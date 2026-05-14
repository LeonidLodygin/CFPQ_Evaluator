import sys
from pathlib import Path

from cfpq_evaluator.config import Dataset, Solver
from cfpq_evaluator.engine import run_experiments


def write_mtx(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "%%MatrixMarket matrix coordinate pattern general\n" f"{body}",
        encoding="utf-8",
    )


def test_run_experiments_end_to_end_with_command_solver(tmp_path: Path):
    graph_dir = tmp_path / "graphs" / "line"
    grammar = tmp_path / "grammars" / "g.cnf"
    solver_script = tmp_path / "solver.py"
    write_mtx(graph_dir / "a.mtx", "3 3 2\n1 2\n2 3\n")
    grammar.parent.mkdir()
    grammar.write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")
    solver_script.write_text(
        "import sys\n"
        "graph = sys.argv[sys.argv.index('--graph') + 1]\n"
        "with open(graph, encoding='utf-8') as file:\n"
        "    count = sum(1 for line in file if line.strip())\n"
        "print(f'#SEdges {count}')\n"
        "print('AnalysisTime 0.25')\n",
        encoding="utf-8",
    )

    progress = []
    summary = run_experiments(
        datasets=[Dataset(name="line", graph=graph_dir, grammar=grammar)],
        solvers=[
            Solver(
                id="mock",
                label="Mock",
                type="command",
                options={
                    "argv": [sys.executable, str(solver_script), "--graph", "{graph}"],
                    "edges_regex": r"#SEdges\s+(\d+)",
                    "time_regex": r"AnalysisTime\s+([\d.]+)",
                },
            )
        ],
        out_dir=tmp_path / "results",
        rounds=2,
        timeout_sec=10,
        index_base="one",
        force=False,
        progress=progress.append,
    )

    assert "| line | Mock | ok | 2 | 0.25 s +/- 0.0% |" in summary
    assert any("preparing line" in message for message in progress)
    assert any("mock / round 1 started" in message for message in progress)
    assert any("mock / round 1 -> ok" in message for message in progress)
    assert (tmp_path / "results" / "raw_results.csv").exists()
    assert (tmp_path / "results" / "summary.md").exists()
    assert (tmp_path / "results" / "prepared_graphs" / "line" / "line.g").read_text(
        encoding="utf-8"
    ).splitlines() == ["0\t1\ta", "1\t2\ta"]
    assert (tmp_path / "results" / "logs" / "line" / "mock" / "1.stdout.txt").exists()
    assert not (tmp_path / "results" / "work").exists()


def test_run_experiments_resumes_completed_rounds(tmp_path: Path):
    graph_dir = tmp_path / "graphs" / "line"
    grammar = tmp_path / "grammars" / "g.cnf"
    solver_script = tmp_path / "solver.py"
    write_mtx(graph_dir / "a.mtx", "2 2 1\n1 2\n")
    grammar.parent.mkdir()
    grammar.write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")
    solver_script.write_text(
        "print('#SEdges 1')\n" "print('AnalysisTime 1')\n",
        encoding="utf-8",
    )
    dataset = Dataset(name="line", graph=graph_dir, grammar=grammar)
    solver = Solver(
        id="mock",
        label="Mock",
        type="command",
        options={
            "argv": [sys.executable, str(solver_script)],
            "edges_regex": r"#SEdges\s+(\d+)",
            "time_regex": r"AnalysisTime\s+([\d.]+)",
        },
    )

    run_experiments([dataset], [solver], tmp_path / "results", 1, 10, "one", force=False)
    run_experiments([dataset], [solver], tmp_path / "results", 1, 10, "one", force=False)

    raw = (tmp_path / "results" / "raw_results.csv").read_text(encoding="utf-8")
    assert raw.count("mock,Mock,line") == 1


