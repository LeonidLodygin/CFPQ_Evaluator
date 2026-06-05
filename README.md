# CFPQ Evaluator

[![CI](https://github.com/LeonidLodygin/CFPQ_Evaluator/actions/workflows/ci.yml/badge.svg)](https://github.com/LeonidLodygin/CFPQ_Evaluator/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Code style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![Lint: Ruff](https://img.shields.io/badge/lint-ruff-purple)
![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)
![License](https://img.shields.io/github/license/LeonidLodygin/CFPQ_Evaluator)

`CFPQ Evaluator` is an experiment runner for CFPQ solvers. Datasets and solvers are described in config files, every
solver is run several times, raw results are saved, and a compact summary is
generated.

A graph is a directory of
Matrix Market files, one file per edge label:

```text
dataset-name/
  graph/
    a.mtx
    b.mtx
    load_i_3.mtx
  grammar/
    query.cnf
```

Each `.mtx` file is a matrix:

```text
%%MatrixMarket matrix coordinate pattern general
%%GraphBLAS type bool
26188 26188 1022
114 115
135 136
```

Before a solver is launched, the evaluator materializes this directory into
a temporary `.g` file. Solvers can use either the original Matrix
Market directory or the generated `.g` file through placeholders. The
evaluator does not import or special-case any solver code.

## Install Locally

From the project root:

```bash
python3 -m pip install -e .
cfpq-eval --help
```

## Quick Start

The repository includes a tiny self-contained example that does not require any third-party solver. It uses a mock solver script from
`examples/mock_solver.py`.

```bash
python3 -m pip install -e ".[dev]"

cfpq-eval plan \
  --datasets examples/tiny/datasets_bundle.csv \
  --solvers examples/tiny/solvers.toml

cfpq-eval run \
  --datasets examples/tiny/datasets_bundle.csv \
  --solvers examples/tiny/solvers.toml \
  --out results_tiny \
  --rounds 2 \
  --timeout 10 \
  --mtx-base one
```

Expected output is a small summary table with one dataset, `line-a`, and one
solver, `Mock solver`. Results are written to:

```text
results_tiny/
  raw_results.csv
  summary.md
  prepared_graphs/
  logs/
```

If you do not want to install the package yet, run from the project root with
`PYTHONPATH=src`:

```bash
PYTHONPATH=src python3 -m cfpq_evaluator.cli run \
  --datasets examples/tiny/datasets_bundle.csv \
  --solvers examples/tiny/solvers.toml \
  --out results_tiny \
  --rounds 1 \
  --mtx-base one
```

## Examples Directory

```text
examples/
  mock_solver.py              # tiny fake solver used for smoke tests
  tiny/
    datasets_bundle.csv       # self-contained dataset folder mode
    solvers.toml              # mock solver config
    dataset/
      graph/a.mtx
      grammar/a_star.cnf
```

Start with `examples/tiny/*` when checking that the evaluator itself works.

## Dataset Config

Datasets are CSV files with three columns:

```csv
name,graph,grammar
xz-aa,/data/graphs_mtx/aa/xz,/data/grammars/aa.cnf
eclipse-java,/data/graphs_mtx/java/eclipse,/data/grammars/java_points_to.cnf
```

`graph` points to a directory containing `.mtx` files. `grammar` points to the CNF-like grammar format file.

Self-contained dataset directories are also supported. In this mode the CSV
points to a folder that contains `graph/` and `grammar/`:

```text
datasets/
  aa-xz/
    graph/
      a.mtx
      abar.mtx
    grammar/
      aa.cnf
```

```csv
name,dataset
aa-xz,/data/datasets/aa-xz
```

If `grammar/` contains more than one `.cnf` file, add `grammar_file`:

```csv
name,dataset,grammar_file
aa-xz,/data/datasets/aa-xz,aa.cnf
```

## Solver Config

Solvers are represented as TOML files. Every solver is configured as an external command:

```toml
[[solver]]
id = "custom"
label = "My CFPQ solver"
type = "command"
argv = ["my-cfpq-tool", "--graph", "{graph}", "--grammar", "{grammar}"]
edges_regex = "AnswerEdges\\s+(\\d+)"
time_regex = "AnalysisTime\\s+([\\d.]+)"
```

Available placeholders: `{graph}`, `{graph_dir}`, `{graph_mtx_dir}`,
`{grammar}`, `{grammar_rewritten}`, `{grammar_stem}`, `{work}`, `{timeout}`. Prefer `argv`
over a single `command` string when paths may contain spaces. A shell-like
`command = "..."` string is also supported for simple cases.

# Adding Your Own Solver

`CFPQ_Evaluator` runs solvers as external commands.

The evaluator itself does not require a solver-specific Python API. It starts the command from `argv`, captures its output, and extracts the answer size and time using regular expressions.

### 1. Choose How the Solver Is Started

First write the command that starts your solver manually.

Examples:

```bash
/path/to/my-solver --graph graph.g --grammar grammar.cnf
```

```bash
python3 -m my_solver.run --graph graph.g --grammar grammar.cnf
```

If the solver needs input conversion or special handling, wrap it in an adapter and run the adapter instead.

### 2. Add the Solver to TOML

Create or update `solvers.toml`:

```toml
[[solver]]
id = "my-solver"
label = "My Solver"
type = "command"
argv = [
  "python3",
  "-m",
  "my_solver.run",
  "--graph",
  "{graph}",
  "--grammar",
  "{grammar}"
]
edges_regex = "ANSWER\\s+(\\d+)"
time_regex = "TIME\\s+([\\d.]+)"
```

`argv` is the command split into separate arguments. The first item is the executable command, and the following items are its arguments.

For example, this shell command:

```bash
python3 -m my_solver.run --graph graph.g --grammar grammar.cnf --timeout 60
```

is written as:

```toml
argv = [
  "python3",
  "-m",
  "my_solver.run",
  "--graph",
  "{graph}",
  "--grammar",
  "{grammar}",
  "--timeout",
  "{timeout}"
]
```

Do not put the whole command into one string.

Correct:

```toml
argv = ["python3", "-m", "my_solver.run", "--graph", "{graph}"]
```

Incorrect:

```toml
argv = ["python3 -m my_solver.run --graph {graph}"]
```

### 3. Useful Placeholders

The evaluator substitutes placeholders before running the command.

| Placeholder | Meaning |
| --- | --- |
| `{graph}` | Prepared graph path passed to the solver |
| `{graph_dir}` | Prepared graph directory |
| `{graph_mtx_dir}` | Directory with Matrix Market files |
| `{grammar}` | Grammar file |
| `{grammar_rewritten}` | Rewritten grammar file, if available |
| `{work}` | Per-run temporary directory |
| `{timeout}` | Timeout in seconds |

Most solvers only need `{graph}`, `{grammar}`, and `{timeout}`.

### 4. Parse Solver Output

`edges_regex` extracts the number of answer pairs. `time_regex` extracts solver time.

For this output:

```text
ANSWER 12345
TIME 0.578
```

use:

```toml
edges_regex = "ANSWER\\s+(\\d+)"
time_regex = "TIME\\s+([\\d.]+)"
```

If your solver prints another format, change the regexes accordingly.

For example:

```text
Result pairs: 12345
Elapsed: 0.578 sec
```

can be parsed with:

```toml
edges_regex = "Result pairs:\\s+(\\d+)"
time_regex = "Elapsed:\\s+([\\d.]+)\\s+sec"
```


## Run Real Experiments

Preview a run:

```bash
cfpq-eval plan --datasets /path/to/datasets.csv --solvers /path/to/solvers.toml
```

Run experiments:

```bash
cfpq-eval run \
  --datasets /path/to/datasets.csv \
  --solvers /path/to/solvers.toml \
  --out results \
  --rounds 3 \
  --timeout 600 \
  --mtx-base auto
```

Outputs:

```text
results/
  raw_results.csv
  summary.md
  prepared_graphs/
  logs/
  work/
```

`raw_results.csv` is append-only by default, so interrupted experiments can be
resumed by running the same command again. Use `--force` to replace old raw
results and start a fresh run from round 1.

For large graphs, add `--cleanup-prepared` to delete each generated `.g` file
after that dataset has been processed by all solvers:

```bash
cfpq-eval run \
  --datasets /path/to/datasets.csv \
  --solvers /path/to/solvers.toml \
  --out results \
  --cleanup-prepared
```

## Docker

The included Dockerfile builds a minimal standalone evaluator image from
`python:3.11-slim`. It installs only `cfpq-eval`; external CFPQ solvers are still
mounted or installed separately, just like any other command-line tool.

Build:

```bash
docker build -t cfpq-evaluator .
```

Run with your own Matrix Market data and grammars mounted into the container:

```bash
docker run --rm \
  -v /absolute/path/to/configs:/configs \
  -v /absolute/path/to/datasets:/datasets \
  -v /absolute/path/to/results:/results \
  cfpq-evaluator run \
    --datasets /configs/datasets.csv \
    --solvers /configs/solvers.toml \
    --out /results \
    --rounds 3 \
    --timeout 600
```

The image contains only the evaluator. Put solver commands in your mounted
`solvers.toml` and make sure those commands are available in the container.

