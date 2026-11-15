from pathlib import Path

from flakeguard.rag.index import CodebaseIndexer
from flakeguard.rag.qa import RepoQAEngine


def test_rag_index_and_citations(tmp_path: Path):
    # Create sample target codebase
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    orders_py = src_dir / "orders.py"
    orders_py.write_text(
        "GLOBAL_REGISTRY = []\n\n"
        "def register_order(order_id):\n"
        "    GLOBAL_REGISTRY.append(order_id)\n",
        encoding="utf-8"
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_py = tests_dir / "test_orders.py"
    test_py.write_text(
        "from src.orders import GLOBAL_REGISTRY, register_order\n\n"
        "def test_batch_polluter():\n"
        "    register_order(100)\n"
        "    assert len(GLOBAL_REGISTRY) == 1\n\n"
        "def test_victim():\n"
        "    assert len(GLOBAL_REGISTRY) == 0\n",
        encoding="utf-8"
    )

    indexer = CodebaseIndexer(tmp_path)
    chunks = indexer.index()
    assert len(chunks) >= 3

    engine = RepoQAEngine(tmp_path, indexer=indexer)

    # 1. Test question answering with citations
    res = engine.ask("Why does test_victim fail due to polluter?")
    assert res["status"] == "answered"
    assert len(res["citations"]) > 0
    # Must cite file:line
    for cite in res["citations"]:
        assert ":" in cite
        parts = cite.split(":")
        assert len(parts) == 2
        assert parts[1].isdigit()

    # 2. Test refusal when retrieval is empty
    res_empty = engine.ask("quantum_superposition_xyz_unrelated_12345")
    assert res_empty["status"] == "refused"
    assert "Refusal" in res_empty["answer"]
    assert len(res_empty["citations"]) == 0
