"""Pydantic mirror of ``console/src/types.ts``.

Field names are the TypeScript names (camelCase) on purpose, so the JSON the console
receives is exactly what ``types.ts`` declares. ``tests/test_api_contract.py`` checks this
against the TypeScript source, so a renamed field fails a test.

Nothing here may be invented: missing data is ``None`` (the console shows a dash).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_serializer


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _OptionalKeys(_Model):
    """Fields declared ``x?: T`` in TypeScript are absent in JSON, not ``null``."""

    @model_serializer(mode="wrap")
    def _drop_none(self, handler: Any) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}


Verdict = Literal["flaky", "real", "unknown"]
NodeStatus = Literal["flaky", "real", "unknown", "polluter", "clean"]
EvidenceTier = Literal["observed", "reproduced", "intervention-confirmed"]
Severity = Literal["blocking", "suggestion", "needs-evidence"]
StageState = Literal["done", "running", "pending", "failed"]
RunCell = Literal["pass", "fail", "none"]
RunMode = Literal["actions", "local", "recorded"]
LabelType = Literal["injected", "natural", "planted"]
ScreenState = Literal[
    "first-run",
    "actions-unavailable",
    "docker-not-running",
    "scan-incomplete",
    "recorded-run",
    "no-findings",
    "quarantine-refused",
    "post-merge",
    "ask-nothing",
]


class Stage(_Model):
    id: str
    name: str
    detail: str
    tool: str
    time: str | None
    state: StageState


class MatrixRow(_Model):
    label: str
    summary: str
    cells: list[RunCell]


class PrInfo(_Model):
    number: int
    title: str
    state: Literal["open", "merged", "closed"]
    checkState: str
    postMergeState: str
    prUrl: str | None
    runUrl: str | None


class Current(_Model):
    test: str
    condition: str


class Counters(_Model):
    runsDone: int
    runsTotal: int
    failures: int
    flagged: int


class Notice(_OptionalKeys):
    kind: ScreenState
    detail: str | None = None


class SourceRef(_Model):
    """A GitHub repository and the commit that was scanned, so file:line references can link to it."""

    repo: str
    ref: str


class RunStatus(_Model):
    id: str
    target: str
    mode: RunMode
    status: Literal["idle", "running", "complete", "failed"]
    pr: PrInfo | None
    stages: list[Stage]
    current: Current | None
    counters: Counters
    matrix: list[MatrixRow]
    notice: Notice | None
    source: SourceRef | None = None


class CodeLine(_OptionalKeys):
    n: int
    t: str
    note: str | None = None
    hot: bool | None = None


class CodeSnippet(_Model):
    file: str
    role: Literal["the polluter", "the victim", "the risky spot", "the test FlakeGuard wrote"]
    lines: list[CodeLine]


class LivesChip(_Model):
    text: str
    tone: Literal["plain", "read", "write"]


class FixPreview(_Model):
    summary: str
    file: str
    diff: list[str]
    checked: str
    doesNotProve: str


class Quarantine(_Model):
    allowed: bool
    reason: str | None


class Finding(_Model):
    id: str
    test: str
    file: str
    line: int
    verdict: Verdict
    subtype: str | None
    severity: Severity
    evidenceTier: EvidenceTier
    summaryLine: str
    why: str
    evidence: list[str]
    lives: list[LivesChip]
    did: str
    limits: str
    writer: CodeSnippet | None
    reader: CodeSnippet | None
    repro: str | None
    fix: FixPreview | None
    quarantine: Quarantine


class TreeNode(_Model):
    id: str
    kind: Literal["repo", "file", "test"]
    name: str
    path: str | None
    status: NodeStatus
    label: str
    faults: int
    findingId: str | None
    children: list[TreeNode]


class SharedState(_Model):
    id: str
    name: str
    path: str
    note: str
    writers: list[str]
    readers: list[str]


class TreeData(_Model):
    root: TreeNode
    sharedState: list[SharedState]


class ResultsTable(_Model):
    columns: list[str]
    rows: list[list[str | None]]


class Provenance(_Model):
    dataset: str | None
    labelType: LabelType
    n: int | None
    command: str | None
    date: str | None
    commit: str | None


class TableWithProvenance(_Model):
    table: ResultsTable
    provenance: Provenance


class RunsToDecision(_Model):
    fixed: str | None
    adaptive: str | None


class TriageNumbers(_Model):
    redPrsCleared: str | None
    realQuarantined: str | None


class ResultsData(_Model):
    ablation: TableWithProvenance
    baselines: TableWithProvenance
    runsToDecision: RunsToDecision
    triage: TriageNumbers
    triageTable: TableWithProvenance | None = None  # RQ3, a simulation; None until a run exists
    notes: list[str] = []  # limitations that belong next to the figures
    status: str = "not run"  # "run" when a recorded run exists for this label type


class RiskySpot(_Model):
    where: str
    what: str
    why: str
    test: str | None


class NoTestsStep(_Model):
    name: str
    state: StageState


class NoTestsExample(_Model):
    risky: CodeSnippet
    test: CodeSnippet


class NoTestsCheck(_Model):
    label: str
    ok: bool | None


class DroppedTest(_Model):
    test: str
    where: str
    reason: str
    byUser: bool = False


class NoTestsPlan(_Model):
    repo: str
    steps: list[NoTestsStep]
    spots: list[RiskySpot]
    example: NoTestsExample | None
    checks: list[NoTestsCheck]
    dropped: list[DroppedTest] = []  # a test that failed a check, or that the person dropped, with the reason (AC-N2)
    notes: list[str] = []
    canOpenPr: bool = False  # the Open PR action is not enabled in this build


class StartRunRequest(_Model):
    target: str
    source: Literal["pull-request", "repo", "sample"]
    runs: int
    docker: bool


class AskCitation(_Model):
    label: str
    file: str
    line: int


class AskAnswer(_Model):
    text: str
    citations: list[AskCitation]
    chunks: int


TreeNode.model_rebuild()
