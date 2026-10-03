"""Split a repository into one chunk per function or class.

This is the input side of the retriever: before anything can be embedded it
has to be cut into pieces that are worth retrieving. One function or class per
chunk, with the path and line range kept as metadata, which is what the
`Chunk` contract in `flakeguard.contracts` already asks for.

Deliberately has no dependency on chromadb or sentence-transformers, so the
chunking can be unit tested in CI without pulling in PyTorch.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from flakeguard.contracts import Chunk

# Directories that are never worth indexing.
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", "build", "dist"}
)

# A one-line function carries no retrievable meaning on its own.
MIN_LINES = 2


def iter_python_files(repo_root: Path) -> Iterator[Path]:
    for path in sorted(repo_root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def chunk_file(path: Path, repo_root: Path, repo: str, sha: str) -> list[Chunk]:
    """One chunk per top-level function, class, and method."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []

    rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    lines = source.splitlines()
    out: list[Chunk] = []

    def add(node: ast.AST, kind: str) -> None:
        start = node.lineno  # type: ignore[attr-defined]
        end = getattr(node, "end_lineno", None) or start
        if end - start + 1 < MIN_LINES:
            return
        text = "\n".join(lines[start - 1 : end])
        out.append(
            Chunk(
                chunk_id=f"{repo}@{sha}:{rel}:{start}-{end}",
                path=rel,
                start_line=start,
                end_line=end,
                kind=kind,
                text=text,
            )
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node, "test" if node.name.startswith("test") else "function")
        elif isinstance(node, ast.ClassDef):
            add(node, "class")
            # Methods are indexed separately: a 200-line class is one blob to
            # an embedding model, and the useful answer is usually one method.
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(child, "test" if child.name.startswith("test") else "function")
    return out


def chunk_repo(
    repo_root: str | Path, repo: str = "repo", sha: str = "local"
) -> list[Chunk]:
    root = Path(repo_root).resolve()
    chunks: list[Chunk] = []
    for path in iter_python_files(root):
        chunks.extend(chunk_file(path, root, repo, sha))
    return chunks
