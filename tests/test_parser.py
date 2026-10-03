"""Tests for flakeguard.parser.junit and flakeguard.parser.redact."""
from __future__ import annotations

from pathlib import Path

from flakeguard.parser.junit import parse_junit_file
from flakeguard.parser.redact import redact

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "data"
SAMPLE_XML = FIXTURE_DIR / "junit-1.xml"


# ---------------------------------------------------------------------------
# redact tests
# ---------------------------------------------------------------------------


class TestRedact:
    def test_email_is_masked(self):
        text = "Contact user@example.com for help"
        result = redact(text)
        assert "user@example.com" not in result
        assert "[REDACTED_EMAIL]" in result

    def test_phone_like_string_is_masked(self):
        text = "Call +91-9876543210 now"
        result = redact(text)
        assert "9876543210" not in result

    def test_long_token_is_masked(self):
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact(f"Authorization: Bearer {token}")
        assert token not in result
        assert "[REDACTED_TOKEN]" in result

    def test_plain_text_unchanged(self):
        text = "no sensitive data here"
        assert redact(text) == text

    def test_empty_string(self):
        assert redact("") == ""


# ---------------------------------------------------------------------------
# junit parser tests
# ---------------------------------------------------------------------------


class TestParseJunitFile:
    def test_parses_sample_xml(self):
        rows = parse_junit_file(SAMPLE_XML)
        assert len(rows) == 4

    def test_run_id_and_seed_from_filename(self):
        rows = parse_junit_file(SAMPLE_XML)
        assert all(r["run_id"] == 1 for r in rows)
        assert all(r["seed"] == 1 for r in rows)

    def test_outcomes(self):
        rows = parse_junit_file(SAMPLE_XML)
        outcomes = {r["test_id"].split("::")[-1]: r["outcome"] for r in rows}
        assert outcomes["test_lru_cache_hit"] == "passed"
        assert outcomes["test_lru_cache_miss"] == "failed"
        assert outcomes["test_ttl_expire"] == "skipped"
        assert outcomes["test_lfu_eviction"] == "passed"

    def test_required_fields_present(self):
        rows = parse_junit_file(SAMPLE_XML)
        required = {
            "repo", "sha", "run_id", "test_id", "outcome",
            "duration_s", "order_index", "seed", "py_version", "log_path",
        }
        for row in rows:
            assert required.issubset(row.keys()), f"Missing fields in {row}"

    def test_order_index_monotone(self):
        rows = parse_junit_file(SAMPLE_XML)
        indices = [r["order_index"] for r in rows]
        assert indices == sorted(indices)

    def test_duration_s_nonnegative(self):
        rows = parse_junit_file(SAMPLE_XML)
        assert all(r["duration_s"] >= 0 for r in rows)
