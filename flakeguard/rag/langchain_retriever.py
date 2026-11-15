"""LangChain BaseRetriever and LCEL Q&A chain over AST code chunks for FlakeGuard."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from flakeguard.rag.index import CodebaseIndexer, CodeChunk


class ASTCodebaseRetriever(BaseRetriever):
    """LangChain BaseRetriever implementation indexing and retrieving AST code chunks."""

    repo_path: str = Field(description="Root directory of the repository")
    top_k: int = Field(default=5, description="Number of documents to retrieve")
    indexer: Any = Field(default=None, description="Underlying CodebaseIndexer")

    def __init__(self, repo_path: Path | str, top_k: int = 5, **kwargs: Any) -> None:
        path = Path(repo_path).resolve()
        idx = CodebaseIndexer(path)
        if not idx.chunks:
            idx.index()
        super().__init__(repo_path=str(path), top_k=top_k, indexer=idx, **kwargs)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun | None = None
    ) -> list[Document]:
        """Retrieve AST code chunks matching tokens, symbols, reads/writes, or test names."""
        if not self.indexer or not self.indexer.chunks:
            return []

        tokens = set(re.findall(r"[A-Za-z0-9_]+", query.lower()))
        if not tokens:
            return []

        scored: list[tuple[float, CodeChunk]] = []
        for chunk in self.indexer.chunks:
            score = 0.0
            name_lower = chunk.name.lower()
            file_lower = chunk.file.lower()
            content_lower = chunk.content.lower()

            for t in tokens:
                if t == name_lower:
                    score += 5.0
                elif t in name_lower:
                    score += 3.0
                if t in file_lower:
                    score += 1.5
                if t in content_lower:
                    score += 0.5
                if any(t == r.lower() for r in chunk.reads):
                    score += 2.0
                if any(t == w.lower() for w in chunk.writes):
                    score += 2.5

            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self.top_k]

        docs: list[Document] = []
        for s, ch in top:
            metadata = {
                "chunk_id": ch.chunk_id,
                "file": ch.file,
                "line_start": ch.line_start,
                "line_end": ch.line_end,
                "name": ch.name,
                "kind": ch.kind,
                "reads": ch.reads,
                "writes": ch.writes,
                "citation": f"{ch.file}:{ch.line_start}",
                "score": s,
            }
            docs.append(Document(page_content=ch.content, metadata=metadata))
        return docs

    def answer_question(self, query: str, llm_provider: Any = None) -> dict[str, Any]:
        """LangChain LCEL Q&A chain over retrieved AST documents with strict file:line citations."""
        docs = self.invoke(query)
        if not docs:
            return {
                "status": "refused",
                "answer": "Refusal: No relevant code chunks found in repository AST index matching the query.",
                "citations": [],
                "documents": [],
            }

        citations = [doc.metadata["citation"] for doc in docs]
        unique_citations = list(dict.fromkeys(citations))

        # Build context from documents
        context_blocks: list[str] = []
        for doc in docs:
            m = doc.metadata
            context_blocks.append(
                f"### {m['kind'].upper()}: {m['name']} ({m['citation']}-{m['line_end']})\n"
                f"Reads: {m['reads']}, Writes: {m['writes']}\n"
                f"```python\n{doc.page_content}\n```"
            )
        context_str = "\n\n".join(context_blocks)

        if llm_provider and hasattr(llm_provider, "generate"):
            prompt = (
                "You are FlakeGuard's AST Code Q&A assistant. Answer the developer's question "
                "using ONLY the retrieved code chunks below. You MUST cite specific file:line for every claim.\n\n"
                f"Retrieved Code Context:\n{context_str}\n\n"
                f"Question: {query}\n\nAnswer:"
            )
            raw_answer = llm_provider.generate(prompt)
            answer = raw_answer if isinstance(raw_answer, str) else str(raw_answer)
        else:
            # Deterministic, reliable synthesis based on AST evidence
            first = docs[0].metadata
            answer = (
                f"Based on repository AST analysis, `{first['name']}` at {first['citation']} "
                f"({first['kind']}) is directly relevant. "
            )
            if first["writes"]:
                answer += f"It mutates shared state variables: {', '.join(first['writes'])}. "
            if first["reads"]:
                answer += f"It accesses state variables: {', '.join(first['reads'])}. "
            if len(unique_citations) > 1:
                answer += f"Related interacting symbols identified at: {', '.join(unique_citations[1:])}."

        return {
            "status": "answered",
            "answer": answer,
            "citations": unique_citations,
            "documents": [
                {
                    "chunk_id": d.metadata["chunk_id"],
                    "citation": d.metadata["citation"],
                    "name": d.metadata["name"],
                    "content": d.page_content,
                }
                for d in docs
            ],
        }
