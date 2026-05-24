from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .config import Dataset, Solver, solver_uses_placeholder
from .graphs import prepare_graph
from .reporting import append_raw_row, completed_rounds, write_summary
from .runners import RunStatus, SolverError, run_solver

ProgressReporter = Callable[[str], None]


@dataclass(frozen=True)
class OutputLayout:
    root: Path

    @classmethod
    def create(cls, out_dir: Path) -> "OutputLayout":
        root = out_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return cls(root)

    @property
    def raw_results(self) -> Path:
        return self.root / "raw_results.csv"

    @property
    def summary(self) -> Path:
        return self.root / "summary.md"

    @property
    def prepared_graphs(self) -> Path:
        return self.root / "prepared_graphs"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def work(self) -> Path:
        return self.root / "work"

    def graph_work_dir(self, dataset_name: str) -> Path:
        return self.prepared_graphs / dataset_name

    def solver_work_dir(self, dataset_name: str, solver_id: str, round_number: int) -> Path:
        return self.work / dataset_name / solver_id / str(round_number)

    def log_dir(self, dataset_name: str, solver_id: str) -> Path:
        return self.logs / dataset_name / solver_id

    def reset_run_outputs(self) -> None:
        self.raw_results.unlink(missing_ok=True)
        self.summary.unlink(missing_ok=True)


def run_experiments(
    datasets: List[Dataset],
    solvers: List[Solver],
    out_dir: Path,
    rounds: int,
    timeout_sec: Optional[int],
    index_base: str,
    force: bool,
    cleanup_prepared: bool = False,
    progress: Optional[ProgressReporter] = None,
) -> str:
    layout = OutputLayout.create(out_dir)
    if force:
        layout.reset_run_outputs()
    total_runs = len(datasets) * len(solvers) * rounds
    run_index = 0

    for dataset in datasets:
        report(progress, f"[dataset] preparing {dataset.name}")
        graph_work = layout.graph_work_dir(dataset.name)
        prepared = prepare_graph(
            dataset.graph,
            graph_work,
            index_base=index_base,
            grammar_path=dataset.grammar,
        )
        report(
            progress,
            f"[dataset] prepared {dataset.name}: "
            f"{prepared.vertex_count} vertices, {prepared.edge_count} edges, "
            f"{prepared.label_count} labels",
        )
        try:
            # A prepared graph is shared by every solver for this dataset, then
            # optionally removed before moving to the next dataset.
            for solver in solvers:
                done = 0 if force else completed_rounds(layout.raw_results, solver.id, dataset.name)
                # Without --force, completed rounds are skipped so interrupted
                # experiments can resume from raw_results.csv.
                for round_number in range(done + 1, rounds + 1):
                    run_index += 1
                    report(
                        progress,
                        f"[run {run_index}/{total_runs}] {dataset.name} / "
                        f"{solver.id} / round {round_number} started",
                    )
                    run_work = layout.solver_work_dir(dataset.name, solver.id, round_number)
                    if solver_uses_placeholder(solver, "work"):
                        run_work.mkdir(parents=True, exist_ok=True)
                    row = {
                        "solver_id": solver.id,
                        "solver_label": solver.label,
                        "dataset": dataset.name,
                        "graph_dir": str(dataset.graph),
                        "grammar": str(dataset.grammar),
                        "round": str(round_number),
                    }
                    try:
                        result = run_solver(
                            solver=solver,
                            graph_path=prepared.pocr_path,
                            graph_dir=dataset.graph,
                            grammar_path=dataset.grammar,
                            timeout_sec=timeout_sec,
                            work_dir=run_work,
                        )
                        write_log(
                            layout,
                            dataset.name,
                            solver.id,
                            round_number,
                            result.stdout,
                            result.stderr,
                        )
                        row.update(
                            {
                                "status": RunStatus.OK.value,
                                "answer_edges": result.answer_edges,
                                "time_sec": result.time_sec,
                                "ram_kb": result.ram_kb,
                            }
                        )
                    except SolverError as exc:
                        record_error(
                            layout,
                            dataset.name,
                            solver.id,
                            round_number,
                            row,
                            exc.status,
                            exc,
                        )
                    append_raw_row(layout.raw_results, row)
                    report(
                        progress,
                        f"[run {run_index}/{total_runs}] {dataset.name} / "
                        f"{solver.id} / round {round_number} -> {row['status']}",
                    )
        finally:
            # Cleanup happens after all solvers have consumed this dataset.
            if cleanup_prepared:
                prepared.pocr_path.unlink(missing_ok=True)
                try:
                    prepared.pocr_path.parent.rmdir()
                except OSError:
                    pass

    return write_summary(layout.raw_results, layout.summary)


def record_error(
    layout: OutputLayout,
    dataset_name: str,
    solver_id: str,
    round_number: int,
    row: dict[str, str],
    status: RunStatus,
    exc: SolverError,
) -> None:
    write_log(layout, dataset_name, solver_id, round_number, exc.stdout, exc.stderr)
    row.update({"status": status.value, "message": exc.summary()})


def report(progress: Optional[ProgressReporter], message: str) -> None:
    if progress:
        progress(message)


def write_log(
    layout: OutputLayout,
    dataset_name: str,
    solver_id: str,
    round_number: int,
    stdout: str,
    stderr: str,
) -> None:
    log_dir = layout.log_dir(dataset_name, solver_id)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{round_number}.stdout.txt").write_text(stdout, encoding="utf-8")
    (log_dir / f"{round_number}.stderr.txt").write_text(stderr, encoding="utf-8")
