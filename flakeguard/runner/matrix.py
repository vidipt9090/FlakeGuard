"""Perturbation Matrix Runner for test flakiness diagnosis.

Runs:
1. Baseline (standard collection order, no shuffling)
2. Shuffled N (randomized execution order with distinct seeds)
3. Reversed (reversed test execution order via collected test list)
4. Isolated (each failing or candidate test executed in its own isolated process)
5. Repeated (repeated executions to expose race conditions)
6. Parallel (concurrent test execution)
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from flakeguard.runner.events import EventLogger
from flakeguard.runner.sandbox import Sandbox


def to_node_id(repo_path: Path, test_id: str) -> str:
    """Turn a JUnit-style id (``tests.test_a::test_x``) into a pytest node id.

    JUnit gives a dotted module name, but pytest only accepts a path, so passing
    the dotted form selects no tests. Ids that are already paths, and modules
    that cannot be found on disk, are returned unchanged.
    """
    module, sep, name = test_id.partition("::")
    if not sep or "/" in module or module.endswith(".py"):
        return test_id
    candidate = module.replace(".", "/") + ".py"
    if (repo_path / candidate).is_file():
        return f"{candidate}::{name}"
    return test_id


@dataclass
class TestRunOutcome:
    test_id: str
    outcome: str  # PASS, FAIL, SKIP, ERROR
    duration_s: float
    message: str = ""


# Shuffled run i uses seed `seed_start + i - 1`. The default keeps the seeds the engine always
# used (1001, 1002, ...), so existing scans are unchanged.
DEFAULT_SEED_START = 1001


class RunObserver(Protocol):
    """Told about every individual run as it starts and ends (used for live progress)."""

    def on_run_start(self, mode: str, iteration: int, seed: int | None, test_id: str | None) -> None: ...

    def on_run_end(self, result: "SliceResult") -> None: ...


@dataclass
class SliceResult:
    mode: str  # baseline, shuffled, reversed, isolated, repeated, parallel
    iteration: int
    exit_code: int
    duration_s: float
    outcomes: list[TestRunOutcome] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""
    junit_path: Path | None = None
    seed: int | None = None  # pytest-randomly seed; only the shuffled runs have one


def parse_junit_xml(xml_path: Path) -> list[TestRunOutcome]:
    """Parse a JUnit XML file to extract individual test case results."""
    outcomes: list[TestRunOutcome] = []
    if not xml_path.is_file() or xml_path.stat().st_size == 0:
        return outcomes

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception:
        return outcomes

    # Root can be <testsuites> or <testsuite>
    testsuites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    for suite in testsuites:
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "")
            time_val = float(case.attrib.get("time", "0.0") or 0.0)

            # Build canonical test_id (e.g. tests/test_foo.py::test_bar)
            file_attr = case.attrib.get("file", "")
            if file_attr:
                test_id = f"{file_attr}::{name}"
            elif classname:
                test_id = f"{classname}::{name}"
            else:
                test_id = name

            # Determine outcome
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                outcome = "FAIL"
                msg = failure.attrib.get("message", "") or (failure.text or "")
            elif error is not None:
                outcome = "ERROR"
                msg = error.attrib.get("message", "") or (error.text or "")
            elif skipped is not None:
                outcome = "SKIP"
                msg = skipped.attrib.get("message", "") or (skipped.text or "")
            else:
                outcome = "PASS"
                msg = ""

            outcomes.append(
                TestRunOutcome(
                    test_id=test_id,
                    outcome=outcome,
                    duration_s=time_val,
                    message=msg.strip(),
                )
            )

    return outcomes


class PerturbationMatrix:
    """Executes the 6-slice perturbation matrix through a provided Sandbox."""

    def __init__(
        self,
        sandbox: Sandbox,
        repo_path: Path,
        shuffled_n: int = 5,
        test_dir: str = "tests",
        timeout: float = 60.0,
        python_exe: str = "python",
        seed_start: int = DEFAULT_SEED_START,
    ) -> None:
        self.seed_start = seed_start
        self.sandbox = sandbox
        self.repo_path = repo_path.resolve()
        self.shuffled_n = shuffled_n
        self.test_dir = test_dir
        self.timeout = timeout
        self.python_exe = python_exe

    def _build_env(self) -> dict[str, str]:
        """Prepare PYTHONPATH including repo root and common src/ dirs."""
        paths = [str(self.repo_path)]
        if (self.repo_path / "src").is_dir():
            paths.insert(0, str(self.repo_path / "src"))
        if (self.repo_path / "synthetic" / "src").is_dir():
            paths.insert(0, str(self.repo_path / "synthetic" / "src"))

        current_pythonpath = os.environ.get("PYTHONPATH", "")
        if current_pythonpath:
            paths.append(current_pythonpath)

        return {"PYTHONPATH": os.pathsep.join(paths)}

    def _collect_test_ids(self) -> list[str]:
        """Collect test IDs using pytest --collect-only -q."""
        cmd = [self.python_exe, "-m", "pytest", "--collect-only", "-q", self.test_dir]
        res = self.sandbox.run(
            cmd, cwd=self.repo_path, env=self._build_env(), timeout=30.0
        )
        if res.exit_code != 0:
            return []

        test_ids = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if "::" in line and not line.startswith("<"):
                test_ids.append(line)
        return test_ids

    def run_matrix(
        self,
        artifacts_dir: Path,
        event_logger: EventLogger,
        observer: RunObserver | None = None,
        preloaded: Path | None = None,
    ) -> list[SliceResult]:
        """Execute baseline, shuffled, reversed, isolated, repeated, and parallel runs.

        ``preloaded`` is a directory holding ``junit_baseline.xml`` and ``junit_shuffled_<i>.xml``
        produced elsewhere (the per-seed jobs of the GitHub Actions workflow). Those runs are read
        instead of executed, and are marked ``preloaded`` in the event log.
        """
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        env = self._build_env()
        results: list[SliceResult] = []

        def begin(
            mode: str, iteration: int, seed: int | None = None, test_id: str | None = None,
            preloaded_run: bool = False,
        ) -> None:
            data: dict[str, object] = {"mode": mode, "iteration": iteration}
            if seed is not None:
                data["seed"] = seed
            if preloaded_run:
                data["preloaded"] = True
            event_logger.log("run", "progress", test_id=test_id, data=data)
            if observer is not None:
                observer.on_run_start(mode, iteration, seed, test_id)

        def finish(result: SliceResult) -> None:
            results.append(result)
            if observer is not None:
                observer.on_run_end(result)

        def preloaded_file(name: str) -> Path | None:
            if preloaded is None:
                return None
            path = preloaded / name
            return path if path.is_file() and path.stat().st_size > 0 else None

        def use_preloaded(source: Path, dest: Path) -> Path:
            if source.resolve() != dest.resolve():
                dest.write_bytes(source.read_bytes())
            return dest

        # 1. Baseline Run (default order, disable randomizer if present)
        base_junit = artifacts_dir / "junit_baseline.xml"
        base_pre = preloaded_file("junit_baseline.xml")
        begin("baseline", 1, preloaded_run=base_pre is not None)
        if base_pre is not None:
            use_preloaded(base_pre, base_junit)
            finish(SliceResult(
                mode="baseline", iteration=1, exit_code=0, duration_s=0.0,
                outcomes=parse_junit_xml(base_junit), junit_path=base_junit,
            ))
        else:
            cmd = [
                self.python_exe, "-m", "pytest", "-q", "-p", "no:randomly", self.test_dir,
                f"--junitxml={str(base_junit.resolve())}",
            ]
            res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
            finish(SliceResult(
                mode="baseline", iteration=1, exit_code=res.exit_code, duration_s=res.duration,
                outcomes=parse_junit_xml(base_junit), raw_stdout=res.stdout, raw_stderr=res.stderr,
                junit_path=base_junit,
            ))

        # 2. Shuffled N Runs
        for i in range(1, self.shuffled_n + 1):
            seed = self.seed_start + i - 1
            shuf_junit = artifacts_dir / f"junit_shuffled_{i}.xml"
            shuf_pre = preloaded_file(f"junit_shuffled_{i}.xml")
            begin("shuffled", i, seed=seed, preloaded_run=shuf_pre is not None)
            if shuf_pre is not None:
                use_preloaded(shuf_pre, shuf_junit)
                finish(SliceResult(
                    mode="shuffled", iteration=i, seed=seed, exit_code=0, duration_s=0.0,
                    outcomes=parse_junit_xml(shuf_junit), junit_path=shuf_junit,
                ))
                continue
            cmd = [
                self.python_exe, "-m", "pytest", "-q", "-p", "randomly", f"--randomly-seed={seed}",
                self.test_dir, f"--junitxml={str(shuf_junit.resolve())}",
            ]
            res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
            finish(SliceResult(
                mode="shuffled", iteration=i, seed=seed, exit_code=res.exit_code, duration_s=res.duration,
                outcomes=parse_junit_xml(shuf_junit), raw_stdout=res.stdout, raw_stderr=res.stderr,
                junit_path=shuf_junit,
            ))

        # 3. Reversed Run (collect test IDs and run in reversed order)
        begin("reversed", 1)
        rev_junit = artifacts_dir / "junit_reversed.xml"
        collected = self._collect_test_ids()
        if collected:
            reversed_ids = list(reversed(collected))
            cmd = [
                self.python_exe,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                f"--junitxml={str(rev_junit.resolve())}",
            ] + reversed_ids
        else:
            cmd = [
                self.python_exe,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                self.test_dir,
                f"--junitxml={str(rev_junit.resolve())}",
            ]

        res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
        rev_outcomes = parse_junit_xml(rev_junit)
        finish(
            SliceResult(
                mode="reversed",
                iteration=1,
                exit_code=res.exit_code,
                duration_s=res.duration,
                outcomes=rev_outcomes,
                raw_stdout=res.stdout,
                raw_stderr=res.stderr,
                junit_path=rev_junit,
            )
        )

        # Identify suspect / flaky / failed tests from previous runs for isolated check
        all_test_ids = {o.test_id for r in results for o in r.outcomes}
        failing_or_suspect: set[str] = set()
        test_history: dict[str, list[str]] = {tid: [] for tid in all_test_ids}
        for r in results:
            for o in r.outcomes:
                test_history[o.test_id].append(o.outcome)

        for tid, outcomes in test_history.items():
            if "FAIL" in outcomes or "ERROR" in outcomes:
                failing_or_suspect.add(tid)

        # If none failed, isolate up to 3 sampled tests
        candidates_to_isolate = list(failing_or_suspect) or list(all_test_ids)[:3]

        # 4. Isolated Runs
        iso_idx = 1
        for tid in candidates_to_isolate[:5]:  # bound to top 5
            begin("isolated", iso_idx, test_id=tid)
            iso_junit = artifacts_dir / f"junit_isolated_{iso_idx}.xml"
            cmd = [
                self.python_exe,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                to_node_id(self.repo_path, tid),
                f"--junitxml={str(iso_junit.resolve())}",
            ]
            res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
            outcomes = parse_junit_xml(iso_junit)
            finish(
                SliceResult(
                    mode="isolated",
                    iteration=iso_idx,
                    exit_code=res.exit_code,
                    duration_s=res.duration,
                    outcomes=outcomes,
                    raw_stdout=res.stdout,
                    raw_stderr=res.stderr,
                    junit_path=iso_junit,
                )
            )
            iso_idx += 1

        # 5. Repeated Run (pytest-repeat --count=3)
        begin("repeated", 1)
        rep_junit = artifacts_dir / "junit_repeated.xml"
        cmd = [
            self.python_exe,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "--count=3",
            self.test_dir,
            f"--junitxml={str(rep_junit.resolve())}",
        ]
        res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
        rep_outcomes = parse_junit_xml(rep_junit)
        finish(
            SliceResult(
                mode="repeated",
                iteration=1,
                exit_code=res.exit_code,
                duration_s=res.duration,
                outcomes=rep_outcomes,
                raw_stdout=res.stdout,
                raw_stderr=res.stderr,
                junit_path=rep_junit,
            )
        )

        # 6. Parallel Run
        begin("parallel", 1)
        par_junit = artifacts_dir / "junit_parallel.xml"
        # Try -n 2 if xdist is installed; otherwise fallback sequentially
        cmd = [
            self.python_exe,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "-n",
            "2",
            self.test_dir,
            f"--junitxml={str(par_junit.resolve())}",
        ]
        res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
        if res.exit_code != 0 and "unrecognized arguments: -n" in res.stderr:
            cmd = [
                self.python_exe,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                self.test_dir,
                f"--junitxml={str(par_junit.resolve())}",
            ]
            res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)

        par_outcomes = parse_junit_xml(par_junit)
        finish(
            SliceResult(
                mode="parallel",
                iteration=1,
                exit_code=res.exit_code,
                duration_s=res.duration,
                outcomes=par_outcomes,
                raw_stdout=res.stdout,
                raw_stderr=res.stderr,
                junit_path=par_junit,
            )
        )

        return results
