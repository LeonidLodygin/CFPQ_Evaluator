from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .config import Dataset, Solver, solver_uses_placeholder
from .graphs import PreparedGraph, prepare_graph
from .reporting import RawResultRow, append_raw_row, completed_rounds, write_summary
from .runners import RunResult, RunStatus, SolverError, run_solver

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


@dataclass(frozen=True)
class ExperimentContext:
    layout: OutputLayout
    rounds: int
    timeout_sec: Optional[int]
    index_base: str
    force: bool
    cleanup_prepared: bool
    progress: Optional[ProgressReporter]
    total_runs: int


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

    context = ExperimentContext(
        layout=layout,
        rounds=rounds,
        timeout_sec=timeout_sec,
        index_base=index_base,
        force=force,
        cleanup_prepared=cleanup_prepared,
        progress=progress,
        total_runs=len(datasets) * len(solvers) * rounds,
    )
    run_index = 0
    for dataset in datasets:
        run_index = run_dataset(dataset, solvers, context, run_index)

    return write_summary(layout.raw_results, layout.summary)


def run_dataset(
    dataset: Dataset,
    solvers: List[Solver],
    context: ExperimentContext,
    run_index: int,
) -> int:
    prepared = prepare_dataset(dataset, context)
    try:
        # A prepared graph is shared by every solver for this dataset, then
        # optionally removed before moving to the next dataset.
        for solver in solvers:
            done = completed_rounds_for_solver(context, solver, dataset)
            # Without --force, completed rounds are skipped so interrupted
            # experiments can resume from raw_results.csv.
            for round_number in range(done + 1, context.rounds + 1):
                run_index += 1
                run_solver_round(
                    dataset=dataset,
                    solver=solver,
                    prepared=prepared,
                    context=context,
                    round_number=round_number,
                    run_index=run_index,
                )
    finally:
        if context.cleanup_prepared:
            cleanup_prepared_graph(prepared)
    return run_index


def completed_rounds_for_solver(
    context: ExperimentContext, solver: Solver, dataset: Dataset
) -> int:
    if context.force:
        return 0
    return completed_rounds(context.layout.raw_results, solver.id, dataset.name)


def prepare_dataset(dataset: Dataset, context: ExperimentContext) -> PreparedGraph:
    report(context.progress, f"[dataset] preparing {dataset.name}")
    prepared = prepare_graph(
        dataset.graph,
        context.layout.graph_work_dir(dataset.name),
        index_base=context.index_base,
        grammar_path=dataset.grammar,
    )
    report(
        context.progress,
        f"[dataset] prepared {dataset.name}: "
        f"{prepared.vertex_count} vertices, {prepared.edge_count} edges, "
        f"{prepared.label_count} labels",
    )
    return prepared


def run_solver_round(
    dataset: Dataset,
    solver: Solver,
    prepared: PreparedGraph,
    context: ExperimentContext,
    round_number: int,
    run_index: int,
) -> None:
    report(
        context.progress,
        f"[run {run_index}/{context.total_runs}] {dataset.name} / {solver.id} / "
        f"round {round_number} started",
    )
    run_work = context.layout.solver_work_dir(dataset.name, solver.id, round_number)
    if solver_uses_placeholder(solver, "work"):
        run_work.mkdir(parents=True, exist_ok=True)

    row = base_raw_row(dataset, solver, round_number)
    try:
        result = run_solver(
            solver=solver,
            graph_path=prepared.pocr_path,
            graph_dir=dataset.graph,
            grammar_path=dataset.grammar,
            timeout_sec=context.timeout_sec,
            work_dir=run_work,
        )
        write_log(
            context.layout, dataset.name, solver.id, round_number, result.stdout, result.stderr
        )
        apply_success(row, result)
    except SolverError as exc:
        record_error(context.layout, dataset.name, solver.id, round_number, row, exc.status, exc)

    append_raw_row(context.layout.raw_results, row)
    report(
        context.progress,
        f"[run {run_index}/{context.total_runs}] {dataset.name} / {solver.id} / "
        f"round {round_number} -> {row.status}",
    )


def base_raw_row(dataset: Dataset, solver: Solver, round_number: int) -> RawResultRow:
    return RawResultRow(
        solver_id=solver.id,
        solver_label=solver.label,
        dataset=dataset.name,
        graph_dir=str(dataset.graph),
        grammar=str(dataset.grammar),
        round=str(round_number),
    )


def apply_success(row: RawResultRow, result: RunResult) -> None:
    row.status = RunStatus.OK.value
    row.answer_edges = result.answer_edges
    row.time_sec = result.time_sec
    row.ram_kb = result.ram_kb


def cleanup_prepared_graph(prepared: PreparedGraph) -> None:
    prepared.pocr_path.unlink(missing_ok=True)
    try:
        prepared.pocr_path.parent.rmdir()
    except OSError:
        pass


def record_error(
    layout: OutputLayout,
    dataset_name: str,
    solver_id: str,
    round_number: int,
    row: RawResultRow,
    status: RunStatus,
    exc: SolverError,
) -> None:
    write_log(layout, dataset_name, solver_id, round_number, exc.stdout, exc.stderr)
    row.status = status.value
    row.message = exc.summary()


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
