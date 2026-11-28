"""Test provenance contracts (Principle 0): Every results metric must carry provenance metadata."""

import csv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results" / "eval3"

REQUIRED_PROVENANCE_KEYS = {"command", "git_sha", "timestamp", "data_label"}
VALID_DATA_LABELS = {"planted", "injected", "natural"}


@pytest.mark.parametrize("csv_file", [
    "baseline_comparison.csv",
    "evidence_ablation.csv",
    "calibration_reliability.csv",
    "risk_coverage.csv",
])
def test_results_csv_carries_strict_provenance(csv_file: str):
    path = RESULTS_DIR / csv_file
    assert path.is_file(), f"Expected results file {path} to exist."

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) > 0, f"Expected non-empty rows in {csv_file}"

    for idx, row in enumerate(rows):
        missing = REQUIRED_PROVENANCE_KEYS - set(row.keys())
        assert not missing, f"Row {idx} in {csv_file} missing required provenance keys: {missing}"

        # Verify command is non-empty
        assert row["command"].strip(), f"Row {idx} in {csv_file} has empty command."

        # Verify git_sha is valid hex sha
        git_sha = row["git_sha"].strip()
        assert len(git_sha) == 40 and all(c in "0123456789abcdefABCDEF" for c in git_sha), (
            f"Row {idx} in {csv_file} has invalid git_sha: {git_sha!r}"
        )

        # Verify timestamp is ISO format
        ts = row["timestamp"].strip()
        assert "T" in ts and ts.endswith("Z"), f"Row {idx} in {csv_file} has non-ISO timestamp: {ts!r}"

        # Verify data_label is one of planted, injected, natural
        label = row["data_label"].strip()
        assert label in VALID_DATA_LABELS, (
            f"Row {idx} in {csv_file} has invalid data_label: {label!r}. Expected one of {VALID_DATA_LABELS}"
        )
