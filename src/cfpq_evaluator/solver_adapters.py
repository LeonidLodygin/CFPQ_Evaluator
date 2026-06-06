from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Rule:
    lhs: str
    rhs: tuple[str, ...]


@dataclass(frozen=True)
class Grammar:
    start: str
    rules: list[Rule]

    @property
    def symbols(self) -> set[str]:
        result = {self.start}
        for rule in self.rules:
            result.add(rule.lhs)
            result.update(rule.rhs)
        return result

    @property
    def nonterminals(self) -> set[str]:
        return {rule.lhs for rule in self.rules}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    label: str
    index: Optional[int] = None


class AdapterError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cfpq-evaluator-adapter")
    subparsers = parser.add_subparsers(dest="adapter", required=True)
    for name in ("pocr", "pearl", "gigascale", "graspan", "kotgll"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--graph", required=True, type=Path)
        sub.add_argument("--grammar", required=True, type=Path)
        sub.add_argument("--timeout", type=int, default=None)
        sub.add_argument("--work", type=Path, default=Path(".adapter-work"))

    args = parser.parse_args(argv)
    try:
        result = {
            "pocr": run_pocr,
            "pearl": run_pearl,
            "gigascale": run_gigascale,
            "graspan": run_graspan,
            "kotgll": run_kotgll,
        }[args.adapter](args.graph, args.grammar, args.timeout, args.work)
    except AdapterError as exc:
        print(f"EVAL_INCOMPATIBLE {exc}")
        return 0

    print(f"EVAL_ANSWER_EDGES {result[0]}")
    print(f"EVAL_TIME_SEC {result[1]}")
    return 0


def run_pocr(graph: Path, grammar: Path, timeout: Optional[int], work: Path) -> tuple[int, float]:
    command = (
        [grammar.stem, "-pocr", str(graph)]
        if grammar.stem in {"aa", "vf"}
        else ["cfl", "-pocr", str(grammar), str(graph)]
    )
    process = run(command, timeout=timeout)
    return (
        int(parse_required(process.stdout, r"#(?:SEdges|CountEdges)\s+(\d+)")),
        float(parse_required(process.stdout, r"AnalysisTime\s+([\d.]+)")),
    )


def run_pearl(graph: Path, grammar: Path, timeout: Optional[int], work: Path) -> tuple[int, float]:
    if grammar.stem not in {"aa", "vf"}:
        raise AdapterError(f"pearl supports only aa/vf, got {grammar.stem}")
    pearl_dir = Path(os.environ.get("PEARL_DIR", "/root/eval"))
    process = run(
        [f"./{grammar.stem}", str(graph), "-pearl", "-scc=false", "-gf=false"],
        cwd=pearl_dir,
        timeout=timeout,
    )
    return (
        int(parse_required(process.stdout, r"#(?:VEdges|AEdges)\s+(\d+)")),
        float(parse_required(process.stdout, r"AnalysisTime\s+([\d.]+)")),
    )


def run_gigascale(
    graph: Path, grammar: Path, timeout: Optional[int], work: Path
) -> tuple[int, float]:
    if grammar.stem not in {"java_points_to", "java_points_to_rewritten"}:
        raise AdapterError(f"gigascale supports only java_points_to, got {grammar.stem}")
    target = work / "gigascale" / graph.stem
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "alloc": (target / "Alloc.csv").open("w", encoding="utf-8"),
        "assign": (target / "Assign.csv").open("w", encoding="utf-8"),
        "load": (target / "Load.csv").open("w", encoding="utf-8"),
        "store": (target / "Store.csv").open("w", encoding="utf-8"),
    }
    try:
        # Gigascale expects four relation CSVs with its own argument order.
        for edge in read_edges(graph):
            if edge.label == "alloc":
                files["alloc"].write(f'"var_{edge.source}","var_{edge.target}"\n')
            elif edge.label == "assign":
                files["assign"].write(f'"var_{edge.target}","var_{edge.source}"\n')
            elif edge.label == "load_i":
                files["load"].write(
                    f'"var_{edge.target}","var_{edge.source}","field_{edge.index}"\n'
                )
            elif edge.label == "store_i":
                files["store"].write(
                    f'"var_{edge.target}","var_{edge.source}","field_{edge.index}"\n'
                )
    finally:
        for file in files.values():
            file.close()

    gigascale_dir = Path(os.environ.get("GIGASCALE_DIR", "/gigascale"))
    command = ["./run.sh", "-wdlrb", "-i", str(target)]
    if shutil.which("expect"):
        script = f"set timeout -1\nspawn {' '.join(command)}\nexpect eof\n"
        process = run(["expect"], cwd=gigascale_dir, timeout=timeout, input_text=script)
    else:
        process = run(command, cwd=gigascale_dir, timeout=timeout)

    pattern = (
        r"benchmark\s+TC-time\s+TC-mem\s+v\s+e\s+vpt\s+avg\s+max\s+load/f\s+store/f\s*\n"
        r"\w+\s+(\d+\.\d+)\s+\d+(?:\.\d+)?\s+\d+\s+\d+\s+(\d+)"
    )
    match = re.search(pattern, process.stdout)
    if not match:
        raise AdapterError("could not parse gigascale output")
    return int(match.group(2)), float(match.group(1))


