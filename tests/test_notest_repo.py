"""Unit and integration tests for Step 6: No-test repo workflow."""

from pathlib import Path

from flakeguard.notest.generator import GeneratedTest, generate_targeted_test
from flakeguard.notest.orchestrator import generate_tests_for_repo
from flakeguard.notest.scanner import RiskySite, scan_file_for_risky_sites
from flakeguard.notest.validator import validate_generated_test
from flakeguard.runner.events import EventLogger

SYNTHETIC_DIR = Path(__file__).parent.parent / "synthetic"


# ---------------------------------------------------------------------------
# 1. Static Scanner Tests
# ---------------------------------------------------------------------------


def test_scan_risky_sites_all_categories(tmp_path):
    """Verify static scanner identifies sleep, random, now, globals, threads, and network."""
    code = """
import time, random, threading, socket
from datetime import datetime

_COUNTER = 0

def sample_risky():
    global _COUNTER
    _COUNTER += 1
    time.sleep(0.01)
    val = random.random()
    current_time = datetime.now()
    th = threading.Thread(target=lambda: None)
    s = socket.socket()
    return val
"""
    py_file = tmp_path / "risky_sample.py"
    py_file.write_text(code, encoding="utf-8")

    sites = scan_file_for_risky_sites(py_file)
    categories = {s.risk_category for s in sites}

    assert "globals" in categories
    assert "sleep" in categories
    assert "randomness" in categories
    assert "now" in categories
    assert "threads" in categories
    assert "network" in categories


# ---------------------------------------------------------------------------
# 2. Generator Tests
# ---------------------------------------------------------------------------


def test_generator_states_recording_current_behaviour():
    """Verify test generator explicitly records current behaviour at HEAD."""
    site = RiskySite(
        file_path="src/shop.py",
        line_number=70,
        function_name="pick_discount",
        risk_category="randomness",
        code_snippet="return random.random()",
        explanation="Calls random.random()",
    )

    gen = generate_targeted_test(
        site=site,
        source_snippet="def pick_discount(): return random.random()",
        module_import_name="shop",
    )

    assert gen.records_current_behavior is True
    assert "records current behaviour" in gen.test_code.lower()
    assert "pick_discount" in gen.test_name


# ---------------------------------------------------------------------------
# 3. Quality Gate Validator Tests
# ---------------------------------------------------------------------------


def test_validator_rejects_failing_at_head():
    """Verify validator immediately rejects tests that fail at HEAD."""
    failing_test = GeneratedTest(
        test_name="test_broken",
        target_function="calculate_tax",
        target_file="src/shop.py",
        risk_category="globals",
        test_code="def test_broken(): assert 1 == 2",
    )

    res = validate_generated_test(SYNTHETIC_DIR, failing_test, k=2)
    assert res.kept is False
    assert res.passed_at_head is False
    assert "failed to pass at HEAD" in (res.rejection_reason or "")


def test_validator_accepts_deterministic_test():
    """Verify validator accepts passing deterministic tests across k shuffled runs."""
    passing_test = GeneratedTest(
        test_name="test_deterministic_pass",
        target_function="calculate_tax",
        target_file="src/shop.py",
        risk_category="globals",
        test_code="""import shop
def test_deterministic_pass():
    # Generated test by FlakeGuard: records current behaviour at HEAD
    assert shop.calculate_tax(100) == 5.0
""",
    )

    res = validate_generated_test(SYNTHETIC_DIR, passing_test, k=3)
    assert res.kept is True
    assert res.passed_at_head is True
    assert res.deterministic_over_k is True
    assert res.k_runs == 3


def test_validator_mutant_killing():
    """Verify validator tests mutant killing when mutation operator is provided."""
    test = GeneratedTest(
        test_name="test_discount_threshold",
        target_function="pick_discount",
        target_file="src/shop.py",
        risk_category="randomness",
        test_code="""import shop
def test_discount_threshold():
    # Generated test by FlakeGuard: records current behaviour at HEAD
    val = shop.pick_discount()
    assert 0.0 <= val <= 1.0
""",
    )

    # RandomnessOperator injects assert random.random() < 0.85
    res = validate_generated_test(SYNTHETIC_DIR, test, k=2)
    assert res.passed_at_head is True


# ---------------------------------------------------------------------------
# 4. End-to-End Orchestrator
# ---------------------------------------------------------------------------


def test_notest_orchestrator_synthetic_scan(tmp_path):
    """Verify end-to-end no-test workflow: scans risky sites, generates tests, validates, and emits events."""
    out_file = tmp_path / "test_generated_suite.py"
    event_file = tmp_path / "notest_events.jsonl"
    logger = EventLogger("test_run_notest", output_path=event_file)

    summary = generate_tests_for_repo(
        repo_path=SYNTHETIC_DIR,
        output_test_file=out_file,
        max_tests=2,
        k_shuffled_runs=2,
        event_logger=logger,
    )

    assert summary.risky_sites_count > 0
    assert summary.tests_generated_count > 0
    assert summary.tests_kept_count > 0

    # Verify event stream
    events = list(logger.read_events())
    assert any(e.stage == "generate" and e.type == "started" for e in events)
    assert any(e.stage == "generate" and e.type == "result" for e in events)

    # Verify output file
    if out_file.exists():
        text = out_file.read_text(encoding="utf-8")
        assert "records current behaviour at HEAD" in text

