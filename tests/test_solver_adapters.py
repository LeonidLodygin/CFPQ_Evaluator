from pathlib import Path

import pytest

from cfpq_evaluator import solver_adapters as adapters


def test_read_and_explode_grammar(tmp_path: Path):
    grammar_path = tmp_path / "g.cnf"
    grammar_path.write_text(
        "S\tA_i\tb\n" "A_i\ta_i\n" "\n" "Count:\n" "S\n",
        encoding="utf-8",
    )

    grammar = adapters.read_grammar(grammar_path)
    exploded = adapters.explode_grammar(grammar, 2)

    assert grammar.start == "S"
    assert adapters.Rule("S", ("A_i_0", "b")) in exploded.rules
    assert adapters.Rule("S", ("A_i_1", "b")) in exploded.rules
    assert adapters.Rule("A_i_0", ("a_i_0",)) in exploded.rules
    assert adapters.Rule("A_i_1", ("a_i_1",)) in exploded.rules


def test_read_and_explode_edges(tmp_path: Path):
    graph_path = tmp_path / "g.g"
    graph_path.write_text("0\t1\ta_i\t3\n1\t2\tb\n", encoding="utf-8")

    edges = list(adapters.explode_edges(adapters.read_edges(graph_path)))

    assert edges == [
        adapters.Edge("0", "1", "a_i_3"),
        adapters.Edge("1", "2", "b"),
    ]


def test_write_grammar_without_start_marker(tmp_path: Path):
    path = tmp_path / "out.cnf"
    grammar = adapters.Grammar("S", [adapters.Rule("S", ("a",)), adapters.Rule("E", tuple())])

    adapters.write_grammar(path, grammar, include_start=False)

    assert path.read_text(encoding="utf-8").splitlines() == ["S\ta", "E"]


def test_grammar_has_index_template(tmp_path: Path):
    source = tmp_path / "g.cfg"
    source.write_text('Terminal("load_i_{i}")\n', encoding="utf-8")

    assert adapters.grammar_has_index_template(source)


def test_expand_kotgll_grammar(tmp_path: Path):
    source = tmp_path / "g.cfg"
    target = tmp_path / "out.cfg"
    source.write_text('Terminal("load_i_{i}")\nNoIndex\n', encoding="utf-8")

    adapters.expand_kotgll_grammar(source, target, 3)

    assert target.read_text(encoding="utf-8").splitlines() == [
        'Terminal("load_i_0")',
        'Terminal("load_i_1")',
        'Terminal("load_i_2")',
        "NoIndex",
    ]


def test_count_start_edges(tmp_path: Path):
    final = tmp_path / "final.txt"
    final.write_text("0 1 S\n0 1 S\n1 2 A\n", encoding="utf-8")

    assert adapters.count_start_edges(final, "S") == 1


def test_pocr_adapter_builds_special_command(monkeypatch, tmp_path: Path):
    graph = tmp_path / "g.g"
    grammar = tmp_path / "aa.cnf"
    captured = {}

    def fake_run(command, cwd=None, timeout=None, input_text=None):
        captured["command"] = command
        return completed("#SEdges 7\nAnalysisTime 0.2\n")

    monkeypatch.setattr(adapters, "run", fake_run)

    assert adapters.run_pocr(graph, grammar, None, tmp_path) == (7, 0.2)
    assert captured["command"] == ["aa", "-pocr", str(graph)]


def test_pearl_rejects_unsupported_grammar(tmp_path: Path):
    with pytest.raises(adapters.AdapterError, match="supports only"):
        adapters.run_pearl(tmp_path / "g.g", tmp_path / "other.cnf", None, tmp_path)


def completed(stdout: str):
    class Process:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str):
            self.stdout = stdout

    return Process(stdout)


