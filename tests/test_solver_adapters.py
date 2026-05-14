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
