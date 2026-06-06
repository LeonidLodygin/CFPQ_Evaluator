from pathlib import Path

import pytest

from cfpq_evaluator.graphs import (
    detect_base,
    label_from_matrix_name,
    prepare_graph,
    read_matrix_market,
)


def write_mtx(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "%%MatrixMarket matrix coordinate pattern general\n" "%%GraphBLAS type bool\n" f"{body}",
        encoding="utf-8",
    )


def test_label_from_matrix_name_plain_and_indexed():
    assert label_from_matrix_name("a") == ("a", None)
    assert label_from_matrix_name("load_i_3") == ("load_i", 3)
    assert label_from_matrix_name("load_i.7") == ("load_i", 7)
    assert label_from_matrix_name("load_i-11") == ("load_i", 11)
    indexed = {"load_i", "store_i", "load_r_i", "store_r_i", "call_i", "ret_i"}
    assert label_from_matrix_name("load_3", indexed) == ("load_i", 3)
    assert label_from_matrix_name("store_4", indexed) == ("store_i", 4)
    assert label_from_matrix_name("load_r_7", indexed) == ("load_r_i", 7)
    assert label_from_matrix_name("store_r_8", indexed) == ("store_r_i", 8)
    assert label_from_matrix_name("call_5", indexed) == ("call_i", 5)
    assert label_from_matrix_name("ret_6", indexed) == ("ret_i", 6)
    assert label_from_matrix_name("load_3") == ("load_3", None)
    assert label_from_matrix_name("field_9", {"field_i"}) == ("field_i", 9)


def test_read_matrix_market_skips_comments_and_reads_entries(tmp_path: Path):
    matrix = tmp_path / "a.mtx"
    write_mtx(matrix, "3 3 2\n1 2\n2 3\n")

    rows, cols, declared_edges, entries = read_matrix_market(matrix)

    assert (rows, cols, declared_edges) == (3, 3, 2)
    assert entries == [(1, 2), (2, 3)]


def test_detect_base_modes():
    assert detect_base([(0, 1), (1, 2)], "auto") == 0
    assert detect_base([(1, 2), (2, 3)], "auto") == 1
    assert detect_base([(1, 2)], "zero") == 0
    assert detect_base([(1, 2)], "one") == 1
    with pytest.raises(ValueError, match="index base"):
        detect_base([(1, 2)], "two")


def test_prepare_graph_converts_mtx_directory_to_pocr_graph(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    write_mtx(graph_dir / "a.mtx", "3 3 2\n1 2\n2 3\n")
    write_mtx(graph_dir / "load_i_5.mtx", "3 3 1\n3 1\n")

    prepared = prepare_graph(graph_dir, tmp_path / "prepared", index_base="one")

    assert prepared.source_dir == graph_dir
    assert prepared.edge_count == 3
    assert prepared.label_count == 2
    assert prepared.vertex_count == 3
    assert prepared.pocr_path.read_text(encoding="utf-8").splitlines() == [
        "0\t1\ta",
        "1\t2\ta",
        "2\t0\tload_i\t5",
    ]


def test_prepare_graph_uses_grammar_to_infer_short_indexed_labels(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    grammar = tmp_path / "grammar" / "g.cnf"
    write_mtx(graph_dir / "field_9.mtx", "4 4 1\n1 2\n")
    write_mtx(graph_dir / "plain_9.mtx", "4 4 1\n2 3\n")
    grammar.parent.mkdir()
    grammar.write_text("S\tfield_i\nS\tplain\n\nCount:\nS\n", encoding="utf-8")

    prepared = prepare_graph(
        graph_dir, tmp_path / "prepared", index_base="one", grammar_path=grammar
    )

    assert prepared.pocr_path.read_text(encoding="utf-8").splitlines() == [
        "0\t1\tfield_i\t9",
        "1\t2\tplain_9",
    ]


def test_prepare_graph_auto_base_is_global_across_labels(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    write_mtx(graph_dir / "a.mtx", "5 5 1\n0 1\n")
    write_mtx(graph_dir / "b.mtx", "5 5 1\n3 4\n")

    prepared = prepare_graph(graph_dir, tmp_path / "prepared", index_base="auto")

    assert prepared.pocr_path.read_text(encoding="utf-8").splitlines() == [
        "0\t1\ta",
        "3\t4\tb",
    ]


def test_prepare_graph_rejects_missing_mtx_files(tmp_path: Path):
    graph_dir = tmp_path / "empty"
    graph_dir.mkdir()

    with pytest.raises(ValueError, match="No .mtx files"):
        prepare_graph(graph_dir, tmp_path / "prepared")


def test_prepare_graph_validates_declared_edge_count(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    write_mtx(graph_dir / "a.mtx", "3 3 2\n1 2\n")

    with pytest.raises(ValueError, match="declares 2 edges"):
        prepare_graph(graph_dir, tmp_path / "prepared", index_base="one")
