from pathlib import Path

from cfpq_evaluator import cli
from cfpq_evaluator.config import Dataset, Solver


def test_plan_command_prints_loaded_datasets_and_solvers(monkeypatch, capsys, tmp_path: Path):
    dataset = Dataset("case", tmp_path / "graph", tmp_path / "grammar.cnf")
    solver = Solver("mock", "Mock Solver", "command", {})

    monkeypatch.setattr(cli, "load_datasets", lambda path: [dataset])
    monkeypatch.setattr(cli, "load_solvers", lambda path: [solver])

    exit_code = cli.main(["plan", "--datasets", "datasets.csv", "--solvers", "solvers.toml"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Datasets:" in output
    assert f"case: graph={dataset.graph}, grammar={dataset.grammar}" in output
    assert "mock: Mock Solver (command)" in output


def test_run_command_passes_cli_options_to_engine(monkeypatch, capsys, tmp_path: Path):
    dataset = Dataset("case", tmp_path / "graph", tmp_path / "grammar.cnf")
    solver = Solver("mock", "Mock Solver", "command", {})
    captured = {}

    monkeypatch.setattr(cli, "load_datasets", lambda path: [dataset])
    monkeypatch.setattr(cli, "load_solvers", lambda path: [solver])

    def fake_run_experiments(**kwargs):
        captured.update(kwargs)
        return "| summary |\n"

    monkeypatch.setattr(cli, "run_experiments", fake_run_experiments)

    exit_code = cli.main(
        [
            "run",
            "--datasets",
            "datasets.csv",
            "--solvers",
            "solvers.toml",
            "--out",
            str(tmp_path / "out"),
            "--rounds",
            "3",
            "--timeout",
            "42",
            "--mtx-base",
            "zero",
            "--cleanup-prepared",
            "--force",
            "--quiet",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "| summary |\n\n"
    assert captured == {
        "datasets": [dataset],
        "solvers": [solver],
        "out_dir": tmp_path / "out",
        "rounds": 3,
        "timeout_sec": 42,
        "index_base": "zero",
        "force": True,
        "cleanup_prepared": True,
        "progress": None,
    }


def test_run_command_uses_stdout_progress_by_default(monkeypatch, tmp_path: Path):
    dataset = Dataset("case", tmp_path / "graph", tmp_path / "grammar.cnf")
    solver = Solver("mock", "Mock Solver", "command", {})
    captured = {}

    monkeypatch.setattr(cli, "load_datasets", lambda path: [dataset])
    monkeypatch.setattr(cli, "load_solvers", lambda path: [solver])

    def fake_run_experiments(**kwargs):
        captured.update(kwargs)
        kwargs["progress"]("hello")
        return "summary"

    monkeypatch.setattr(cli, "run_experiments", fake_run_experiments)

    assert cli.main(["run", "--datasets", "d.csv", "--solvers", "s.toml", "--out", "out"]) == 0
    assert captured["progress"] is print
