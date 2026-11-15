"""Codebase and CI history indexing for FlakeGuard RAG."""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CodeChunk:
    chunk_id: str
    file: str
    line_start: int
    line_end: int
    name: str
    kind: str  # "test", "function", "class", "global_state", "ci_event"
    content: str
    reads: list[str]
    writes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodebaseIndexer:
    """Parses repository Python files into AST-backed code chunks and indexes CI logs."""

    def __init__(self, repo_path: Path | str) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.chunks: list[CodeChunk] = []

    def index(self, max_files: int = 500) -> list[CodeChunk]:
        """Index all python files and recent CI logs in repo_path."""
        self.chunks = []
        py_files = sorted(self.repo_path.glob("**/*.py"))
        py_files = [
            f for f in py_files
            if not any(part.startswith(".") or part in {"__pycache__", "venv", ".venv", "build", "dist"}
                       for part in f.parts)
        ][:max_files]

        for file_path in py_files:
            rel_file = str(file_path.relative_to(self.repo_path)).replace("\\", "/")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(file_path))
            except Exception:
                continue

            lines = content.splitlines()

            # Global assignments (shared mutable state)
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    start = getattr(node, "lineno", 1)
                    end = getattr(node, "end_lineno", start)
                    snippet = "\n".join(lines[start - 1:end])
                    targets = []
                    if isinstance(node, ast.Assign):
                        for t in node.targets:
                            if isinstance(t, ast.Name):
                                targets.append(t.id)
                    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        targets.append(node.target.id)

                    for target in targets:
                        self.chunks.append(
                            CodeChunk(
                                chunk_id=f"{rel_file}::{target}:{start}",
                                file=rel_file,
                                line_start=start,
                                line_end=end,
                                name=target,
                                kind="global_state",
                                content=snippet,
                                reads=[],
                                writes=[target],
                            )
                        )

            # Functions and methods
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    snippet = "\n".join(lines[start - 1:end])
                    is_test = node.name.startswith("test_") or "test" in rel_file.lower()

                    # Find read/write references
                    reads: set[str] = set()
                    writes: set[str] = set()
                    for child in ast.walk(node):
                        if isinstance(child, ast.Name):
                            if isinstance(child.ctx, ast.Load):
                                reads.add(child.id)
                            elif isinstance(child.ctx, (ast.Store, ast.Del)):
                                writes.add(child.id)
                        elif isinstance(child, ast.Global):
                            writes.update(child.names)

                    self.chunks.append(
                        CodeChunk(
                            chunk_id=f"{rel_file}::{node.name}:{start}",
                            file=rel_file,
                            line_start=start,
                            line_end=end,
                            name=node.name,
                            kind="test" if is_test else "function",
                            content=snippet,
                            reads=sorted(reads),
                            writes=sorted(writes),
                        )
                    )

        # Index CI event history if present
        results_dir = self.repo_path / "results"
        if results_dir.is_dir():
            for event_file in results_dir.glob("**/*.jsonl"):
                try:
                    for line_idx, line in enumerate(event_file.read_text(encoding="utf-8").splitlines()[:50]):
                        if not line.strip():
                            continue
                        ev = json.loads(line)
                        test_id = ev.get("test_id") or ""
                        self.chunks.append(
                            CodeChunk(
                                chunk_id=f"{event_file.name}::event_{line_idx}",
                                file=str(event_file.relative_to(self.repo_path)).replace("\\", "/"),
                                line_start=line_idx + 1,
                                line_end=line_idx + 1,
                                name=test_id or ev.get("type", "event"),
                                kind="ci_event",
                                content=json.dumps(ev),
                                reads=[test_id] if test_id else [],
                                writes=[],
                            )
                        )
                except Exception:
                    pass

        return self.chunks

    def save(self, cache_file: Path | str) -> None:
        path = Path(cache_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self.chunks]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, cache_file: Path | str) -> list[CodeChunk]:
        path = Path(cache_file)
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        self.chunks = [CodeChunk(**item) for item in data]
        return self.chunks

