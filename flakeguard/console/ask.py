"""Answering a question about a finding from the code, with file:line citations (BE-5).

The search is scoped to the selected finding (docs/DECISIONS.md M2-8): the code of the finding's own test,
its polluter, the shared value and the code that reads or writes it is always a candidate, together with any code
whose identifiers appear in the question. A question that relates to neither the code nor the finding gets no
answer: ``chunks`` is 0 and there is no text. This is not the retrieval used in the RQ4 ablation.
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


def _finding_vocabulary(finding: m.Finding) -> set[str]:
    """Words the finding itself uses, so that "why is this order-dependent?" counts as a question about it."""
    texts = [finding.test, finding.subtype or "", finding.summaryLine, finding.why, finding.did, finding.limits,
             *finding.evidence, *[c.text for c in finding.lives]]
    return _tokens(" ".join(texts))


def _scope(finding: m.Finding) -> tuple[set[str], str | None]:
    """Names of the finding's own tests (victim, polluter) and its shared value, read from the finding."""
    names = {finding.test}
    for c in finding.lives:
        if c.tone == "write" and c.text.startswith("written by "):
            names.add(c.text.removeprefix("written by "))
    for snippet in (finding.writer, finding.reader):
        if snippet:
            names.update(re.findall(r"def (\w+)\(", " ".join(line.t for line in snippet.lines)))
    state = next((c.text.removeprefix("reads ") for c in finding.lives if c.tone == "read" and c.text.startswith("reads ")), None)
    return names, state


def answer_question(repo: Path, finding: m.Finding, question: str) -> m.AskAnswer:
    from flakeguard.rag.index import CodebaseIndexer

    key = str(repo)
    if key not in _indexes:
        idx = CodebaseIndexer(repo)
        idx.index()
        _indexes[key] = idx
    chunks = [c for c in _indexes[key].chunks if c.kind != "ci_event"]
    tokens = _tokens(question)
    names, state = _scope(finding)
    scope_files = {s.file for s in (finding.writer, finding.reader) if s} | {finding.file}

    def question_hits(chunk) -> int:
        return len(tokens & _identifier_parts(chunk.name, Path(chunk.file).stem, *chunk.reads, *chunk.writes))

    related = bool(tokens & _finding_vocabulary(finding)) or any(question_hits(c) for c in chunks)
    if not related:
        return m.AskAnswer(text="", citations=[], chunks=0)

    scored = []
    for chunk in chunks:
        in_scope = chunk.name in names or (state is not None and (chunk.name == state or state in chunk.reads or state in chunk.writes))
        score = question_hits(chunk) + (2 if in_scope else 0) + (1 if in_scope and chunk.file in scope_files else 0)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda x: (-x[0], x[1].file, x[1].line_start))
    top = [c for _, c in scored[:5]]
    if not top:
        return m.AskAnswer(text="", citations=[], chunks=0)
    cites = [m.AskCitation(label=f"{c.file}:{c.line_start}", file=c.file, line=c.line_start) for c in top]
    names_text = ", ".join(f"{c.name} ({c.file}:{c.line_start})" for c in top)
    lead = "Code that matches your question and this finding" if any(question_hits(c) for c in top) else "Code behind this finding"
    text = f"{lead}: {names_text}. What the scan found for {finding.test}: {finding.why}"
    return m.AskAnswer(text=text, citations=cites, chunks=len(top))
