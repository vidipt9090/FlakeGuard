# flakeguard/contracts.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Chunk:
    chunk_id: str        # "<repo>@<sha>:<path>:<start>-<end>"
    path: str
    start_line: int
    end_line: int
    kind: str            # "function" | "class" | "test" | "fixture" | "log"
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class NavResult:
    test_id: str                                   # "tests/test_x.py::TestA::test_b"
    code_under_test: list[Chunk] = field(default_factory=list)
    fixtures: list[Chunk] = field(default_factory=list)
    shared_state: list[Chunk] = field(default_factory=list)  # module-level mutable globals touched
    smells: list[str] = field(default_factory=list)          # e.g. "time.sleep", "random.random"


class LLMProvider(Protocol):
    def generate(self, prompt: str, schema: dict) -> dict: ...


class Retriever(Protocol):
    def retrieve(self, test_id: str, k: int) -> list[Chunk]: ...


class Navigator(Protocol):
    def related(self, test_id: str) -> NavResult: ...