def test_adapter_cli_routes_to_selected_adapter(monkeypatch, capsys, tmp_path: Path):
    graph = tmp_path / "g.g"
    grammar = tmp_path / "aa.cnf"
    work = tmp_path / "work"
    captured = {}

    def fake_run_pocr(graph_path, grammar_path, timeout, work_path):
        captured.update(
            {
                "graph": graph_path,
                "grammar": grammar_path,
                "timeout": timeout,
                "work": work_path,
            }
        )
        return 11, 0.75

    monkeypatch.setattr(adapters, "run_pocr", fake_run_pocr)

    exit_code = adapters.main(
        [
            "pocr",
            "--graph",
            str(graph),
            "--grammar",
            str(grammar),
            "--timeout",
            "9",
            "--work",
            str(work),
        ]
    )

    assert exit_code == 0
    assert captured == {"graph": graph, "grammar": grammar, "timeout": 9, "work": work}
    assert capsys.readouterr().out.splitlines() == [
        "ORCH_ANSWER_EDGES 11",
        "ORCH_TIME_SEC 0.75",
    ]


def test_adapter_cli_reports_incompatible_solver(monkeypatch, capsys, tmp_path: Path):
    def fake_run_pearl(graph, grammar, timeout, work):
        raise adapters.AdapterError("nope")

    monkeypatch.setattr(adapters, "run_pearl", fake_run_pearl)

    exit_code = adapters.main(
        [
            "pearl",
            "--graph",
            str(tmp_path / "g.g"),
            "--grammar",
            str(tmp_path / "other.cnf"),
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "ORCH_INCOMPATIBLE nope\n"


def test_run_gigascale_writes_relation_csvs(monkeypatch, tmp_path: Path):
    graph = tmp_path / "points.g"
    grammar = tmp_path / "java_points_to.cnf"
    work = tmp_path / "work"
    graph.write_text(
        "0\t1\talloc\n" "2\t3\tassign\n" "4\t5\tload_i\t7\n" "6\t7\tstore_i\t8\n",
        encoding="utf-8",
    )
    grammar.write_text("S\talloc\n\nCount:\nS\n", encoding="utf-8")
    monkeypatch.setenv("GIGASCALE_DIR", str(tmp_path))
    monkeypatch.setattr(adapters.shutil, "which", lambda name: None)
    captured = {}

    def fake_run(command, cwd=None, timeout=None, input_text=None):
        captured.update({"command": command, "cwd": cwd, "timeout": timeout})
        return completed(
            "benchmark TC-time TC-mem v e vpt avg max load/f store/f\n"
            "case 0.33 1 2 3 42 0 0 0 0\n"
        )

    monkeypatch.setattr(adapters, "run", fake_run)

    assert adapters.run_gigascale(graph, grammar, 5, work) == (42, 0.33)
    target = work / "gigascale" / "points"
    assert (target / "Alloc.csv").read_text(encoding="utf-8") == '"var_0","var_1"\n'
    assert (target / "Assign.csv").read_text(encoding="utf-8") == '"var_3","var_2"\n'
    assert (target / "Load.csv").read_text(encoding="utf-8") == '"var_5","var_4","field_7"\n'
    assert (target / "Store.csv").read_text(encoding="utf-8") == '"var_7","var_6","field_8"\n'
    assert captured == {
        "command": ["./run.sh", "-wdlrb", "-i", str(target)],
        "cwd": tmp_path,
        "timeout": 5,
    }


def test_run_gigascale_rejects_non_points_to_grammar(tmp_path: Path):
    with pytest.raises(adapters.AdapterError, match="java_points_to"):
        adapters.run_gigascale(tmp_path / "g.g", tmp_path / "aa.cnf", None, tmp_path)


def test_run_graspan_expands_indexed_inputs_and_counts_start_edges(monkeypatch, tmp_path: Path):
    graph = tmp_path / "g.g"
    grammar_path = tmp_path / "g.cnf"
    final_file = tmp_path / "final.out"
    graph.write_text("0\t1\tload_i\t0\n1\t2\tload_i\t1\n", encoding="utf-8")
    grammar_path.write_text("S\tload_i\n\nCount:\nS\n", encoding="utf-8")
    monkeypatch.setenv("GRASPAN_DIR", str(tmp_path))
    monkeypatch.setattr(adapters, "total_memory_gb", lambda: 2.0)
    monkeypatch.setattr(adapters.os, "cpu_count", lambda: 3)
    captured = {}

    def fake_run(command, cwd=None, timeout=None, input_text=None):
        captured.update({"command": command, "cwd": cwd, "timeout": timeout})
        final_file.write_text("0 1 S\n0 1 S\n1 2 S\n", encoding="utf-8")
        return completed(f"finalFile: {final_file}\nCOMP TIME: 1.5\n")

    monkeypatch.setattr(adapters, "run", fake_run)

    assert adapters.run_graspan(graph, grammar_path, 10, tmp_path / "work") == (2, 1.5)
    generated_graph = tmp_path / "work" / "graspan" / "g.g"
    generated_grammar = tmp_path / "work" / "graspan" / "g.cnf"
    assert generated_graph.read_text(encoding="utf-8").splitlines() == [
        "0\t1\tload_i_0",
        "1\t2\tload_i_1",
    ]
    assert generated_grammar.read_text(encoding="utf-8").splitlines() == [
        "S\tload_i_0",
        "S\tload_i_1",
    ]
    assert captured["command"][-2:] == ["1", "6"]
    assert captured["cwd"] == tmp_path / "src"
    assert not final_file.exists()


def test_run_kotgll_expands_template_grammar_and_graph(monkeypatch, tmp_path: Path):
    graph = tmp_path / "g.g"
    grammar_path = tmp_path / "grammar" / "q.cnf"
    kotgll_grammar = grammar_path.parent / "kotgll" / "q.cfg"
    graph.write_text("0\t1\tload_i\t0\n1\t2\tplain\n", encoding="utf-8")
    grammar_path.parent.mkdir()
    grammar_path.write_text("S\tload_i\n\nCount:\nS\n", encoding="utf-8")
    kotgll_grammar.parent.mkdir()
    kotgll_grammar.write_text('Terminal("load_i_{i}")\nTerminal("plain")\n', encoding="utf-8")
    monkeypatch.setenv("KOTGLL_DIR", str(tmp_path))
    monkeypatch.setattr(adapters, "total_memory_gb", lambda: 4.0)
    captured = {}

    def fake_run(command, cwd=None, timeout=None, input_text=None):
        captured.update({"command": command, "cwd": cwd, "timeout": timeout})
        grammar_arg = Path(command[command.index("--grammarPath") + 1])
        graph_dir = Path(command[command.index("--inputPath") + 1])
        captured["grammar_text"] = grammar_arg.read_text(encoding="utf-8")
        captured["graph_text"] = (graph_dir / "g.g").read_text(encoding="utf-8")
        return completed("benchmark:: case 13 0.44\n")

    monkeypatch.setattr(adapters, "run", fake_run)

    assert adapters.run_kotgll(graph, grammar_path, 6, tmp_path / "work") == (13, 0.44)
    assert captured["grammar_text"] == 'Terminal("load_i_0")\nTerminal("plain")\n'
    assert captured["graph_text"].splitlines() == ["0 1 load_i_0", "1 2 plain"]
    assert captured["command"][1] == "-Xmx3G"
    assert captured["timeout"] == 12


def test_run_kotgll_rejects_missing_solver_grammar(tmp_path: Path):
    grammar_path = tmp_path / "grammar" / "q.cnf"
    grammar_path.parent.mkdir()
    grammar_path.write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")

    with pytest.raises(adapters.AdapterError, match="missing kotgll grammar"):
        adapters.run_kotgll(tmp_path / "g.g", grammar_path, None, tmp_path)


def test_parse_required_raises_on_missing_pattern():
    with pytest.raises(adapters.AdapterError, match="could not parse pattern"):
        adapters.parse_required("nothing", r"Answer (\\d+)")