def run_graspan(
    graph: Path, grammar_path: Path, timeout: Optional[int], work: Path
) -> tuple[int, float]:
    grammar = read_grammar(grammar_path)
    edges = list(read_edges(graph))
    block_count = max((edge.index or 0 for edge in edges), default=0) + 1
    # Graspan has no native indexed labels, so expand load_i/store_i-style
    # rules and edges into concrete load_i_0, load_i_1, ... symbols.
    if block_count > 1:
        grammar = explode_grammar(grammar, block_count)
        edges = list(explode_edges(edges))
    if len(grammar.symbols) > 255:
        raise AdapterError("graspan supports at most 255 symbols")

    adapter_dir = work / "graspan"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    graph_out = adapter_dir / graph.name
    grammar_out = adapter_dir / grammar_path.name
    write_edges(graph_out, edges, order="source-target-label")
    write_grammar(grammar_out, grammar, include_start=False)

    mem_gb = max(1, int(total_memory_gb() * 0.9))
    threads = max(1, (os.cpu_count() or 1) * 2)
    graspan_dir = Path(os.environ.get("GRASPAN_DIR", "/graspan")) / "src"
    process = run(
        ["./run", str(graph_out), str(grammar_out), "1", str(mem_gb), str(threads)],
        cwd=graspan_dir,
        timeout=timeout,
    )
    final_file = Path(parse_required(process.stdout, r"finalFile:\s*(.*)"))
    try:
        answer = count_start_edges(final_file, grammar.start)
    finally:
        final_file.unlink(missing_ok=True)
    return answer, float(parse_required(process.stdout, r"COMP TIME:\s*([\d.]+|NaN)"))


def run_kotgll(
    graph: Path, grammar_path: Path, timeout: Optional[int], work: Path
) -> tuple[int, float]:
    # KOTGLL uses its own grammar dialect; keep those files next to the .cnf
    # grammar under grammar/kotgll/<name>.cfg or .rsm.
    base = grammar_path.parent / "kotgll"
    source_grammar = base / f"{grammar_path.stem}.rsm"
    if not source_grammar.exists():
        source_grammar = base / f"{grammar_path.stem}.cfg"
    if not source_grammar.exists():
        raise AdapterError(f"missing kotgll grammar for {grammar_path.stem}")

    edges = list(read_edges(graph))
    has_indexed_edges = any(edge.index is not None for edge in edges)
    block_count = max((edge.index or 0 for edge in edges), default=0) + 1
    adapter_dir = work / "kotgll" / str(uuid.uuid4())
    adapter_dir.mkdir(parents=True, exist_ok=True)
    graph_dir = adapter_dir / "input"
    graph_dir.mkdir()
    graph_out = graph_dir / graph.name
    # KOTGLL runner expects whitespace-separated graph rows and concrete
    # indexed labels, not the four-column "label index" representation.
    write_edges(graph_out, explode_edges(edges), order="source-target-label", separator=" ")

    grammar_out = adapter_dir / source_grammar.name
    if has_indexed_edges and grammar_has_index_template(source_grammar):
        expand_kotgll_grammar(source_grammar, grammar_out, block_count)
    else:
        shutil.copyfile(source_grammar, grammar_out)

    out_dir = adapter_dir / "out"
    out_dir.mkdir()
    max_mem = max(1, int(total_memory_gb() * 0.9))
    kotgll_dir = Path(os.environ.get("KOTGLL_DIR", "/kotgll"))
    process = run(
        [
            "java",
            f"-Xmx{max_mem}G",
            "-cp",
            "kotgll.jar",
            "org.kotgll.benchmarks.BenchmarksKt",
            "--grammar",
            grammar_out.suffix[1:],
            "--sppf",
            "off",
            "--inputPath",
            str(graph_dir),
            "--grammarPath",
            str(grammar_out),
            "--outputPath",
            str(out_dir),
            "--warmUpRounds",
            "1",
            "--benchmarkRounds",
            "1",
        ],
        cwd=kotgll_dir,
        timeout=timeout * 2 if timeout else None,
    )
    for line in process.stdout.splitlines():
        if line.startswith("benchmark::"):
            parts = line.split()
            return int(parts[-2]), float(parts[-1])
    raise AdapterError("could not parse kotgll output")