def test_run_experiments_force_replaces_existing_raw_results(tmp_path: Path):
    graph_dir = tmp_path / "graphs" / "line"
    grammar = tmp_path / "grammars" / "g.cnf"
    solver_script = tmp_path / "solver.py"
    write_mtx(graph_dir / "a.mtx", "2 2 1\n1 2\n")
    grammar.parent.mkdir()
    grammar.write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")
    solver_script.write_text(
        "from pathlib import Path\n"
        "counter = Path(__file__).with_suffix('.count')\n"
        "value = int(counter.read_text() if counter.exists() else '0') + 1\n"
        "counter.write_text(str(value))\n"
        "print(f'#SEdges {value}')\n"
        "print('AnalysisTime 1')\n",
        encoding="utf-8",
    )
    dataset = Dataset(name="line", graph=graph_dir, grammar=grammar)
    solver = Solver(
        id="mock",
        label="Mock",
        type="command",
        options={
            "argv": [sys.executable, str(solver_script)],
            "edges_regex": r"#SEdges\s+(\d+)",
            "time_regex": r"AnalysisTime\s+([\d.]+)",
        },
    )

    run_experiments([dataset], [solver], tmp_path / "results", 1, 10, "one", force=True)
    summary = run_experiments([dataset], [solver], tmp_path / "results", 1, 10, "one", force=True)

    raw = (tmp_path / "results" / "raw_results.csv").read_text(encoding="utf-8")
    assert raw.count("mock,Mock,line") == 1
    assert "| line | Mock | ok | 2 |" in summary


def test_run_experiments_can_cleanup_prepared_graph(tmp_path: Path):
    graph_dir = tmp_path / "graphs" / "line"
    grammar = tmp_path / "grammars" / "g.cnf"
    solver_script = tmp_path / "solver.py"
    write_mtx(graph_dir / "a.mtx", "2 2 1\n1 2\n")
    grammar.parent.mkdir()
    grammar.write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")
    solver_script.write_text(
        "print('#SEdges 1')\n" "print('AnalysisTime 1')\n",
        encoding="utf-8",
    )

    run_experiments(
        datasets=[Dataset(name="line", graph=graph_dir, grammar=grammar)],
        solvers=[
            Solver(
                id="mock",
                label="Mock",
                type="command",
                options={
                    "argv": [sys.executable, str(solver_script)],
                    "edges_regex": r"#SEdges\s+(\d+)",
                    "time_regex": r"AnalysisTime\s+([\d.]+)",
                },
            )
        ],
        out_dir=tmp_path / "results",
        rounds=1,
        timeout_sec=10,
        index_base="one",
        force=False,
        cleanup_prepared=True,
    )

    assert not (tmp_path / "results" / "prepared_graphs" / "line" / "line.g").exists()
    assert not (tmp_path / "results" / "prepared_graphs" / "line").exists()
    assert (tmp_path / "results" / "raw_results.csv").exists()


def test_run_experiments_creates_work_dir_when_solver_uses_work_placeholder(tmp_path: Path):
    graph_dir = tmp_path / "graphs" / "line"
    grammar = tmp_path / "grammars" / "g.cnf"
    solver_script = tmp_path / "solver.py"
    write_mtx(graph_dir / "a.mtx", "2 2 1\n1 2\n")
    grammar.parent.mkdir()
    grammar.write_text("S\ta\n\nCount:\nS\n", encoding="utf-8")
    solver_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "work = Path(sys.argv[sys.argv.index('--work') + 1])\n"
        "print(work.exists())\n"
        "print('#SEdges 1')\n"
        "print('AnalysisTime 1')\n",
        encoding="utf-8",
    )

    run_experiments(
        datasets=[Dataset(name="line", graph=graph_dir, grammar=grammar)],
        solvers=[
            Solver(
                id="mock",
                label="Mock",
                type="command",
                options={
                    "argv": [sys.executable, str(solver_script), "--work", "{work}"],
                    "edges_regex": r"#SEdges\s+(\d+)",
                    "time_regex": r"AnalysisTime\s+([\d.]+)",
                },
            )
        ],
        out_dir=tmp_path / "results",
        rounds=1,
        timeout_sec=10,
        index_base="one",
        force=False,
    )

    assert (tmp_path / "results" / "work" / "line" / "mock" / "1").is_dir()
