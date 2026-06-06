from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


@dataclass(frozen=True)
class Dataset:
    name: str
    graph: Path
    grammar: Path


@dataclass(frozen=True)
class Solver:
    id: str
    label: str
    type: str
    options: Dict[str, Any] = field(default_factory=dict)


def _resolve_path(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_datasets(path: Path) -> List[Dataset]:
    base = path.resolve().parent
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        if "name" not in fieldnames:
            raise ValueError(f"Dataset file {path} is missing columns: ['name']")
        has_explicit_paths = {"graph", "grammar"}.issubset(fieldnames)
        has_dataset_path = "dataset" in fieldnames
        if not has_explicit_paths and not has_dataset_path:
            raise ValueError(
                f"Dataset file {path} must contain either columns "
                "['name', 'graph', 'grammar'] or ['name', 'dataset']"
            )

        datasets = []
        for row in reader:
            if has_dataset_path and row.get("dataset"):
                dataset_root = _resolve_path(row["dataset"], base)
                graph_path = dataset_root / "graph"
                grammar_path = resolve_dataset_grammar(dataset_root, row.get("grammar_file"))
            else:
                graph_path = _resolve_path(row["graph"], base)
                grammar_path = _resolve_path(row["grammar"], base)
            datasets.append(
                Dataset(
                    name=row["name"],
                    graph=graph_path,
                    grammar=grammar_path,
                )
            )
        return datasets


def resolve_dataset_grammar(dataset_root: Path, grammar_file: Optional[str]) -> Path:
    grammar_dir = dataset_root / "grammar"
    if grammar_file:
        return grammar_dir / grammar_file

    grammars = sorted(grammar_dir.glob("*.cnf"))
    if len(grammars) == 1:
        return grammars[0]
    if not grammars:
        raise ValueError(f"No .cnf grammar files found in {grammar_dir}")
    raise ValueError(
        f"Multiple .cnf grammar files found in {grammar_dir}. "
        "Add a 'grammar_file' column to the dataset CSV."
    )


def load_solvers(path: Path) -> List[Solver]:
    base = path.resolve().parent
    with path.open("rb") as file:
        data = tomllib.load(file)

    solvers = []
    for raw in data.get("solver", []):
        options = dict(raw)
        solver_id = options.pop("id")
        label = options.pop("label", solver_id)
        solver_type = options.pop("type")

        for key in ("repo", "cwd"):
            if key in options and options[key] is not None:
                options[key] = str(_resolve_path(str(options[key]), base))

        solvers.append(Solver(id=solver_id, label=label, type=solver_type, options=options))

    if not solvers:
        raise ValueError(f"No [[solver]] entries found in {path}")
    return solvers


def optional_int(value: Optional[str]) -> Optional[int]:
    return None if value is None else int(value)


def solver_uses_placeholder(solver: Solver, placeholder: str) -> bool:
    needle = "{" + placeholder + "}"
    for key in ("command",):
        value = solver.options.get(key)
        if isinstance(value, str) and needle in value:
            return True
    for key in ("argv",):
        value = solver.options.get(key)
        if isinstance(value, list) and any(needle in str(part) for part in value):
            return True
    return False
