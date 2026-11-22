"""Fix proposer for order dependence (BE-7), and its validation under shuffled runs.

The only fix FlakeGuard proposes is an autouse fixture in ``tests/conftest.py`` that puts a shared
module-level ``dict``, ``list`` or ``set`` back to the value it had before each test. It is
validated on a copy of the repository before anything is shown as ready or opened as a pull
request: the suite is run in ``runs`` shuffled orders without and with the fixture, and the
polluter-then-victim repro is run both ways.

Nothing here talks to GitHub. See ``forge.py`` for that.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from flakeguard.console.analysis import StateDef
from flakeguard.runner.matrix import parse_junit_xml, to_node_id

CONFTEST = "tests/conftest.py"
DEFAULT_RUNS = 20
_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc", "node_modules", ".venv")

_COPY = {"dict": "dict({n})", "list": "list({n})", "set": "set({n})"}
_RESTORE = {
    "dict": ["{n}.clear()", "{n}.update(before)"],
    "list": ["{n}[:] = before"],
    "set": ["{n}.clear()", "{n}.update(before)"],
}


@dataclass(frozen=True)
class FixPlan:
    file: str  # repo-relative, always tests/conftest.py
    kind: str  # dict, list or set
    module: str  # importable name of the module that holds the state
    state: str
    appended: str  # text added to the end of the file
    added_lines: list[str]  # the same text, line by line (what the diff shows)
    existed: bool  # the file was already there, so the text is appended


@dataclass
class Validation:
    seeds: list[int]
    victim: str
    victim_failed_after: int = 0
    pair_before_exit: int | None = None
    pair_after_exit: int | None = None
    failing_after: dict[str, int] = field(default_factory=dict)  # test id -> shuffled runs it failed in, with the fix
    new_failures: dict[str, int] = field(default_factory=dict)  # of those, tests that had never failed in the scan
    errors: list[str] = field(default_factory=list)  # runs that produced no result at all

    @property
    def passed(self) -> bool:
        return (
            not self.errors and self.victim_failed_after == 0 and not self.new_failures
            and self.pair_after_exit == 0 and self.pair_before_exit not in (None, 0)
        )

    def reason(self) -> str:
        if self.errors:
            return "; ".join(self.errors)
        bits = []
        if self.victim_failed_after:
            bits.append(f"{self.victim} still failed in {self.victim_failed_after} of {len(self.seeds)} shuffled runs")
        if self.new_failures:
            bits.append("tests that had never failed now failed: " + ", ".join(sorted(self.new_failures)))
        if self.pair_after_exit != 0:
            bits.append("the two-test repro still failed with the fix")
        if self.pair_before_exit in (None, 0):
            bits.append("the two-test repro did not fail without the fix, so it proves nothing")
        return "; ".join(bits)


def module_name(state_file: str) -> str:
    """``src/inventory/cache.py`` -> ``inventory.cache`` (the ``src`` layout is the common case)."""
    parts = state_file[:-3].split("/") if state_file.endswith(".py") else state_file.split("/")
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def state_kind(repo: Path, state: StateDef) -> str | None:
    """dict, list or set when the module-level assignment is visibly one of those, else None."""
    path = repo / state.file
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target, value = node.target.id, node.value
        if target != state.name:
            continue
        if isinstance(value, (ast.Dict, ast.DictComp)):
            return "dict"
        if isinstance(value, (ast.List, ast.ListComp)):
            return "list"
        if isinstance(value, (ast.Set, ast.SetComp)):
            return "set"
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in _COPY:
            return value.func.id
    return None


def plan_fix(repo: Path, state: StateDef) -> FixPlan | None:
    """The fixture text for one shared state, or None when the state is not a plain dict, list or set."""
    kind = state_kind(repo, state)
    if kind is None:
        return None
    module = module_name(state.file)
    alias = f"_flakeguard_{state.name.lower()}"
    ref = f"{alias}.{state.name}"
    lines = [
        "import pytest",
        f"import {module} as {alias}",
        "",
        "",
        "@pytest.fixture(autouse=True)",
        f"def _flakeguard_restore_{state.name.lower()}():",
        f"    before = {_COPY[kind].format(n=ref)}",
        "    yield",
        *(f"    {step.format(n=ref)}" for step in _RESTORE[kind]),
    ]
    existed = (repo / CONFTEST).is_file()
    appended = ("\n\n" if existed else "") + "\n".join(lines) + "\n"
    return FixPlan(CONFTEST, kind, module, state.name, appended, lines, existed)


def apply_fix(repo: Path, plan: FixPlan) -> None:
    path = repo / plan.file
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    if old and not old.endswith("\n"):
        old += "\n"
    path.write_text(old + plan.appended, encoding="utf-8")


def _env(repo: Path) -> dict[str, str]:
    paths = [str(repo)]
    if (repo / "src").is_dir():
        paths.insert(0, str(repo / "src"))
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths), "PYTHONDONTWRITEBYTECODE": "1"}


def _pytest(repo: Path, args: list[str], junit: Path, timeout: float) -> tuple[int, dict[str, str]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, f"--junitxml={junit}"],
        cwd=repo, env=_env(repo), capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, {to_node_id(repo, o.test_id): o.outcome for o in parse_junit_xml(junit)}


def validate_fix(
    repo: Path, plan: FixPlan, *, polluter: str, victim: str, known_failing: set[str],
    test_dir: str = "tests", runs: int = DEFAULT_RUNS, seed_start: int = 1, timeout: float = 120.0,
    workers: int = 4, log: list[str] | None = None,
) -> Validation:
    """Run the suite in ``runs`` shuffled orders on copies of ``repo`` with the fix applied, and the
    polluter-then-victim repro on a copy without it and on a copy with it.

    ``polluter`` and ``victim`` are pytest node ids; ``known_failing`` are the tests that failed in
    the scan. A failure of a test outside that set after the fix counts against the fix. What the
    victim did without the fix comes from the scan itself, not from this function.
    """
    seeds = list(range(seed_start, seed_start + runs))
    result = Validation(seeds=seeds, victim=victim)
    note = log.append if log is not None else (lambda line: None)
    lock = threading.Lock()
    with tempfile.TemporaryDirectory(prefix="flakeguard-fix-") as tmp:
        base = Path(tmp)
        before = base / "before"
        shutil.copytree(repo, before, ignore=_IGNORE)
        copies = []
        for i in range(max(1, min(workers, runs))):
            copy = base / f"after-{i}"
            shutil.copytree(repo, copy, ignore=_IGNORE)
            apply_fix(copy, plan)
            copies.append(copy)

        def shuffled(index: int, seed: int) -> None:
            copy = copies[index % len(copies)]
            junit = base / f"shuffled-{seed}.xml"
            try:
                code, outcomes = _pytest(copy, ["-p", "randomly", f"--randomly-seed={seed}", test_dir], junit, timeout)
            except subprocess.TimeoutExpired:
                with lock:
                    result.errors.append(f"seed {seed} timed out")
                return
            with lock:
                if not outcomes:
                    result.errors.append(f"seed {seed} produced no result (exit code {code})")
                    return
                failed = sorted(t for t, o in outcomes.items() if o in ("FAIL", "ERROR"))
                note(f"with the fix, seed {seed}: exit {code}, {len(outcomes)} tests, failed: {', '.join(failed) or 'none'}")
                result.victim_failed_after += victim in failed
                for t in failed:
                    result.failing_after[t] = result.failing_after.get(t, 0) + 1
                    if t not in known_failing:
                        result.new_failures[t] = result.new_failures.get(t, 0) + 1

        # One worker per copy: runs that share a copy never overlap.
        def lane(k: int) -> None:
            for i in range(k, len(seeds), len(copies)):
                shuffled(i, seeds[i])

        threads = [threading.Thread(target=lane, args=(k,)) for k in range(len(copies))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for label, copy in (("pair without the fix", before), ("pair with the fix", copies[0])):
            junit = base / f"{copy.name}-pair.xml"
            try:
                code, outcomes = _pytest(copy, [polluter, victim, "-p", "no:randomly"], junit, timeout)
            except subprocess.TimeoutExpired:
                result.errors.append(f"{label} timed out")
                continue
            if not outcomes:
                result.errors.append(f"{label} produced no result (exit code {code})")
                continue
            note(f"{label} ({polluter} then {victim}): exit {code}")
            if copy is before:
                result.pair_before_exit = code
            else:
                result.pair_after_exit = code
    return result
