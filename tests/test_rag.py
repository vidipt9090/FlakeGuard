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


def test_langchain_ast_retriever(tmp_path: Path):
    from flakeguard.llm.prompt_v4 import build_prompt_v4
    from flakeguard.rag.langchain_retriever import ASTCodebaseRetriever
    from flakeguard.stats.bayesian import BayesianFailureRate

    src_file = tmp_path / "app.py"
    src_file.write_text(
        "SHARED_CACHE = {}\n\n"
        "def compute_val(k, v):\n"
        "    SHARED_CACHE[k] = v\n"
        "    return v * 2\n",
        encoding="utf-8"
    )

    retriever = ASTCodebaseRetriever(repo_path=tmp_path, top_k=3)
    docs = retriever.invoke("SHARED_CACHE")
    assert len(docs) > 0
    assert docs[0].metadata["file"] == "app.py"
    assert "app.py:" in docs[0].metadata["citation"]
    assert "compute_val" in docs[0].page_content or "SHARED_CACHE" in docs[0].page_content

    # Q&A via LangChain retriever
    ans = retriever.answer_question("How is SHARED_CACHE modified?")
    assert ans["status"] == "answered"
    assert len(ans["citations"]) > 0
    assert "app.py:" in ans["citations"][0]

    # Refusal on empty query
    empty_ans = retriever.answer_question("totally_nonexistent_token_99999")
    assert empty_ans["status"] == "refused"

    # Integration with build_prompt_v4
    prompt = build_prompt_v4(
        test_id="test_cache",
        test_body="assert False",
        log_excerpt="AssertionError",
        b_rate=BayesianFailureRate(test_id="test_cache", runs=10, failures=3),
        retrieved_chunks=[
            {"citation": docs[0].metadata["citation"], "name": docs[0].metadata["name"], "content": docs[0].page_content}
        ],
    )
    assert "CODE THE MODEL READ" in prompt
    assert "app.py:" in prompt

