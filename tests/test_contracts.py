"""Trivial smoke test: verify that contracts can be imported."""
from flakeguard import contracts


def test_import_contracts():
    """Importing contracts must succeed and expose the core dataclasses."""
    assert hasattr(contracts, "Chunk")
    assert hasattr(contracts, "NavResult")
    assert hasattr(contracts, "LLMProvider")
    assert hasattr(contracts, "Retriever")
    assert hasattr(contracts, "Navigator")
    assert hasattr(contracts, "EvidenceTier")
    assert hasattr(contracts, "InterventionRecord")
    assert hasattr(contracts, "EvidenceReport")


def test_evidence_contracts():
    """Verify evidence contract types, immutability, and tier values."""
    assert contracts.EvidenceTier.OBSERVED == "observed"
    assert contracts.EvidenceTier.REPRODUCED == "reproduced"
    assert contracts.EvidenceTier.INTERVENTION_CONFIRMED == "intervention-confirmed"

    record = contracts.InterventionRecord(
        kind="pin_seed",
        parameters={"seed": 42},
        flipped=True,
        outcome="PASS",
        details="Flipped from FAIL to PASS when seed pinned",
    )
    assert record.kind == "pin_seed"
    assert record.flipped is True

    report = contracts.EvidenceReport(
        test_id="test_suite.py::test_case",
        tier=contracts.EvidenceTier.INTERVENTION_CONFIRMED,
        category="randomness",
        polluter_test_id=None,
        interventions=[record],
        shared_state_reads=["_cache"],
        shared_state_writes=[],
        details={"runs": 10},
    )
    assert report.tier == contracts.EvidenceTier.INTERVENTION_CONFIRMED
    assert len(report.interventions) == 1


def test_chunk_frozen():
    """Chunk must be immutable (frozen dataclass)."""
    c = contracts.Chunk(
        chunk_id="repo@sha:path:1-10",
        path="path",
        start_line=1,
        end_line=10,
        kind="test",
        text="def test_foo(): pass",
    )
    assert c.chunk_id == "repo@sha:path:1-10"
    try:
        c.score = 1.0  # type: ignore[misc]
        assert False, "should have raised"
    except Exception:
        pass
