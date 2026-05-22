from pathlib import Path

import pytest

from cfpq_evaluator.config import Solver
from cfpq_evaluator.runners import (
    CommandRunner,
    IncompatibleSolverError,
    OutOfMemorySolverError,
    RunResult,
    is_oom,
    parse_required,
    rewritten_grammar_path,
    run_solver,
)


def test_rewritten_grammar_path_prefers_existing_rewritten_file(tmp_path: Path):
    grammar = tmp_path / "g.cnf"
    rewritten = tmp_path / "g_rewritten.cnf"
    grammar.write_text("original", encoding="utf-8")
    rewritten.write_text("rewritten", encoding="utf-8")

    assert rewritten_grammar_path(grammar) == rewritten


def test_rewritten_grammar_path_falls_back_to_original(tmp_path: Path):
    grammar = tmp_path / "g.cnf"
    grammar.write_text("original", encoding="utf-8")

    assert rewritten_grammar_path(grammar) == grammar


def test_parse_required_returns_first_group():
    assert parse_required("AnalysisTime 1.25", r"AnalysisTime\s+([\d.]+)") == "1.25"


def test_parse_required_raises_for_missing_pattern():
    with pytest.raises(IncompatibleSolverError, match="Could not parse"):
        parse_required("no result", r"#SEdges\s+(\d+)")


def test_is_oom_detects_common_signals():
    assert is_oom(137, "", "")
    assert is_oom(-9, "", "")
    assert is_oom(1, "", "java.lang.OutOfMemoryError")
    assert is_oom(1, "", "Cannot allocate memory")


def test_command_runner_reports_adapter_incompatible_marker(monkeypatch, tmp_path: Path):
    def fake_run_process(self, command, cwd, timeout_sec, env):
        return RunResult(
            answer_edges="",
            time_sec="",
            ram_kb="",
            stdout="EVAL_INCOMPATIBLE missing kotgll grammar\n",
            stderr="",
        )

    monkeypatch.setattr(CommandRunner, "run_process", fake_run_process)
    solver = Solver(
        id="mock",
        label="Mock",
        type="command",
        options={
            "argv": ["tool"],
            "edges_regex": r"EVAL_ANSWER_EDGES\s+(\d+)",
            "time_regex": r"EVAL_TIME_SEC\s+([\d.]+)",
        },
    )

    with pytest.raises(IncompatibleSolverError, match="missing kotgll grammar"):
        CommandRunner(solver).run(
            graph_path=tmp_path / "g.g",
            graph_dir=tmp_path / "graph",
            grammar_path=tmp_path / "g.cnf",
            timeout_sec=None,
            work_dir=tmp_path / "work",
        )


def test_process_runner_classifies_oom(monkeypatch):
    class Process:
        returncode = 137
        stdout = ""
        stderr = "Killed"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Process())

    with pytest.raises(OutOfMemorySolverError):
        CommandRunner(
            Solver(
                id="mock",
                label="Mock",
                type="command",
                options={"argv": ["tool"], "edges_regex": "x", "time_regex": "y"},
            )
        ).run_process(["tool"], cwd=None, timeout_sec=None)


def test_command_runner_substitutes_placeholders_and_parses_output(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run_process(self, command, cwd, timeout_sec, env):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout_sec
        captured["env"] = env
        return RunResult(
            answer_edges="",
            time_sec="",
            ram_kb="123",
            stdout="#SEdges 9\nAnalysisTime 0.5\n",
            stderr="",
        )

    monkeypatch.setattr(CommandRunner, "run_process", fake_run_process)
    grammar = tmp_path / "grammar.cnf"
    rewritten = tmp_path / "grammar_rewritten.cnf"
    grammar.write_text("", encoding="utf-8")
    rewritten.write_text("", encoding="utf-8")
    solver = Solver(
        id="mock",
        label="Mock",
        type="command",
        options={
            "cwd": str(tmp_path),
            "argv": [
                "tool",
                "--graph",
                "{graph}",
                "--mtx",
                "{graph_mtx_dir}",
                "--grammar",
                "{grammar_rewritten}",
                "--work",
                "{work}",
                "--timeout",
                "{timeout}",
            ],
            "edges_regex": r"#SEdges\s+(\d+)",
            "time_regex": r"AnalysisTime\s+([\d.]+)",
            "env": {"A": "B"},
        },
    )

    result = CommandRunner(solver).run(
        graph_path=tmp_path / "prepared.g",
        graph_dir=tmp_path / "graph-dir",
        grammar_path=grammar,
        timeout_sec=7,
        work_dir=tmp_path / "work",
    )

    assert result.answer_edges == "9"
    assert result.time_sec == "0.5"
    assert result.ram_kb == "123"
    assert captured["command"] == [
        "tool",
        "--graph",
        str(tmp_path / "prepared.g"),
        "--mtx",
        str(tmp_path / "graph-dir"),
        "--grammar",
        str(rewritten),
        "--work",
        str(tmp_path / "work"),
        "--timeout",
        "7",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 7
    assert captured["env"]["A"] == "B"


def test_command_runner_respects_only_grammars(tmp_path: Path):
    solver = Solver(
        id="mock",
        label="Mock",
        type="command",
        options={
            "argv": ["tool"],
            "edges_regex": r"edges (\d+)",
            "time_regex": r"time ([\d.]+)",
            "only_grammars": ["supported"],
        },
    )

    with pytest.raises(IncompatibleSolverError, match="does not support"):
        CommandRunner(solver).run(
            graph_path=tmp_path / "g.g",
            graph_dir=tmp_path / "graph",
            grammar_path=tmp_path / "other.cnf",
            timeout_sec=None,
            work_dir=tmp_path / "work",
        )


def test_run_solver_rejects_unknown_type(tmp_path: Path):
    solver = Solver(id="x", label="X", type="unknown", options={})

    with pytest.raises(ValueError, match="Unknown solver type"):
        run_solver(solver, tmp_path / "g.g", tmp_path / "graph", tmp_path / "g.cnf", None, tmp_path)
