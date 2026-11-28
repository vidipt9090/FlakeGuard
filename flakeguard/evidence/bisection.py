"""Polluter and dependency bisection for order-dependent flaky tests."""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from flakeguard.runner.matrix import parse_junit_xml
from flakeguard.runner.sandbox import LocalProcessSandbox, Sandbox


@dataclass
class BisectionStep:
    iteration: int
    candidate_tests: list[str]
    outcome: str
    victim_outcome: str


@dataclass
class BisectionResult:
    victim_id: str
    polluter_id: str | None = None
    setter_id: str | None = None
    relationship: str = "none"  # "polluter" | "setter" | "none"
    reproduced: bool = False
    history: list[BisectionStep] = field(default_factory=list)
    minimal_reproducer: list[str] = field(default_factory=list)


def _run_test_sequence(
    repo_path: Path,
    test_ids: list[str],
    sandbox: Sandbox,
    timeout: float = 30.0,
) -> tuple[str, str | None]:
    """Run tests in exact given order (disabling randomizer) and return (victim_outcome, error_msg).

    The last test in test_ids is assumed to be the victim under test.
    """
    if not test_ids:
        return "PASS", None

    victim_id = test_ids[-1]
    with tempfile.TemporaryDirectory(prefix="flakeguard_bisect_") as tmpdir:
        junit_path = Path(tmpdir) / "junit_bisect.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            f"--junitxml={str(junit_path.resolve())}",
            *test_ids,
        ]

        sandbox.run(cmd, cwd=repo_path, timeout=timeout)
        if not junit_path.exists():
            return "ERROR", "JUnit XML not generated"

        outcomes = parse_junit_xml(junit_path)
        victim_outcome = "PASS"
        err_msg = None

        # Look up outcome for victim
        for out in outcomes:
            # Match either exact ID or function suffix
            if out.test_id == victim_id or out.test_id.endswith(f"::{victim_id.split('::')[-1]}"):
                victim_outcome = out.outcome
                err_msg = out.message
                break

        return victim_outcome, err_msg


def bisect_polluter(
    repo_path: Path,
    victim_id: str,
    execution_order: list[str],
    sandbox: Sandbox | None = None,
    timeout: float = 30.0,
) -> BisectionResult:
    """Bisect a test execution order to locate the minimal polluter or prerequisite setter.

    Args:
        repo_path: Repository root directory.
        victim_id: The test that exhibits order-dependent failure.
        execution_order: Ordered list of test IDs from the run where the failure occurred.
        sandbox: Execution sandbox (defaults to LocalProcessSandbox).
        timeout: Subprocess timeout in seconds.
    """
    sb = sandbox or LocalProcessSandbox(default_timeout=timeout)

    # 1. First test victim in complete isolation
    isolated_outcome, _ = _run_test_sequence(repo_path, [victim_id], sb, timeout=timeout)

    # Identify preceding tests
    try:
        victim_idx = execution_order.index(victim_id)
        prefix = execution_order[:victim_idx]
    except ValueError:
        prefix = [t for t in execution_order if t != victim_id]

    history: list[BisectionStep] = []

    # Case A: Victim PASSES in isolation -> It was polluted by some preceding test!
    if isolated_outcome == "PASS":
        if not prefix:
            return BisectionResult(
                victim_id=victim_id,
                relationship="none",
                reproduced=False,
                history=history,
            )

        # Binary search / delta bisection over prefix
        candidates = list(prefix)
        step_num = 0

        while len(candidates) > 1:
            step_num += 1
            mid = len(candidates) // 2
            left = candidates[:mid]
            right = candidates[mid:]

            # Try running left half + victim
            left_outcome, _ = _run_test_sequence(repo_path, [*left, victim_id], sb, timeout=timeout)
            history.append(BisectionStep(step_num, list(left), left_outcome, left_outcome))

            if left_outcome in ("FAIL", "ERROR"):
                candidates = left
                continue

            # Try running right half + victim
            right_outcome, _ = _run_test_sequence(repo_path, [*right, victim_id], sb, timeout=timeout)
            history.append(BisectionStep(step_num, list(right), right_outcome, right_outcome))

            if right_outcome in ("FAIL", "ERROR"):
                candidates = right
                continue

            # Neither individual half alone reproduced the failure.
            # Test each candidate pairwise with victim.
            found_polluter = None
            for cand in candidates:
                cand_outcome, _ = _run_test_sequence(repo_path, [cand, victim_id], sb, timeout=timeout)
                if cand_outcome in ("FAIL", "ERROR"):
                    found_polluter = cand
                    break

            if found_polluter:
                candidates = [found_polluter]
            break

        # Check minimal 1-on-1 candidate
        if len(candidates) == 1:
            cand = candidates[0]
            cand_outcome, _ = _run_test_sequence(repo_path, [cand, victim_id], sb, timeout=timeout)
            if cand_outcome in ("FAIL", "ERROR"):
                return BisectionResult(
                    victim_id=victim_id,
                    polluter_id=cand,
                    relationship="polluter",
                    reproduced=True,
                    history=history,
                    minimal_reproducer=[cand, victim_id],
                )

        return BisectionResult(
            victim_id=victim_id,
            relationship="polluter",
            reproduced=False,
            history=history,
        )

    # Case B: Victim FAILS in isolation -> It requires a preceding test (state setter)!
    if isolated_outcome in ("FAIL", "ERROR"):
        if not prefix:
            return BisectionResult(
                victim_id=victim_id,
                relationship="none",
                reproduced=False,
                history=history,
            )

        step_num = 0
        candidates = list(prefix)

        # Check pairwise to find which setter turns the failure into PASS
        for cand in reversed(candidates):
            step_num += 1
            pair_outcome, _ = _run_test_sequence(repo_path, [cand, victim_id], sb, timeout=timeout)
            history.append(BisectionStep(step_num, [cand], pair_outcome, pair_outcome))
            if pair_outcome == "PASS":
                return BisectionResult(
                    victim_id=victim_id,
                    setter_id=cand,
                    relationship="setter",
                    reproduced=True,
                    history=history,
                    minimal_reproducer=[cand, victim_id],
                )

        return BisectionResult(
            victim_id=victim_id,
            relationship="setter",
            reproduced=False,
            history=history,
        )

    return BisectionResult(
        victim_id=victim_id,
        relationship="none",
        reproduced=False,
        history=history,
    )
