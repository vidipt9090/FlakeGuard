"""Instrumentation for the navigator: what the AST walk saw, what jedi resolved.

The navigator's answer (a ``NavResult``) says *what* code a failing test
reaches. It says nothing about *how* that answer was reached, which is the
part a reviewer has to trust: how many names the AST walk pulled out of the
test body, which of them jedi could resolve, how deep the expansion went
before it stopped finding anything new, and where the time went.

A ``NavTrace`` records that. Every step the navigator takes appends one
``TraceEvent``, in order, with the hop depth it happened at. The dashboard
replays those events; the CI pipeline exports their summary as a metric.

Cost when off is one method call returning a shared no-op, so the navigator
carries the instrumentation unconditionally and nothing pays for it unless a
trace is passed in.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

# Phases, in the order the navigator runs them. The dashboard colours and
# groups by this, so a new phase must be added here to be rendered.
PHASES: tuple[str, ...] = (
    "locate",        # test id -> file, class, function
    "inherit",       # method not in the named class: walk base classes
    "ast_walk",      # collect candidate names out of the test body
    "jedi_goto",     # name -> definition
    "jedi_infer",    # expression -> type of its value
    "fixture",       # test arguments -> conftest chain
    "concrete",      # self.x -> the override in the class the id names
    "expand",        # a definition's bases, decorators, defaults, callees
    "shared_state",  # module-level mutable values in reachable files
    "smell",         # flakiness pattern scan
)

# Which resolver produced an event, for the "who found this" column.
VIA_AST = "ast"
VIA_JEDI = "jedi"


@dataclass(frozen=True)
class TraceEvent:
    """One step of navigation.

    ``depth`` is hop distance from the test: 0 for the test body itself, 1
    for a definition the test names directly, 2 for that definition's base
    class, and so on. It is the axis the "searching in depth" view plots.
    """

    seq: int
    phase: str
    op: str                      # short verb: "parse", "walk", "goto", "infer"
    label: str                   # the subject, e.g. "shop.total" or "TTLCache"
    depth: int = 0
    via: str = VIA_AST
    detail: str = ""
    path: str = ""
    line: int = 0
    end_line: int = 0
    weight: float = 0.0
    results: int = 0             # definitions the step returned
    kept: int = 0                # of those, how many survived filtering
    duration_ms: float = 0.0
    ok: bool = True
    # Chunk keys ("<path>:<start_line>") this step put into the result. This
    # is what lets a viewer replay the trace and grow the tree in step with
    # it: without it, "which step found this node" can only be guessed at.
    produced: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class _Step:
    """Handle for an in-flight step, so a caller can report what it found."""

    __slots__ = ("results", "kept", "detail", "ok", "label", "produced")

    def __init__(self, label: str = "") -> None:
        self.results = 0
        self.kept = 0
        self.detail = ""
        self.ok = True
        self.label = label
        # Chunk keys this step added to the result, so a replay can grow the
        # tree in step with the trace.
        self.produced: list[str] = []


class _NullStep(_Step):
    """A step that discards writes and reads back as empty.

    The class attributes shadow the parent's ``__slots__`` descriptors, so
    ``s.results += 1`` reads 0 and throws the write away. Callers that
    accumulate into a step therefore work unchanged when tracing is off.
    """

    results = 0
    kept = 0
    detail = ""
    ok = True
    label = ""
    produced: list[str] = []

    def __setattr__(self, name: str, value: object) -> None:
        pass


_NULL_STEP = _NullStep()


class NavTrace:
    """An ordered log of navigation steps."""

    def __init__(self, test_id: str = "", repo: str = "", sha: str = "") -> None:
        self.test_id = test_id
        self.repo = repo
        self.sha = sha
        self.events: list[TraceEvent] = []
        self.started = time.perf_counter()
        self._seq = 0

    # ------------------------------------------------------------- recording

    @property
    def enabled(self) -> bool:
        return True

    def record(self, phase: str, op: str, label: str, **kw) -> TraceEvent:
        """Append a step that has already happened."""
        self._seq += 1
        event = TraceEvent(seq=self._seq, phase=phase, op=op, label=label, **kw)
        self.events.append(event)
        return event

    def step(self, phase: str, op: str, label: str, **kw) -> _TimedStep:
        """Context manager that times a step and records it on exit.

        Used as::

            with trace.step("jedi_goto", "goto", name, depth=1) as s:
                s.results = len(found)
        """
        return _TimedStep(self, phase, op, label, kw)

    # -------------------------------------------------------------- analysis

    def summary(self) -> dict:
        """Counters the CSV export and the dashboard header both read."""
        by_phase: dict[str, int] = {}
        ms_by_phase: dict[str, float] = {}
        for event in self.events:
            by_phase[event.phase] = by_phase.get(event.phase, 0) + 1
            ms_by_phase[event.phase] = round(
                ms_by_phase.get(event.phase, 0.0) + event.duration_ms, 3
            )
        calls = by_phase.get("jedi_goto", 0) + by_phase.get("jedi_infer", 0)
        hits = sum(
            1
            for e in self.events
            if e.phase in {"jedi_goto", "jedi_infer"} and e.results
        )
        return {
            "test_id": self.test_id,
            "events": len(self.events),
            "max_depth": max((e.depth for e in self.events), default=0),
            "ast_names": by_phase.get("ast_walk", 0),
            "jedi_goto_calls": by_phase.get("jedi_goto", 0),
            "jedi_infer_calls": by_phase.get("jedi_infer", 0),
            "jedi_calls": calls,
            "jedi_hits": hits,
            "jedi_hit_rate": round(hits / calls, 4) if calls else 0.0,
            "expand_rounds": len({e.depth for e in self.events if e.phase == "expand"}),
            "events_by_phase": by_phase,
            "ms_by_phase": ms_by_phase,
            "total_ms": round((time.perf_counter() - self.started) * 1000, 3),
        }

    def by_depth(self) -> dict[int, int]:
        """How many steps happened at each hop depth."""
        out: dict[int, int] = {}
        for event in self.events:
            out[event.depth] = out.get(event.depth, 0) + 1
        return dict(sorted(out.items()))

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "repo": self.repo,
            "sha": self.sha,
            "summary": self.summary(),
            "by_depth": {str(k): v for k, v in self.by_depth().items()},
            "events": [e.to_dict() for e in self.events],
        }


class _TimedStep:
    """Times its body and records one event when it closes."""

    __slots__ = ("_trace", "_phase", "_op", "_label", "_kw", "_start", "step")

    def __init__(self, trace: NavTrace, phase: str, op: str, label: str, kw: dict) -> None:
        self._trace = trace
        self._phase = phase
        self._op = op
        self._label = label
        self._kw = kw
        self._start = 0.0
        self.step = _Step(label)

    def __enter__(self) -> _Step:
        self._start = time.perf_counter()
        return self.step

    def __exit__(self, exc_type, exc, tb) -> bool:
        kw = dict(self._kw)
        kw["duration_ms"] = round((time.perf_counter() - self._start) * 1000, 3)
        kw["results"] = self.step.results
        kw["kept"] = self.step.kept
        kw["produced"] = list(self.step.produced)
        kw["ok"] = self.step.ok and exc_type is None
        if self.step.detail:
            kw["detail"] = self.step.detail
        self._trace.record(self._phase, self._op, self.step.label or self._label, **kw)
        return False  # never swallow


class NullTrace(NavTrace):
    """Records nothing. The default, so instrumentation is free when unused."""

    @property
    def enabled(self) -> bool:
        return False

    def record(self, phase: str, op: str, label: str, **kw) -> TraceEvent:
        return _NULL_EVENT

    def step(self, phase: str, op: str, label: str, **kw) -> _TimedStep:
        return _NULL_TIMED


_NULL_EVENT = TraceEvent(seq=0, phase="", op="", label="")


class _NullTimed(_TimedStep):
    """Enter and exit with no clock and no append."""

    def __init__(self) -> None:
        self.step = _NULL_STEP

    def __enter__(self) -> _Step:
        return _NULL_STEP

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


_NULL_TIMED = _NullTimed()
NULL_TRACE = NullTrace()


@dataclass
class Provenance:
    """How one chunk entered the result: the edge that reached it.

    The navigator scores chunks but does not otherwise say where each came
    from. The knowledge tree needs exactly that: which edge, from which
    parent, at what depth. One ``Provenance`` per chunk key answers it.
    """

    edge: str                    # calls | infers | fixture-builds | overrides | expands
    via: str = VIA_JEDI
    depth: int = 1
    seq: int = 0
    weight: float = 1.0
    parent: str = ""             # "<path>:<start_line>" of the chunk we came from
    detail: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
