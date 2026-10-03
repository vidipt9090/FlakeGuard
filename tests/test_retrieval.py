"""Tests for the retrieval chunker, and a smoke test for the embedder.

The chunker is pure `ast` and always runs. The embedding tests are skipped
unless chromadb and sentence-transformers are installed, so CI does not have
to download PyTorch to check the part that actually has logic in it.
"""

from importlib.util import find_spec
from pathlib import Path

import pytest

from flakeguard.contracts import Chunk
from flakeguard.retrieval.chunker import MIN_LINES, chunk_file, chunk_repo

SAMPLE = Path(__file__).parent / "data" / "navsample"

needs_rag = pytest.mark.skipif(
    find_spec("chromadb") is None or find_spec("sentence_transformers") is None,
    reason="chromadb and sentence-transformers are optional: pip install -e '.[rag]'",
)


# ------------------------------------------------------------------ chunker


@pytest.fixture(scope="module")
def chunks():
    return chunk_repo(SAMPLE, repo="navsample", sha="test")


def test_chunks_the_whole_sample_repo(chunks):
    assert chunks
    assert all(isinstance(c, Chunk) for c in chunks)


def test_finds_module_level_functions(chunks):
    names = [c for c in chunks if c.path == "src/shop.py"]
    assert any("def total(" in c.text for c in names)
    assert any("def slow_job(" in c.text for c in names)


def test_indexes_methods_separately_from_their_class(chunks):
    """A 200-line class is one blob to an embedding model."""
    in_tests = [c for c in chunks if c.path == "tests/test_shop.py"]
    assert any(c.kind == "class" and "class TestRegistry" in c.text for c in in_tests)
    assert any(
        c.kind == "test" and c.text.strip().startswith("def test_register")
        for c in in_tests
    )


def test_marks_tests_apart_from_other_functions(chunks):
    kinds = {c.kind for c in chunks}
    assert "test" in kinds
    assert "function" in kinds


def test_chunk_id_follows_the_contract(chunks):
    for chunk in chunks:
        assert chunk.chunk_id == (
            f"navsample@test:{chunk.path}:{chunk.start_line}-{chunk.end_line}"
        )


def test_line_range_matches_the_text(chunks):
    for chunk in chunks:
        assert chunk.end_line >= chunk.start_line
        assert len(chunk.text.splitlines()) == chunk.end_line - chunk.start_line + 1


def test_skips_one_line_definitions(tmp_path):
    f = tmp_path / "tiny.py"
    f.write_text("def a(): return 1\n\n\ndef b():\n    return 2\n", encoding="utf-8")
    got = chunk_file(f, tmp_path, "r", "s")
    assert [c.text.splitlines()[0] for c in got] == ["def b():"]
    assert all(c.end_line - c.start_line + 1 >= MIN_LINES for c in got)


def test_unparseable_file_is_skipped_not_fatal(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_text("def oops(:\n", encoding="utf-8")
    assert chunk_file(bad, tmp_path, "r", "s") == []


def test_ignores_virtualenvs_and_caches(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    (tmp_path / "real.py").write_text("def y():\n    return 1\n", encoding="utf-8")
    paths = {c.path for c in chunk_repo(tmp_path)}
    assert paths == {"real.py"}


# ----------------------------------------------------------------- embedder


@needs_rag
def test_index_and_search_round_trip(tmp_path):
    """Build a tiny index and check the obvious query comes back first."""
    from flakeguard.retrieval.embed import build_index, search

    count = build_index(SAMPLE, tmp_path / "chroma", repo="navsample", sha="test")
    assert count > 0

    hits = search("sleep for a random amount of time", tmp_path / "chroma",
                  repo="navsample", k=3)
    assert hits
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    assert any("slow_job" in h.text for h in hits), [h.path for h in hits]


# ------------------------------------------------- chroma name constraints


@pytest.mark.parametrize(
    "repo,expected",
    [
        ("cachetools", "cachetools"),
        ("ct", "ct-idx"),            # Chroma rejects names under 3 characters
        ("tkem/cachetools", "tkem-cachetools"),
        ("_weird_", "weird"),
        ("", "repo"),
    ],
)
def test_collection_name_is_chroma_legal(repo, expected):
    """Found by running the smoke test with a two-letter repo label."""
    from flakeguard.retrieval.embed import collection_name

    got = collection_name(repo)
    assert got == expected
    assert 3 <= len(got) <= 512
    assert got[0].isalnum() and got[-1].isalnum()
    assert all(c.isalnum() or c in "._-" for c in got)