def run(
    command: list[str],
    cwd: Optional[Path] = None,
    timeout: Optional[int] = None,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise AdapterError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process


def read_grammar(path: Path) -> Grammar:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 2 or lines[-2] != "Count:":
        raise AdapterError(f"grammar {path} has no Count start marker")
    start = lines[-1]
    rules = []
    for line in lines[:-2]:
        parts = tuple(line.split())
        rules.append(Rule(parts[0], parts[1:]))
    return Grammar(start=start, rules=rules)


def write_grammar(path: Path, grammar: Grammar, include_start: bool) -> None:
    with path.open("w", encoding="utf-8") as file:
        for rule in grammar.rules:
            file.write("\t".join((rule.lhs, *rule.rhs)).rstrip() + "\n")
        if include_start:
            file.write("\nCount:\n")
            file.write(grammar.start)


def read_edges(path: Path) -> Iterable[Edge]:
    with path.open(encoding="utf-8") as file:
        for line in file:
            parts = line.split()
            if not parts:
                continue
            index = int(parts[3]) if len(parts) > 3 else None
            yield Edge(parts[0], parts[1], parts[2], index)


def write_edges(
    path: Path,
    edges: Iterable[Edge],
    order: str,
    separator: str = "\t",
) -> None:
    with path.open("w", encoding="utf-8") as file:
        for edge in edges:
            if order == "source-target-label":
                file.write(separator.join((edge.source, edge.target, edge.label)) + "\n")
            else:
                file.write(separator.join((edge.source, edge.label, edge.target)) + "\n")


def explode_edges(edges: Iterable[Edge]) -> Iterable[Edge]:
    for edge in edges:
        label = f"{edge.label}_{edge.index}" if edge.index is not None else edge.label
        yield Edge(edge.source, edge.target, label)


def explode_grammar(grammar: Grammar, block_count: int) -> Grammar:
    # Replace symbolic indexed rules with one concrete rule per observed block.
    rules = []
    for rule in grammar.rules:
        if any(is_indexed(symbol) for symbol in (rule.lhs, *rule.rhs)):
            for index in range(block_count):
                rules.append(
                    Rule(
                        index_symbol(rule.lhs, index),
                        tuple(index_symbol(s, index) for s in rule.rhs),
                    )
                )
        else:
            rules.append(rule)
    return Grammar(start=grammar.start, rules=rules)


def grammar_has_index_template(path: Path) -> bool:
    return "{i}" in path.read_text(encoding="utf-8")


def expand_kotgll_grammar(source: Path, target: Path, block_count: int) -> None:
    # KOTGLL templates use {i}; expand only when the graph actually has
    # indexed edge families.
    with source.open(encoding="utf-8") as src, target.open("w", encoding="utf-8") as dst:
        for line in src:
            if "{i}" in line:
                for i in range(block_count):
                    dst.write(line.replace("{i}", str(i)))
            else:
                dst.write(line)


def is_indexed(symbol: str) -> bool:
    return symbol.endswith("_i")


def index_symbol(symbol: str, index: int) -> str:
    return f"{symbol}_{index}" if is_indexed(symbol) else symbol


def count_start_edges(path: Path, start: str) -> int:
    pairs = set()
    with path.open(encoding="utf-8") as file:
        for line in file:
            parts = line.split()
            if len(parts) >= 3 and parts[-1] == start:
                pairs.add((parts[0], parts[1]))
    return len(pairs)


def parse_required(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise AdapterError(f"could not parse pattern {pattern!r}")
    return match.group(1)


def total_memory_gb() -> float:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / (1024**3)
    except (OSError, ValueError):
        return 4.0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
