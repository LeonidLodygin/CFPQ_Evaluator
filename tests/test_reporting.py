import csv
from pathlib import Path

from cfpq_evaluator.reporting import (
    RawResultRow,
    append_raw_row,
    completed_rounds,
    format_metric,
    markdown_table,
    write_summary,
)


def raw_row(
    solver_id: str = "s",
    solver_label: str = "Solver",
    dataset: str = "d",
    round: str = "1",
    status: str = "ok",
    answer_edges: str = "",
    time_sec: str = "",
    ram_kb: str = "",
    message: str = "",
) -> RawResultRow:
    return RawResultRow(
        solver_id=solver_id,
        solver_label=solver_label,
        dataset=dataset,
        graph_dir="/graph",
        grammar="/grammar.cnf",
        round=round,
        status=status,
        answer_edges=answer_edges,
        time_sec=time_sec,
        ram_kb=ram_kb,
        message=message,
    )


def test_append_raw_row_writes_header_and_completed_rounds(tmp_path: Path):
    raw = tmp_path / "raw.csv"

    append_raw_row(raw, raw_row(round="1"))
    append_raw_row(raw, raw_row(round="2"))
    append_raw_row(raw, raw_row(solver_id="other", round="1"))

    with raw.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert rows[0]["solver_id"] == "s"
    assert rows[0]["message"] == ""
    assert completed_rounds(raw, "s", "d") == 2
    assert completed_rounds(raw, "missing", "d") == 0


def test_write_summary_aggregates_successes_and_reports_failures(tmp_path: Path):
    raw = tmp_path / "raw.csv"
    append_raw_row(raw, raw_row(answer_edges="10", time_sec="1.0", ram_kb="100"))
    append_raw_row(raw, raw_row(round="2", answer_edges="10", time_sec="3.0", ram_kb="300"))
    append_raw_row(raw, raw_row(solver_id="bad", solver_label="Bad Solver", status="failed"))

    summary = write_summary(raw, tmp_path / "summary.md")

    assert "| d | Solver | ok | 10 | 2 s +/- 70.7% | 200 KB +/- 70.7% |" in summary
    assert "| d | Bad Solver | failed | - | - | - |" in summary


def test_format_metric_and_markdown_table():
    assert format_metric([], "s") == ""
    assert format_metric([1.234], "s") == "1.23 s"
    assert markdown_table(["a"], [["b"]]) == "| a |\n| --- |\n| b |"
