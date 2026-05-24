from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .config import Solver


@dataclass(frozen=True)
class RunResult:
    answer_edges: str
    time_sec: str
    ram_kb: str
    stdout: str
    stderr: str


class SolverError(Exception):
    status = "failed"

    def __init__(
        self,
        message: str,
        *,
        command: Optional[List[str]] = None,
        returncode: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
    ):
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def summary(self) -> str:
        if self.returncode is None:
            return str(self)
        return f"{self}; returncode={self.returncode}"


class TimeoutSolverError(SolverError):
    status = "timeout"


class IncompatibleSolverError(SolverError):
    status = "incompatible"


class OutOfMemorySolverError(SolverError):
    status = "oom"


def run_solver(
    solver: Solver,
    graph_path: Path,
    graph_dir: Path,
    grammar_path: Path,
    timeout_sec: Optional[int],
    work_dir: Path,
) -> RunResult:
    if solver.type == "command":
        return CommandRunner(solver).run(graph_path, graph_dir, grammar_path, timeout_sec, work_dir)
    raise ValueError(f"Unknown solver type: {solver.type}")


class ProcessRunner:
    def run_process(
        self,
        command: List[str],
        cwd: Optional[Path],
        timeout_sec: Optional[int],
        env: Optional[Dict[str, str]] = None,
    ) -> RunResult:
        time_file: Optional[Path] = None
        measured_command = command
        # Wrap external solvers with /usr/bin/time when available to collect
        # peak RSS without forcing every adapter to implement memory tracking.
        if shutil.which("/usr/bin/time") or Path("/usr/bin/time").exists():
            time_file = Path(cwd or Path.cwd()) / ".cfpq_eval_time.txt"
            measured_command = [
                "/usr/bin/time",
                "-f",
                "EVAL_PEAK_RSS_KB=%M",
                "-o",
                str(time_file),
                *command,
            ]

        started = time.monotonic()
        try:
            process = subprocess.run(
                measured_command,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            elapsed = time.monotonic() - started

            # Docker/Linux OOM kills and JVM/native allocation failures surface in
            # different ways, so classify them before generic non-zero failures.
            if is_oom(process.returncode, process.stdout, process.stderr):
                raise OutOfMemorySolverError(
                    "Solver was killed by OOM or memory allocation failure",
                    command=command,
                    returncode=process.returncode,
                    stdout=process.stdout,
                    stderr=process.stderr,
                )

            if process.returncode != 0:
                raise SolverError(
                    "Solver exited with non-zero code",
                    command=command,
                    returncode=process.returncode,
                    stdout=process.stdout,
                    stderr=process.stderr,
                )

            return RunResult(
                answer_edges="",
                time_sec=f"{elapsed:.6f}",
                ram_kb=read_peak_rss(time_file),
                stdout=process.stdout,
                stderr=process.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutSolverError(
                f"Solver timed out after {timeout_sec} seconds",
                command=command,
            ) from exc
        finally:
            if time_file:
                time_file.unlink(missing_ok=True)


class CommandRunner(ProcessRunner):
    def __init__(self, solver: Solver):
        self.solver = solver

    def run(
        self,
        graph_path: Path,
        graph_dir: Path,
        grammar_path: Path,
        timeout_sec: Optional[int],
        work_dir: Path,
    ) -> RunResult:
        if self.solver.options.get("only_grammars"):
            allowed = set(self.solver.options["only_grammars"])
            if grammar_path.stem not in allowed:
                raise IncompatibleSolverError(
                    f"{self.solver.id} does not support grammar {grammar_path.stem}",
                )

        # Placeholders keep solver configs declarative while still allowing
        # adapters to request the prepared .g file, original mtx directory, etc.
        values = {
            "graph": str(graph_path),
            "graph_dir": str(graph_dir),
            "graph_mtx_dir": str(graph_dir),
            "grammar": str(grammar_path),
            "grammar_rewritten": str(rewritten_grammar_path(grammar_path)),
            "grammar_stem": grammar_path.stem,
            "work": str(work_dir),
            "timeout": "" if timeout_sec is None else str(timeout_sec),
        }
        if "argv" in self.solver.options:
            command = [str(part).format(**values) for part in self.solver.options["argv"]]
        else:
            template = str(self.solver.options["command"])
            command = shlex.split(template.format(**values), posix=(os.name != "nt"))
        cwd = Path(self.solver.options["cwd"]).resolve() if self.solver.options.get("cwd") else None
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in self.solver.options.get("env", {}).items()})

        raw = self.run_process(command, cwd=cwd, timeout_sec=timeout_sec, env=env)
        stdout = raw.stdout
        incompatible = re.search(r"^EVAL_INCOMPATIBLE\s+(.+)$", stdout, re.MULTILINE)
        if incompatible:
            raise IncompatibleSolverError(
                incompatible.group(1),
                command=command,
                stdout=raw.stdout,
                stderr=raw.stderr,
            )
        return RunResult(
            answer_edges=parse_required(stdout, str(self.solver.options["edges_regex"])),
            time_sec=parse_required(stdout, str(self.solver.options["time_regex"])),
            ram_kb=raw.ram_kb,
            stdout=raw.stdout,
            stderr=raw.stderr,
        )


def read_peak_rss(time_file: Optional[Path]) -> str:
    if not time_file or not time_file.exists():
        return ""
    match = re.search(r"EVAL_PEAK_RSS_KB=(\d+)", time_file.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def rewritten_grammar_path(grammar_path: Path) -> Path:
    # Backward-compatible optional grammar variant. If the file is absent,
    # {grammar_rewritten} behaves exactly like {grammar}.
    candidate = grammar_path.with_name(f"{grammar_path.stem}_rewritten{grammar_path.suffix}")
    return candidate if candidate.exists() else grammar_path


def parse_required(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise IncompatibleSolverError(
            f"Could not parse pattern {pattern!r} from solver output",
        )
    return match.group(1)


def is_oom(returncode: int, stdout: str, stderr: str) -> bool:
    if returncode in {137, -9}:
        return True
    text = f"{stdout}\n{stderr}".lower()
    return any(
        marker in text
        for marker in (
            "outofmemoryerror",
            "out of memory",
            "cannot allocate memory",
            "\nkilled\n",
            "killed process",
        )
    )
