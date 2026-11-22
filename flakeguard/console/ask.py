"""Answering a question about a finding from the code, with file:line citations (BE-5).

It matches the words of the question against identifiers only (see docs/DECISIONS.md M2-8). When
nothing matches, the answer says so: ``chunks`` is 0 and there is no text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from flakeguard.console import models as m

STOPWORDS = {
    "the", "and", "why", "what", "how", "does", "did", "this", "that", "with", "from", "are", "was",
    "for", "has", "have", "can", "not", "its", "test", "tests", "fail", "fails", "failing", "when",
    "which", "where", "who", "should", "would", "could", "about", "into", "than", "then", "there",
}
_indexes: dict[str, Any] = {}


def clear_indexes() -> None:
    _indexes.clear()


def _tokens(question: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", question.replace("_", " "))
    return {w.lower() for w in words if len(w) >= 3 and w.lower() not in STOPWORDS}


def _identifier_parts(*names: str) -> set[str]:
    parts: set[str] = set()
    for name in names:
        parts.update(p.lower() for p in re.findall(r"[A-Za-z][A-Za-z0-9]*", name.replace("_", " ")))
    return parts


def answer_question(repo: Path, finding: m.Finding, question: str) -> m.AskAnswer:
    from flakeguard.rag.index import CodebaseIndexer

    key = str(repo)
    if key not in _indexes:
        idx = CodebaseIndexer(repo)
        idx.index()
        _indexes[key] = idx
    tokens = _tokens(question)
    scored = []
    for chunk in _indexes[key].chunks:
        if chunk.kind == "ci_event":
            continue
        parts = _identifier_parts(chunk.name, Path(chunk.file).stem, *chunk.reads, *chunk.writes)
        hits = tokens & parts
        if hits:
            scored.append((len(hits), chunk))
    scored.sort(key=lambda x: (-x[0], x[1].file, x[1].line_start))
    top = [c for _, c in scored[:5]]
    if not top:
        return m.AskAnswer(text="", citations=[], chunks=0)
    cites = [m.AskCitation(label=f"{c.file}:{c.line_start}", file=c.file, line=c.line_start) for c in top]
    names = ", ".join(f"{c.name} ({c.file}:{c.line_start})" for c in top)
    text = f"Code that matches your question: {names}. What the scan found for {finding.test}: {finding.why}"
    return m.AskAnswer(text=text, citations=cites, chunks=len(top))
