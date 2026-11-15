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

from flakeguard.runner.events import EventLogger
from flakeguard.runner.sandbox import Sandbox


@dataclass
class TestRunOutcome:
    test_id: str
    outcome: str  # PASS, FAIL, SKIP, ERROR
    duration_s: float
    message: str = ""


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
    ) -> None:
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
    ) -> list[SliceResult]:
        """Execute baseline, shuffled, reversed, isolated, repeated, and parallel runs."""
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        env = self._build_env()
        results: list[SliceResult] = []

        # 1. Baseline Run (default order, disable randomizer if present)
        event_logger.log(
            "run", "progress", data={"mode": "baseline", "iteration": 1}
        )
        base_junit = artifacts_dir / "junit_baseline.xml"
        cmd = [
            self.python_exe,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            self.test_dir,
            f"--junitxml={str(base_junit.resolve())}",
        ]
        res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
        base_outcomes = parse_junit_xml(base_junit)
        results.append(
            SliceResult(
                mode="baseline",
                iteration=1,
                exit_code=res.exit_code,
                duration_s=res.duration,
                outcomes=base_outcomes,
                raw_stdout=res.stdout,
                raw_stderr=res.stderr,
                junit_path=base_junit,
            )
        )

        # 2. Shuffled N Runs
        for i in range(1, self.shuffled_n + 1):
            event_logger.log(
                "run", "progress", data={"mode": "shuffled", "iteration": i}
            )
            shuf_junit = artifacts_dir / f"junit_shuffled_{i}.xml"
            seed = 1000 + i
            cmd = [
                self.python_exe,
                "-m",
                "pytest",
                "-q",
                "-p",
                "randomly",
                f"--randomly-seed={seed}",
                self.test_dir,
                f"--junitxml={str(shuf_junit.resolve())}",
            ]
            res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
            outcomes = parse_junit_xml(shuf_junit)
            results.append(
                SliceResult(
                    mode="shuffled",
                    iteration=i,
                    exit_code=res.exit_code,
                    duration_s=res.duration,
                    outcomes=outcomes,
                    raw_stdout=res.stdout,
                    raw_stderr=res.stderr,
                    junit_path=shuf_junit,
                )
            )

        # 3. Reversed Run (collect test IDs and run in reversed order)
        event_logger.log(
            "run", "progress", data={"mode": "reversed", "iteration": 1}
        )
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
        results.append(
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
            event_logger.log(
                "run", "progress", test_id=tid, data={"mode": "isolated", "iteration": iso_idx}
            )
            iso_junit = artifacts_dir / f"junit_isolated_{iso_idx}.xml"
            cmd = [
                self.python_exe,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                tid,
                f"--junitxml={str(iso_junit.resolve())}",
            ]
            res = self.sandbox.run(cmd, cwd=self.repo_path, env=env, timeout=self.timeout)
            outcomes = parse_junit_xml(iso_junit)
            results.append(
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
        event_logger.log(
            "run", "progress", data={"mode": "repeated", "iteration": 1}
        )
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
        results.append(
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
        event_logger.log(
            "run", "progress", data={"mode": "parallel", "iteration": 1}
        )
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
        results.append(
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
