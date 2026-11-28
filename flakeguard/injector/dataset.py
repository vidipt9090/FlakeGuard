"""Build the injected dataset: a published, passing test suite (cachetools) with known faults inserted by operators.

Deterministic: the same cachetools release (checked by sha256) and the same seed give the same mutated suite and the
same labels. Nothing here looks at how any detection method scores.

Labels: a test that no operator touched is ``stable`` by observation (the pristine suite passed in every one of the
pristine runs recorded in the manifest); that is evidence, not a proof. A test an operator touched gets that operator's
label and root cause.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

from flakeguard.injector.operators import (
    MutationOperator,
    OrderDependenceOperator,
    RandomnessOperator,
    RealFailureOperator,
    SharedStateOperator,
    SleepRaceOperator,
    TimeTZOperator,
)

PACKAGE = "cachetools"
VERSION = "8.0.2"
SDIST_SHA256 = "30ac523adfc118b51d2b2e7bad8a0ddb31370dfe2700c7f10ca224f36ccf81e0"
DEFAULT_SEED = 20261122
EXCLUDED_FILES = {"test_threading.py"}  # threaded tests of the library itself; not touched, so they stay as they are
COUNTS = {"order_dep": 5, "timing": 5, "randomness": 5, "time_tz": 5, "real_fail": 5}
SHARED_STATE_MODULES = 2
SHARED_STATE_PER_MODULE = 3
PRISTINE_RUNS = 3  # fixed-order runs, and the same number of shuffled ones

OPERATORS: dict[str, MutationOperator] = {
    "order_dep": OrderDependenceOperator(), "timing": SleepRaceOperator(), "randomness": RandomnessOperator(),
    "time_tz": TimeTZOperator(), "real_fail": RealFailureOperator(), "shared_state": SharedStateOperator(),
}


@dataclass(frozen=True)
class Target:
    file: str  # relative, forward slashes: tests/test_fifo.py
    cls: str | None
    name: str

    @property
    def id(self) -> str:
        return f"{self.file}::{self.cls}::{self.name}" if self.cls else f"{self.file}::{self.name}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(cache: Path) -> Path:
    """Download the pinned release's source archive (if not cached), check its hash and unpack it."""
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{PACKAGE}-{VERSION}.tar.gz"
    if not archive.is_file():
        subprocess.run([sys.executable, "-m", "pip", "download", f"{PACKAGE}=={VERSION}", "--no-deps", "--no-binary", ":all:",
                        "-d", str(cache)], check=True, capture_output=True, text=True)
    if sha256(archive) != SDIST_SHA256:
        raise RuntimeError(f"{archive.name} has sha256 {sha256(archive)}, expected {SDIST_SHA256}; refusing to build from it")
    root = cache / f"{PACKAGE}-{VERSION}"
    if not root.is_dir():
        with tarfile.open(archive) as tar:
            tar.extractall(cache, filter="data")
    return root


def _pytest(root: Path, *args: str) -> subprocess.CompletedProcess:
    root = root.resolve()
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    # --rootdir and -c keep pytest from taking this repository's configuration when the suite is stored inside it.
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(root),
                           "-c", str(root / "pyproject.toml"), *args], cwd=root, env=env,
                          capture_output=True, text=True)


def collect_ids(root: Path) -> list[str]:
    """Test ids in the order pytest runs them when nothing shuffles."""
    proc = _pytest(root, "--collect-only", "-p", "no:randomly", "tests")
    if proc.returncode != 0:
        raise RuntimeError(f"collection failed:\n{proc.stdout[-1500:]}\n{proc.stderr[-500:]}")
    return [line.strip() for line in proc.stdout.splitlines() if "::" in line and line.startswith("tests/")]


def own_tests(root: Path, ids: list[str]) -> list[Target]:
    """Tests that are defined in their own file (a method defined in a class of a unittest.TestCase subclass, or a function).

    A method that is only inherited from a mixin is left alone: changing it would change several tests at once.
    """
    defined: set[tuple[str, str | None, str]] = set()
    for path in sorted((root / "tests").glob("test_*.py")):
        rel = f"tests/{path.name}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                defined.add((rel, None, node.name))
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test"):
                        defined.add((rel, node.name, item.name))
    out = []
    for tid in ids:
        parts = tid.split("::")
        key = (parts[0], parts[1] if len(parts) == 3 else None, parts[-1])
        if key in defined and Path(parts[0]).name not in EXCLUDED_FILES:
            out.append(Target(*key))
    return out


