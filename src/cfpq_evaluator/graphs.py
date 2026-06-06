from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Set, Tuple


@dataclass(frozen=True)
class PreparedGraph:
    source_dir: Path
    pocr_path: Path
    edge_count: int
    label_count: int
    vertex_count: int


@dataclass(frozen=True)
class MatrixInfo:
    rows: int
    cols: int
    declared_edges: Optional[int]
    index_base: int


def prepare_graph(
    graph_dir: Path,
    work_dir: Path,
    index_base: str = "auto",
    grammar_path: Optional[Path] = None,
) -> PreparedGraph:
    if not graph_dir.is_dir():
        raise ValueError(f"Graph path must be a directory with .mtx files: {graph_dir}")

    mtx_files = sorted(graph_dir.glob("*.mtx"))
    if not mtx_files:
        raise ValueError(f"No .mtx files found in graph directory: {graph_dir}")

    work_dir.mkdir(parents=True, exist_ok=True)
    output = work_dir / f"{graph_dir.name}.g"
    # Some labels are encoded as many Matrix Market files, for example
    # load_i_7.mtx -> "load_i 7". Grammar context disambiguates short
    # names such as load_7.mtx without affecting ordinary labels.
    indexed_labels = indexed_labels_from_grammar(grammar_path) if grammar_path else set()

    # Base conversion must be graph-wide. Detecting it per label can shift
    # only part of a graph and silently change CFPQ results.
    graph_base = detect_graph_base(mtx_files, index_base)

    edge_count = 0
    vertex_count = 0
    with output.open("w", encoding="utf-8", newline="") as out:
        for matrix_path in mtx_files:
            label, label_index = label_from_matrix_name(matrix_path.stem, indexed_labels)
            info = scan_matrix_market(matrix_path)
            vertex_count = max(vertex_count, info.rows, info.cols)

            written_for_label = 0
            # Stream coordinates instead of materializing large matrices in RAM.
            for source, target in iter_matrix_market_edges(matrix_path):
                if graph_base == 1:
                    source -= 1
                    target -= 1
                if source < 0 or target < 0:
                    raise ValueError(
                        f"Negative vertex id after base conversion in {matrix_path}: "
                        f"{source}, {target}"
                    )
                if label_index is None:
                    out.write(f"{source}\t{target}\t{label}\n")
                else:
                    out.write(f"{source}\t{target}\t{label}\t{label_index}\n")
                written_for_label += 1

            if info.declared_edges is not None and info.declared_edges != written_for_label:
                raise ValueError(
                    f"Matrix {matrix_path} declares {info.declared_edges} edges, "
                    f"but {written_for_label} entries were read"
                )
            edge_count += written_for_label

    return PreparedGraph(
        source_dir=graph_dir,
        pocr_path=output,
        edge_count=edge_count,
        label_count=len(mtx_files),
        vertex_count=vertex_count,
    )


def label_from_matrix_name(
    stem: str,
    indexed_labels: Optional[Set[str]] = None,
) -> Tuple[str, Optional[int]]:
    """Map a Matrix Market file stem to a graph label and optional block index.

    Explicit indexed names keep working without grammar context:
    load_i_3.mtx -> label=load_i, index=3. Short names such as
    load_3.mtx become indexed only when the grammar contains load_i.
    """
    match = re.match(r"^(?P<label>.+_i)[._-](?P<index>\d+)$", stem)
    if match:
        return match.group("label"), int(match.group("index"))

    match = re.match(r"^(?P<label>.+)[._-](?P<index>\d+)$", stem)
    if match and indexed_labels:
        candidate = f"{match.group('label')}_i"
        if candidate in indexed_labels:
            return candidate, int(match.group("index"))

    return stem, None


def indexed_labels_from_grammar(path: Path) -> Set[str]:
    # Tokens ending with _i represent indexed edge families in the .g format.
    labels: Set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line == "Count:":
            continue
        for token in line.split():
            if token.endswith("_i"):
                labels.add(token)
    return labels


def detect_graph_base(paths: list[Path], mode: str) -> int:
    # "auto" is a convenience for unknown inputs. Reproducible benchmark
    # bundles should pass zero/one explicitly.
    if mode not in {"auto", "zero", "one"}:
        raise ValueError("index base must be one of: auto, zero, one")
    if mode == "zero":
        return 0
    if mode == "one":
        return 1
    for path in paths:
        for source, target in iter_matrix_market_edges(path):
            if source == 0 or target == 0:
                return 0
    return 1


def scan_matrix_market(path: Path) -> MatrixInfo:
    rows = cols = 0
    declared_edges: Optional[int] = None
    header_seen = False

    with path.open(encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            parts = stripped.split()
            if not header_seen:
                if len(parts) < 3:
                    raise ValueError(f"Invalid Matrix Market size line in {path}: {stripped}")
                rows, cols, declared_edges = int(parts[0]), int(parts[1]), int(parts[2])
                header_seen = True
                continue
            if len(parts) < 2:
                raise ValueError(f"Invalid Matrix Market coordinate in {path}: {stripped}")

    if not header_seen:
        raise ValueError(f"Matrix Market file has no size line: {path}")

    return MatrixInfo(rows, cols, declared_edges, 0)


def iter_matrix_market_edges(path: Path) -> Iterator[Tuple[int, int]]:
    header_seen = False
    with path.open(encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            parts = stripped.split()
            if not header_seen:
                header_seen = True
                continue
            if len(parts) < 2:
                raise ValueError(f"Invalid Matrix Market coordinate in {path}: {stripped}")
            yield int(parts[0]), int(parts[1])


# Kept for compatibility with tests and external callers.
def read_matrix_market(path: Path) -> Tuple[int, int, Optional[int], list[Tuple[int, int]]]:
    info = scan_matrix_market(path)
    return info.rows, info.cols, info.declared_edges, list(iter_matrix_market_edges(path))


def detect_base(edges, mode: str) -> int:
    if mode not in {"auto", "zero", "one"}:
        raise ValueError("index base must be one of: auto, zero, one")
    if mode == "zero":
        return 0
    if mode == "one":
        return 1
    for source, target in edges:
        if source == 0 or target == 0:
            return 0
    return 1
