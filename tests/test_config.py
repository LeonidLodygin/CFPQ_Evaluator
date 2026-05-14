from pathlib import Path

import pytest

from cfpq_evaluator.config import (
    Solver,
    load_datasets,
    load_solvers,
    optional_int,
    resolve_dataset_grammar,
    solver_uses_placeholder,
)


def test_load_datasets_resolves_paths_relative_to_csv(tmp_path: Path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    datasets_csv = config_dir / "datasets.csv"
    datasets_csv.write_text(
        "name,graph,grammar\n" "tiny,../graphs/tiny,../grammars/tiny.cnf\n",
        encoding="utf-8",
    )

    datasets = load_datasets(datasets_csv)

    assert len(datasets) == 1
    assert datasets[0].name == "tiny"
    assert datasets[0].graph == (tmp_path / "graphs" / "tiny").resolve()
    assert datasets[0].grammar == (tmp_path / "grammars" / "tiny.cnf").resolve()


def test_load_datasets_rejects_missing_columns(tmp_path: Path):
    datasets_csv = tmp_path / "datasets.csv"
    datasets_csv.write_text("name,graph\nmissing-grammar,g\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain either"):
        load_datasets(datasets_csv)


def test_load_datasets_supports_self_contained_dataset_directory(tmp_path: Path):
    dataset_root = tmp_path / "datasets" / "case"
    (dataset_root / "graph").mkdir(parents=True)
    (dataset_root / "grammar").mkdir()
    (dataset_root / "grammar" / "aa.cnf").write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    datasets_csv = config_dir / "datasets.csv"
    datasets_csv.write_text("name,dataset\ncase,../datasets/case\n", encoding="utf-8")

    datasets = load_datasets(datasets_csv)

    assert datasets[0].name == "case"
    assert datasets[0].graph == dataset_root / "graph"
    assert datasets[0].grammar == dataset_root / "grammar" / "aa.cnf"


def test_load_datasets_supports_grammar_file_column(tmp_path: Path):
    dataset_root = tmp_path / "datasets" / "case"
    (dataset_root / "graph").mkdir(parents=True)
    (dataset_root / "grammar").mkdir()
    (dataset_root / "grammar" / "aa.cnf").write_text("", encoding="utf-8")
    (dataset_root / "grammar" / "vf.cnf").write_text("", encoding="utf-8")
    datasets_csv = tmp_path / "datasets.csv"
    datasets_csv.write_text(
        "name,dataset,grammar_file\ncase,datasets/case,vf.cnf\n", encoding="utf-8"
    )

    datasets = load_datasets(datasets_csv)

    assert datasets[0].grammar == dataset_root / "grammar" / "vf.cnf"


def test_resolve_dataset_grammar_rejects_ambiguous_grammar_dir(tmp_path: Path):
    dataset_root = tmp_path / "case"
    (dataset_root / "grammar").mkdir(parents=True)
    (dataset_root / "grammar" / "a.cnf").write_text("", encoding="utf-8")
    (dataset_root / "grammar" / "b.cnf").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Multiple .cnf"):
        resolve_dataset_grammar(dataset_root, None)


def test_load_solvers_reads_toml_and_resolves_cwd(tmp_path: Path):
    solvers_toml = tmp_path / "solvers.toml"
    solvers_toml.write_text(
        """
[[solver]]
id = "mock"
label = "Mock Solver"
type = "command"
cwd = "../bin"
argv = ["mock", "{graph}"]
edges_regex = "edges (\\\\d+)"
time_regex = "time ([\\\\d.]+)"
""",
        encoding="utf-8",
    )

    solvers = load_solvers(solvers_toml)

    assert len(solvers) == 1
    assert solvers[0].id == "mock"
    assert solvers[0].label == "Mock Solver"
    assert solvers[0].type == "command"
    assert solvers[0].options["cwd"] == str((tmp_path / ".." / "bin").resolve())
    assert solvers[0].options["argv"] == ["mock", "{graph}"]


def test_load_solvers_rejects_empty_file(tmp_path: Path):
    solvers_toml = tmp_path / "solvers.toml"
    solvers_toml.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="No \\[\\[solver\\]\\] entries"):
        load_solvers(solvers_toml)


def test_optional_int():
    assert optional_int(None) is None
    assert optional_int("42") == 42


def test_solver_uses_placeholder_detects_argv_and_command():
    assert solver_uses_placeholder(
        Solver("s", "S", "command", {"argv": ["tool", "{work}"]}),
        "work",
    )
    assert solver_uses_placeholder(
        Solver("s", "S", "command", {"command": "tool --tmp {work}"}),
        "work",
    )
    assert not solver_uses_placeholder(
        Solver("s", "S", "command", {"argv": ["tool", "{graph}"]}),
        "work",
    )