def choose(candidates: list[Target], seed: int) -> dict:
    """Pick the tests to mutate. Uses only the collection order and the seed."""
    rng = random.Random(seed)
    used: set[Target] = set()
    position = {t: i for i, t in enumerate(candidates)}

    def free(file: str | None = None) -> list[Target]:
        return [t for t in candidates if t not in used and (file is None or t.file == file)]

    pairs = []
    for _ in range(COUNTS["order_dep"]):
        victims = [t for t in free() if any(position[s] < position[t] for s in free(t.file) if s != t)]
        victim = rng.choice(victims)
        setup = rng.choice([s for s in free(victim.file) if position[s] < position[victim]])
        used.update({victim, setup})
        pairs.append((setup, victim))
    shared: list[list[Target]] = []
    files = sorted({t.file for t in candidates if len(free(t.file)) >= SHARED_STATE_PER_MODULE})
    for file in rng.sample(files, SHARED_STATE_MODULES):
        group = rng.sample(free(file), SHARED_STATE_PER_MODULE)
        used.update(group)
        shared.append(sorted(group, key=position.get))
    singles: dict[str, list[Target]] = {}
    for category in ("timing", "randomness", "time_tz", "real_fail"):
        singles[category] = rng.sample(free(), COUNTS[category])
        used.update(singles[category])
    return {"order_dep": pairs, "shared_state": shared, **singles}


def _apply(source: str, op: MutationOperator, target: Target) -> str:
    mutation = op.apply(source, target.name, target.cls)
    if mutation is None:
        raise RuntimeError(f"{type(op).__name__} cannot be applied to {target.id}")
    return mutation.mutated_code


def pristine_check(root: Path) -> list[dict]:
    """Run the untouched suite several times, fixed order and shuffled, and record what it did."""
    results = []
    for shuffled in (False, True):
        for i in range(1, PRISTINE_RUNS + 1):
            flags = ["-p", "randomly", f"--randomly-seed={i}"] if shuffled else ["-p", "no:randomly"]
            proc = _pytest(root, *flags, "tests")
            tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            passed = re.search(r"(\d+) passed", tail)
            failed = re.search(r"(\d+) failed", tail)
            results.append({"order": f"shuffled seed {i}" if shuffled else "fixed", "passed": int(passed.group(1)) if passed else 0,
                            "failed": int(failed.group(1)) if failed else 0, "summary": tail})
    return results


def build(cache: Path, out: Path, seed: int = DEFAULT_SEED) -> dict:
    """Write the mutated suite to ``out`` and ``out/../labels.json`` style files next to it; returns the manifest."""
    root = fetch(cache)
    ids = collect_ids(root)
    pristine = pristine_check(root)
    if any(r["failed"] or not r["passed"] for r in pristine):
        raise RuntimeError(f"the untouched suite does not pass cleanly, so 'stable' would not mean anything: {pristine}")
    picks = choose(own_tests(root, ids), seed)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root, out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    label_of: dict[str, dict] = {tid: {"label": "stable", "root_cause": "none"} for tid in ids}
    injections: list[dict] = []
    sources: dict[str, str] = {}

    def source(file: str) -> str:
        return sources.setdefault(file, (out / file).read_text(encoding="utf-8"))

    def record(target: Target, category: str, label: str, root_cause: str, **extra) -> None:
        label_of[target.id] = {"label": label, "root_cause": root_cause}
        injections.append({"id": target.id, "operator": type(OPERATORS[category]).__name__, "category": category,
                           "label": label, "root_cause": root_cause, **extra})

    for setup, victim in picks["order_dep"]:
        op = OPERATORS["order_dep"]
        sources[victim.file] = _apply(source(victim.file), op, victim)
        mutated = op.apply_setup(source(setup.file), setup.name, setup.cls)  # type: ignore[attr-defined]
        if mutated is None:
            raise RuntimeError(f"cannot mutate setup test {setup.id}")
        sources[setup.file] = mutated
        record(victim, "order_dep", "flaky", "order_dep", setup_test=setup.id)
        record(setup, "order_dep", "stable", "none", role="setup test of " + victim.id)
    for group in picks["shared_state"]:
        for target in group:
            sources[target.file] = _apply(source(target.file), OPERATORS["shared_state"], target)
            record(target, "shared_state", "flaky", "shared_state", module_group=[t.id for t in group])
    for category in ("timing", "randomness", "time_tz", "real_fail"):
        for target in picks[category]:
            sources[target.file] = _apply(source(target.file), OPERATORS[category], target)
            if category == "real_fail":
                record(target, category, "real", "none")
            else:
                record(target, category, "flaky", category)

    for file, text in sources.items():
        (out / file).write_text(text, encoding="utf-8")
    after = collect_ids(out)
    if after != ids:
        raise RuntimeError("the mutated suite does not collect the same tests in the same order")

    labels = [{"id": tid, **label_of[tid], "file_path": tid.split("::")[0]} for tid in ids]
    manifest = {
        "package": PACKAGE, "version": VERSION, "sdist_sha256": SDIST_SHA256, "seed": seed,
        "n_tests": len(ids), "pristine_runs": pristine,
        "counts": {k: sum(1 for x in labels if x["label"] == k) for k in ("flaky", "real", "stable")},
        "excluded_from_injection": sorted(EXCLUDED_FILES),
        "injections": injections,
    }
    (out / "labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
