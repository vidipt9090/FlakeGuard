"""Trivial smoke test: verify that contracts can be imported."""
from flakeguard import contracts


def test_import_contracts():
    """Importing contracts must succeed and expose the core dataclasses."""
    assert hasattr(contracts, "Chunk")
    assert hasattr(contracts, "NavResult")
    assert hasattr(contracts, "LLMProvider")
    assert hasattr(contracts, "Retriever")
    assert hasattr(contracts, "Navigator")


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
