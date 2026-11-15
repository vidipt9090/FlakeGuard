"""Strict validation gate for generated tests: must pass at HEAD, be deterministic over k runs, and kill mutants."""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from flakeguard.injector.operators import MutationOperator
from flakeguard.notest.generator import GeneratedTest
from flakeguard.runner.matrix import parse_junit_xml
from flakeguard.runner.sandbox import LocalProcessSandbox, Sandbox


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of strict multi-stage test validation gate."""

    test_name: str
    passed_at_head: bool
    deterministic_over_k: bool
    k_runs: int
    killed_mutant: bool
    kept: bool
    rejection_reason: str | None = None


def _execute_test_file(
    repo_path: Path,
    test_file_path: Path,
    sandbox: Sandbox,
    extra_args: list[str] | None = None,
    timeout: float = 30.0,
) -> bool:
    """Run a test file in the sandbox and return True if all tests in file PASSED."""
    with tempfile.TemporaryDirectory(prefix="flakeguard_val_") as tmpdir:
        junit_path = Path(tmpdir) / "junit_val.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--junitxml={str(junit_path.resolve())}",
            *(extra_args or []),
            str(test_file_path.resolve()),
        ]

        res = sandbox.run(cmd, cwd=repo_path, timeout=timeout)
        if res.timed_out or not junit_path.exists():
            return False

        outcomes = parse_junit_xml(junit_path)
        if not outcomes:
            return False

        return all(o.outcome == "PASS" for o in outcomes)


def validate_generated_test(
    repo_path: Path,
    test: GeneratedTest,
    k: int = 5,
    mutation_operator: MutationOperator | None = None,
    sandbox: Sandbox | None = None,
    timeout: float = 30.0,
) -> ValidationResult:
    """Validate a generated test against strict acceptance criteria.

    Keep a test ONLY if it:
    1. Runs and passes at HEAD.
    2. Is deterministic over k shuffled runs.
    3. (If mutation operator provided) Successfully kills the injected mutant (fails when mutated).
    """
    sb = sandbox or LocalProcessSandbox(default_timeout=timeout)

    # Place test in a temporary file inside the repo's test directory
    tests_dir = repo_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    temp_test_file = tests_dir / "_test_flakeguard_generated_temp.py"

    try:
        temp_test_file.write_text(test.test_code, encoding="utf-8")

        # 1. Runs and passes at HEAD
        passes_head = _execute_test_file(repo_path, temp_test_file, sb, timeout=timeout)
        if not passes_head:
            return ValidationResult(
                test_name=test.test_name,
                passed_at_head=False,
                deterministic_over_k=False,
                k_runs=0,
                killed_mutant=False,
                kept=False,
                rejection_reason="Test failed to pass at HEAD",
            )

        # 2. Deterministic over k shuffled runs
        for seed in range(1, k + 1):
            shuffled_pass = _execute_test_file(
                repo_path,
                temp_test_file,
                sb,
                extra_args=[f"--randomly-seed={seed}"],
                timeout=timeout,
            )
            if not shuffled_pass:
                return ValidationResult(
                    test_name=test.test_name,
                    passed_at_head=True,
                    deterministic_over_k=False,
                    k_runs=seed,
                    killed_mutant=False,
                    kept=False,
                    rejection_reason=f"Failed shuffled determinism check on run {seed}/{k}",
                )

        # 3. Mutant killing (if mutation operator provided and target file exists)
        killed_mutant = True  # Default true if no mutation operator tested
        if mutation_operator is not None and test.target_file:
            target_path = Path(test.target_file)
            if not target_path.is_absolute():
                target_path = repo_path / target_path

            if target_path.is_file():
                orig_content = target_path.read_text(encoding="utf-8")
                mutation = mutation_operator.apply(orig_content, test.target_function)
                if mutation is not None:
                    try:
                        # Write mutated code
                        target_path.write_text(mutation.mutated_code, encoding="utf-8")
                        # Run test against mutant
                        mutant_passed = _execute_test_file(repo_path, temp_test_file, sb, timeout=timeout)
                        # To kill the mutant, the test must FAIL when mutant is active!
                        killed_mutant = not mutant_passed
                    finally:
                        # Always restore original code immediately
                        target_path.write_text(orig_content, encoding="utf-8")

                if not killed_mutant:
                    return ValidationResult(
                        test_name=test.test_name,
                        passed_at_head=True,
                        deterministic_over_k=True,
                        k_runs=k,
                        killed_mutant=False,
                        kept=False,
                        rejection_reason="Test failed to kill injected mutant (did not fail on buggy code)",
                    )

        return ValidationResult(
            test_name=test.test_name,
            passed_at_head=True,
            deterministic_over_k=True,
            k_runs=k,
            killed_mutant=killed_mutant,
            kept=True,
            rejection_reason=None,
        )

    finally:
        # Clean up temporary test file
        if temp_test_file.exists():
            try:
                temp_test_file.unlink()
            except Exception:
                pass

