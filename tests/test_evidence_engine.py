"""Unit and integration tests for FlakeGuard Evidence Engine (Step 2)."""

import ast
from pathlib import Path

from flakeguard.contracts import EvidenceTier
from flakeguard.evidence.bisection import bisect_polluter
from flakeguard.evidence.engine import EvidenceEngine
from flakeguard.evidence.interventions import InterventionEngine
from flakeguard.evidence.read_write_map import (
    AccessMap,
    analyze_ast_access,
    extract_test_access_map,
    find_shared_state_overlap,
)
from flakeguard.runner.events import EventLogger

SYNTHETIC_DIR = Path(__file__).parent.parent / "synthetic"


# ---------------------------------------------------------------------------
# AST Read/Write Map Tests
# ---------------------------------------------------------------------------


def test_ast_access_visitor_basic():
    """Verify AST visitor detects assigns, reads, attributes, and calls."""
    code = """
def test_sample():
    import os
    shop._default_tax = 0.25
    rate = shop.calculate_tax(100)
    shop._cache.clear()
    token = os.getenv("API_KEY")
    os.environ["STATUS"] = "ACTIVE"
"""
    tree = ast.parse(code)
    func_node = tree.body[0]
    access = analyze_ast_access(func_node)

    assert "shop._default_tax" in access.writes
    assert "shop._cache" in access.writes
    assert "shop.calculate_tax" in access.reads
    assert "API_KEY" in access.env_reads
    assert "STATUS" in access.env_writes


def test_shared_state_overlap_resolution():
    """Verify shared state overlap connects polluter writes to victim reads."""
    polluter_map = AccessMap(
        writes={"shop._default_tax", "COUNTER"},
        env_writes={"MY_FLAG"},
    )
    victim_map = AccessMap(
        reads={"shop.calculate_tax", "shop._default_tax", "COUNTER"},
        env_reads={"MY_FLAG"},
    )

    state_overlap, env_overlap = find_shared_state_overlap(polluter_map, victim_map)
    assert "shop._default_tax" in state_overlap
    assert "COUNTER" in state_overlap
    assert "MY_FLAG" in env_overlap


def test_extract_test_access_map_synthetic():
    """Verify extraction of access map with callee resolution in synthetic repo."""
    test_file = SYNTHETIC_DIR / "tests" / "test_suite_01.py"
    m09 = extract_test_access_map(test_file, "test_case_09", repo_root=SYNTHETIC_DIR)
    m10 = extract_test_access_map(test_file, "test_case_10", repo_root=SYNTHETIC_DIR)

    assert "shop._default_tax" in m09.writes
    # m10 calls calculate_tax, which reads _default_tax
    assert any("default_tax" in r for r in m10.reads)

    overlap, _ = find_shared_state_overlap(m09, m10)
    assert "shop._default_tax" in overlap


# ---------------------------------------------------------------------------
# Polluter Bisection Tests
# ---------------------------------------------------------------------------


def test_bisect_polluter_reproduces_polluter():
    """Verify polluter bisection locates test_case_09 as the polluter for test_case_10."""
    order = [f"tests/test_suite_01.py::test_case_{i:02d}" for i in range(1, 11)]
    res = bisect_polluter(
        repo_path=SYNTHETIC_DIR,
        victim_id="tests/test_suite_01.py::test_case_10",
        execution_order=order,
    )

    assert res.relationship == "polluter"
    assert res.reproduced is True
    assert res.polluter_id == "tests/test_suite_01.py::test_case_09"
    assert res.minimal_reproducer == [
        "tests/test_suite_01.py::test_case_09",
        "tests/test_suite_01.py::test_case_10",
    ]


def test_bisect_polluter_reproduces_setter():
    """Verify dependency bisection locates test_case_01 as the prerequisite setter for test_case_02."""
    order = [f"tests/test_suite_01.py::test_case_{i:02d}" for i in range(1, 11)]
    res = bisect_polluter(
        repo_path=SYNTHETIC_DIR,
        victim_id="tests/test_suite_01.py::test_case_02",
        execution_order=order,
    )

    assert res.relationship == "setter"
    assert res.reproduced is True
    assert res.setter_id == "tests/test_suite_01.py::test_case_01"
    assert res.minimal_reproducer == [
        "tests/test_suite_01.py::test_case_01",
        "tests/test_suite_01.py::test_case_02",
    ]


# ---------------------------------------------------------------------------
# Targeted Interventions Tests
# ---------------------------------------------------------------------------


def test_intervention_pin_seed_flips_randomness():
    """Verify seed intervention flips test_case_16 outcome and confirms randomness."""
    engine = InterventionEngine()
    record = engine.pin_seed(
        repo_path=SYNTHETIC_DIR,
        test_id="tests/test_suite_02.py::test_case_16",
        base_outcome="PASS",
        seeds=[1, 2, 4, 42],
    )

    assert record.kind == "pin_seed"
    assert record.flipped is True
    assert record.outcome == "FAIL"
    assert record.parameters.get("confirmed_seed") == 4


def test_intervention_freeze_clock_flips_time_tz():
    """Verify clock freeze intervention flips test_case_19 outcome and confirms time_tz."""
    engine = InterventionEngine()
    record = engine.freeze_clock(
        repo_path=SYNTHETIC_DIR,
        test_id="tests/test_suite_02.py::test_case_19",
        base_outcome="FAIL",
    )

    assert record.kind == "freeze_clock"
    assert record.flipped is True
    assert record.outcome == "PASS"


# ---------------------------------------------------------------------------
# End-to-End Evidence Engine Diagnoses
# ---------------------------------------------------------------------------


def test_evidence_engine_order_dependent_diagnosis(tmp_path):
    """Verify EvidenceEngine produces REPRODUCED tier for order-dependent failure with events."""
    event_file = tmp_path / "evidence_events.jsonl"
    logger = EventLogger("test_run_evidence", output_path=event_file)

    engine = EvidenceEngine(
        repo_path=SYNTHETIC_DIR,
        event_logger=logger,
    )

    order = [f"tests/test_suite_01.py::test_case_{i:02d}" for i in range(1, 11)]
    report = engine.diagnose_test(
        test_id="tests/test_suite_01.py::test_case_10",
        base_outcome="PASS",
        execution_order=order,
        category_hint="order_dep",
    )

    assert report.tier == EvidenceTier.REPRODUCED
    assert report.polluter_test_id == "tests/test_suite_01.py::test_case_09"
    assert "shop._default_tax" in report.details.get("shared_state_overlap", [])

    # Check streamed events
    events = list(logger.read_events())
    assert any(e.stage == "evidence" and e.type == "started" for e in events)
    assert any(e.stage == "evidence" and e.type == "result" for e in events)


def test_evidence_engine_intervention_confirmed_diagnosis(tmp_path):
    """Verify EvidenceEngine produces INTERVENTION_CONFIRMED tier when an intervention flips outcome."""
    event_file = tmp_path / "evidence_events.jsonl"
    logger = EventLogger("test_run_intervention", output_path=event_file)

    engine = EvidenceEngine(
        repo_path=SYNTHETIC_DIR,
        event_logger=logger,
    )

    report = engine.diagnose_test(
        test_id="tests/test_suite_02.py::test_case_16",
        base_outcome="PASS",
        category_hint="randomness",
    )

    assert report.tier == EvidenceTier.INTERVENTION_CONFIRMED
    assert report.category == "randomness"
    assert report.details.get("confirmed_intervention") == "pin_seed"

