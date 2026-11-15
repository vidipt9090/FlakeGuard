# flakeguard/contracts.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class EvidenceTier(str, Enum):
    OBSERVED = "observed"
    REPRODUCED = "reproduced"
    INTERVENTION_CONFIRMED = "intervention-confirmed"


@dataclass(frozen=True)
class InterventionRecord:
    kind: str  # e.g. "pin_seed", "vary_tz", "freeze_clock", "delay", "cpu_stress"
    parameters: dict[str, Any] = field(default_factory=dict)
    flipped: bool = False  # True if outcome changed compared to baseline failure
    outcome: str = "UNKNOWN"  # "PASS" | "FAIL" | "ERROR"
    details: str = ""


@dataclass(frozen=True)
class EvidenceReport:
    test_id: str
    tier: EvidenceTier
    category: str  # "order_dependent" | "time_dependent" | "concurrency" | "randomness" | "unknown"
    polluter_test_id: str | None = None
    interventions: list[InterventionRecord] = field(default_factory=list)
    shared_state_reads: list[str] = field(default_factory=list)
    shared_state_writes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # "<repo>@<sha>:<path>:<start>-<end>"
    path: str
    start_line: int
    end_line: int
    kind: str  # "function" | "class" | "test" | "fixture" | "log"
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class NavResult:
    test_id: str  # "tests/test_x.py::TestA::test_b"
    code_under_test: list[Chunk] = field(default_factory=list)
    fixtures: list[Chunk] = field(default_factory=list)
    shared_state: list[Chunk] = field(default_factory=list)  # module-level mutable globals touched
    smells: list[str] = field(default_factory=list)  # e.g. "time.sleep", "random.random"


class LLMProvider(Protocol):
    def generate(self, prompt: str, schema: dict) -> dict: ...


class Retriever(Protocol):
    def retrieve(self, test_id: str, k: int) -> list[Chunk]: ...


class Navigator(Protocol):
    def related(self, test_id: str) -> NavResult: ...

