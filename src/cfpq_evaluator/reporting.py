from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, Iterable, List

RAW_HEADER = [
    "solver_id",
    "solver_label",
    "dataset",
    "graph_dir",
    "grammar",
    "round",
    "status",
    "answer_edges",
    "time_sec",
    "ram_kb",
    "message",
]


@dataclass
class RawResultRow:
    solver_id: str
    solver_label: str
    dataset: str
    graph_dir: str
    grammar: str
    round: str
    status: str = ""
    answer_edges: str = ""
    time_sec: str = ""
    ram_kb: str = ""
    message: str = ""

    def to_csv_row(self) -> Dict[str, str]:
        data = asdict(self)
        return {key: str(data.get(key, "")) for key in RAW_HEADER}


def append_raw_row(path: Path, row: RawResultRow) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=RAW_HEADER)
        if not exists:
            writer.writeheader()
        writer.writerow(row.to_csv_row())


def completed_rounds(path: Path, solver_id: str, dataset: str) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["solver_id"] == solver_id and row["dataset"] == dataset:
                count += 1
    return count


def write_summary(raw_path: Path, summary_path: Path) -> str:
    rows = list(read_rows(raw_path))
    grouped: Dict[tuple, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["dataset"], row["solver_label"])].append(row)

    summary_rows = []
    for (dataset, solver_label), group in sorted(grouped.items()):
        ok = [row for row in group if row["status"] == "ok"]
        if not ok:
            status = group[-1]["status"]
            summary_rows.append([dataset, solver_label, status, "-", "-", "-"])
            continue

        times = [float(row["time_sec"]) for row in ok if row["time_sec"]]
        rams = [float(row["ram_kb"]) for row in ok if row["ram_kb"]]
        edges = ok[0]["answer_edges"]
        summary_rows.append(
            [
                dataset,
                solver_label,
                "ok",
                edges,
                format_metric(times, "s"),
                format_metric(rams, "KB") if rams else "",
            ]
        )

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        file.write(
            markdown_table(
                ["dataset", "solver", "status", "answer_edges", "time", "peak_rss"],
                summary_rows,
            )
        )
        file.write("\n")
    return summary_path.read_text(encoding="utf-8")


def read_rows(path: Path) -> Iterable[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        yield from csv.DictReader(file)


def format_metric(values: List[float], unit: str) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return f"{values[0]:.3g} {unit}"
    avg = mean(values)
    sd = stdev(values)
    return f"{avg:.3g} {unit} +/- {sd / avg * 100:.1f}%" if avg else f"{avg:.3g} {unit}"


def markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    table = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        table.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(table)
