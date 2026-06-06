from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_datasets, load_solvers
from .engine import run_experiments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cfpq-eval",
        description=(
            "Run repeatable CFPQ solver evaluation experiments on Matrix Market graph folders."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run experiments")
    run.add_argument(
        "--datasets", required=True, type=Path, help="CSV with name,graph,grammar columns"
    )
    run.add_argument(
        "--solvers", required=True, type=Path, help="TOML file with [[solver]] entries"
    )
    run.add_argument("--out", required=True, type=Path, help="Output directory")
    run.add_argument("--rounds", type=int, default=1, help="Rounds per solver/dataset pair")
    run.add_argument("--timeout", type=int, default=None, help="Timeout per round, seconds")
    run.add_argument(
        "--mtx-base",
        choices=["auto", "zero", "one"],
        default="auto",
        help="Matrix Market vertex numbering convention",
    )
    run.add_argument(
        "--force", action="store_true", help="Replace existing raw results and run rounds from 1"
    )
    run.add_argument(
        "--cleanup-prepared",
        action="store_true",
        help="Delete generated .g files after each dataset has finished.",
    )
    run.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the final summary table.",
    )

    plan = subparsers.add_parser("plan", help="Print loaded datasets and solvers")
    plan.add_argument("--datasets", required=True, type=Path)
    plan.add_argument("--solvers", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    datasets = load_datasets(args.datasets)
    solvers = load_solvers(args.solvers)

    if args.command == "plan":
        print("Datasets:")
        for dataset in datasets:
            print(f"  - {dataset.name}: graph={dataset.graph}, grammar={dataset.grammar}")
        print("Solvers:")
        for solver in solvers:
            print(f"  - {solver.id}: {solver.label} ({solver.type})")
        return 0

    if args.command == "run":
        summary = run_experiments(
            datasets=datasets,
            solvers=solvers,
            out_dir=args.out,
            rounds=args.rounds,
            timeout_sec=args.timeout,
            index_base=args.mtx_base,
            force=args.force,
            cleanup_prepared=args.cleanup_prepared,
            progress=None if args.quiet else print,
        )
        print(summary)
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
