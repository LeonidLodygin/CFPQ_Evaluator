from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from .config import Dataset, Solver, solver_uses_placeholder
from .graphs import prepare_graph
from .reporting import append_raw_row, completed_rounds, write_summary
from .runners import (
    IncompatibleSolverError,
    OutOfMemorySolverError,
    SolverError,
    TimeoutSolverError,
    run_solver,
)

ProgressReporter = Callable[[str], None]


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
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_results.csv"
    if force:
        raw_path.unlink(missing_ok=True)
        (out_dir / "summary.md").unlink(missing_ok=True)
    prepared_root = out_dir / "prepared_graphs"
    logs_root = out_dir / "logs"
    total_runs = len(datasets) * len(solvers) * rounds
    run_index = 0

    for dataset in datasets:
        report(progress, f"[dataset] preparing {dataset.name}")
        graph_work = prepared_root / dataset.name
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
                done = 0 if force else completed_rounds(raw_path, solver.id, dataset.name)
                # Without --force, completed rounds are skipped so interrupted
                # experiments can resume from raw_results.csv.
                for round_number in range(done + 1, rounds + 1):
                    run_index += 1
                    report(
                        progress,
                        f"[run {run_index}/{total_runs}] {dataset.name} / "
                        f"{solver.id} / round {round_number} started",
                    )
                    run_work = out_dir / "work" / dataset.name / solver.id / str(round_number)
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
                            logs_root,
                            dataset.name,
                            solver.id,
                            round_number,
                            result.stdout,
                            result.stderr,
                        )
                        row.update(
                            {
                                "status": "ok",
                                "answer_edges": result.answer_edges,
                                "time_sec": result.time_sec,
                                "ram_kb": result.ram_kb,
                            }
                        )
                    except TimeoutSolverError as exc:
                        record_error(
                            logs_root, dataset.name, solver.id, round_number, row, "timeout", exc
                        )
                    except IncompatibleSolverError as exc:
                        record_error(
                            logs_root,
                            dataset.name,
                            solver.id,
                            round_number,
                            row,
                            "incompatible",
                            exc,
                        )
                    except OutOfMemorySolverError as exc:
                        record_error(
                            logs_root, dataset.name, solver.id, round_number, row, "oom", exc
                        )
                    except SolverError as exc:
                        record_error(
                            logs_root, dataset.name, solver.id, round_number, row, "failed", exc
                        )
                    append_raw_row(raw_path, row)
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

    return write_summary(raw_path, out_dir / "summary.md")


def record_error(
    logs_root: Path,
    dataset_name: str,
    solver_id: str,
    round_number: int,
    row: dict[str, str],
    status: str,
    exc: SolverError,
) -> None:
    write_log(logs_root, dataset_name, solver_id, round_number, exc.stdout, exc.stderr)
    row.update({"status": status, "message": exc.summary()})


def report(progress: Optional[ProgressReporter], message: str) -> None:
    if progress:
        progress(message)


def write_log(
    logs_root: Path,
    dataset_name: str,
    solver_id: str,
    round_number: int,
    stdout: str,
    stderr: str,
) -> None:
    log_dir = logs_root / dataset_name / solver_id
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{round_number}.stdout.txt").write_text(stdout, encoding="utf-8")
    (log_dir / f"{round_number}.stderr.txt").write_text(stderr, encoding="utf-8")
