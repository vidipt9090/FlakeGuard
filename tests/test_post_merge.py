"""Tests for post-merge honest flakiness reporting logic."""

import json
from pathlib import Path

from scripts.report_post_merge import evaluate_post_merge


def test_post_merge_reports_failure_on_runner_exit_error(tmp_path: Path):
    """When scan runner exits with non-zero code, report scan did not complete and never no evidence."""
    msg, is_success = evaluate_post_merge(artifacts_dir=str(tmp_path), scan_exit_code=1)
    assert not is_success
    assert "Verification scan did not complete (runner exited with error)" in msg
    assert "No evidence of flakiness" not in msg


def test_post_merge_reports_failure_on_missing_event_log(tmp_path: Path):
    """When event log is missing or empty, refuse to report flakiness verdict."""
    msg, is_success = evaluate_post_merge(artifacts_dir=str(tmp_path), scan_exit_code=0)
    assert not is_success
    assert "Verification scan did not complete (event log missing or empty)" in msg
    assert "No evidence of flakiness" not in msg


def test_post_merge_reports_failure_on_zero_total_slices(tmp_path: Path):
    """When event log has zero recorded slices, fail honestly."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(json.dumps({"stage": "run", "type": "result", "data": {"total_slices": 0}}), encoding="utf-8")

    msg, is_success = evaluate_post_merge(artifacts_dir=str(tmp_path), scan_exit_code=0)
    assert not is_success
    assert "Verification scan did not complete (zero test slices recorded)" in msg
    assert "No evidence of flakiness" not in msg


def test_post_merge_reports_honest_no_evidence_with_real_count(tmp_path: Path):
    """When scan completes with zero flakes, report exact honest count from event log."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(json.dumps({"stage": "run", "type": "result", "data": {"total_slices": 5}}), encoding="utf-8")
    findings_file = tmp_path / "findings.json"
    findings_file.write_text(json.dumps([{"test_id": "test_1", "verdict": "real"}]), encoding="utf-8")

    msg, is_success = evaluate_post_merge(artifacts_dir=str(tmp_path), scan_exit_code=0)
    assert is_success
    assert "✅ **No evidence of flakiness in 5 runs after this change**" in msg


def test_post_merge_reports_flakiness_detected(tmp_path: Path):
    """When scan detects a flaky test, report flakiness detected with real run count."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(json.dumps({"stage": "run", "type": "result", "data": {"total_slices": 4}}), encoding="utf-8")
    findings_file = tmp_path / "findings.json"
    findings_file.write_text(json.dumps([{"test_id": "test_1", "verdict": "flaky"}]), encoding="utf-8")

    msg, is_success = evaluate_post_merge(artifacts_dir=str(tmp_path), scan_exit_code=0)
    assert is_success
    assert "⚠️ Flakiness detected after merge in 4 runs." in msg
