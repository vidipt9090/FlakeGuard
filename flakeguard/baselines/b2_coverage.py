"""Baseline B2: Coverage-based flakiness classifier (DeFlaker methodology).

Verified Citation:
    Jonathan Bell, Owolabi Legunsen, Michael Hilton, Lamyaa Eloussi, Tifany Yung, Darko Marinov.
    "DeFlaker: Automatically Detecting Flaky Tests",
    Proceedings of the 40th International Conference on Software Engineering (ICSE 2018).

Methodology:
    A test failure in a continuous integration build that does NOT execute any modified
    lines from the commit diff cannot be caused by the newly introduced changes;
    DeFlaker therefore classifies it as flaky without requiring expensive reruns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class B2ClassificationResult:
    """Classification outcome for Baseline B2 (Coverage-diff)."""

    test_id: str
    prediction: Literal["flaky", "real_fail", "no_evidence"]
    covered_modified_lines: int
    executed_diff_lines: list[tuple[str, int]]
    rationale: str


class B2CoverageClassifier:
    """DeFlaker-style coverage diff flakiness classifier."""

    def __init__(self, changed_lines: set[tuple[str, int]] | None = None) -> None:
        """Args:

        changed_lines: Set of (relative_file_path, line_number) changed in the commit diff.
        """
        self.changed_lines: set[tuple[str, int]] = changed_lines or set()

    def classify_test(
        self,
        test_id: str,
        failed_in_build: bool,
        executed_lines: set[tuple[str, int]],
    ) -> B2ClassificationResult:
        """Classify a test using coverage diff heuristic.

        Args:
            test_id: Unique test identifier.
            failed_in_build: True if test failed in current CI run, False if passed.
            executed_lines: Set of (file_path, line_number) executed by this test.
        """
        if not failed_in_build:
            return B2ClassificationResult(
                test_id=test_id,
                prediction="no_evidence",
                covered_modified_lines=0,
                executed_diff_lines=[],
                rationale="Test passed in current build.",
            )

        # Compute overlap with code diff
        overlap = [line for line in executed_lines if line in self.changed_lines]

        if not overlap:
            # Failed without executing any modified lines -> cannot be caused by commit diff -> FLAKY!
            return B2ClassificationResult(
                test_id=test_id,
                prediction="flaky",
                covered_modified_lines=0,
                executed_diff_lines=[],
                rationale="Test failed without executing any modified lines in the commit diff (DeFlaker heuristic).",
            )

        # Executed modified lines -> possible regression
        return B2ClassificationResult(
            test_id=test_id,
            prediction="real_fail",
            covered_modified_lines=len(overlap),
            executed_diff_lines=overlap,
            rationale=f"Test executed {len(overlap)} modified lines in commit diff; candidate code regression.",
        )
