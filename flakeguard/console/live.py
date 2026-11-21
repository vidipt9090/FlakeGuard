"""Live progress for a scan: ``progress.json`` (a ``RunStatus``), written atomically.

``LiveRun`` is the observer the perturbation matrix calls before and after every individual
run. After each call it rewrites ``progress.json`` (write a temp file, then rename), so a
reader never sees half a file. Every number comes from the runs that have actually finished.

Stage mapping: the matrix has six kinds of run but the console shows nine stages.
``reversed`` runs belong to the Shuffled stage; ``repeated`` and ``parallel`` runs belong to
the Isolated stage. The stage text says so with real counts.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from pathlib import Path

from flakeguard.console import models as m
from flakeguard.runner.matrix import SliceResult

MODE_LABELS = {
    "baseline": "Default order",
    "shuffled": "Shuffled order",
    "reversed": "Reversed order",
    "isolated": "Alone",
    "repeated": "Repeated",
    "parallel": "Parallel",
}
STAGE_OF_MODE = {
    "baseline": "baseline", "shuffled": "shuffled", "reversed": "shuffled",
    "isolated": "isolated", "repeated": "isolated", "parallel": "isolated",
}
STAGES = [
    ("checkout", "Checkout", "local path", "Preparing the target"),
    ("install", "Install", "not run", "Not run. A local scan uses this machine's Python environment."),
    ("baseline", "Baseline", "pytest", "Waiting to start"),
    ("shuffled", "Shuffled runs", "pytest, pytest-randomly", "Waiting to start"),
    ("isolated", "Isolated runs", "pytest", "Waiting to start"),
    ("bisection", "Bisection", "FlakeGuard evidence engine", "Waiting to start"),
    ("retrieval", "Retrieval", "AST + Jedi", "Waiting to start"),
    ("verdict", "Verdict", "FlakeGuard rules (no LLM)", "Waiting to start"),
    ("pr-comment", "PR comment", "not run", "Not run. A local scan does not post to GitHub."),
]
FAILED = ("FAIL", "ERROR")


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so that readers see the old file or the new one, never half."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):  # Windows refuses the rename while a reader has the file open
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def stopped_early(run: m.RunStatus, detail: str) -> m.RunStatus:
    """The same run, marked as not finished. No verdict is attached to a failed run."""
    stages = [
        s.model_copy(update={"state": "failed", "time": None}) if s.state == "running" else s
        for s in run.stages
    ]
    return run.model_copy(update={
        "status": "failed", "stages": stages, "current": None,
        "notice": m.Notice(kind="scan-incomplete", detail=detail),
    })


def runs_of(finished: list[SliceResult], mode: str) -> list[SliceResult]:
    return [r for r in finished if r.mode == mode]


def failing_tests(finished: list[SliceResult], modes: tuple[str, ...] | None = None) -> set[str]:
    return {
        o.test_id for r in finished if modes is None or r.mode in modes
        for o in r.outcomes if o.outcome in FAILED
    }


def focus_test(finished: list[SliceResult]) -> str | None:
    """The test the matrix follows: one that both passed and failed, else any failing test."""
    counts: dict[str, Counter] = {}
    for r in finished:
        for o in r.outcomes:
            counts.setdefault(o.test_id, Counter())["fail" if o.outcome in FAILED else "pass"] += 1
    mixed = [t for t, c in counts.items() if c["fail"] and c["pass"]]
    if mixed:
        return max(mixed, key=lambda t: (counts[t]["fail"], t))
    failing = sorted(t for t, c in counts.items() if c["fail"])
    return failing[0] if failing else None


def matrix_rows(finished: list[SliceResult], shuffled_n: int) -> list[m.MatrixRow]:
    """Baseline, Shuffled and Isolated rows for the followed test (the whole suite before one fails)."""
    focus = focus_test(finished)
    scope = focus.split("::")[-1] if focus else "whole suite"

    def result_of(r: SliceResult) -> str | None:
        if focus:
            if not any(o.test_id == focus for o in r.outcomes):
                return None
            return "fail" if any(o.test_id == focus and o.outcome in FAILED for o in r.outcomes) else "pass"
        return "fail" if any(o.outcome in FAILED for o in r.outcomes) else "pass"

    def cells_for(mode: str, expected: int) -> list[str]:
        rs = runs_of(finished, mode)
        if mode == "shuffled":
            # Seeds can finish out of order (parallel jobs), so a mark sits at its own run's position.
            cells = ["none"] * expected
            for r in rs:
                result = result_of(r)
                if result is not None and 1 <= r.iteration <= expected:
                    cells[r.iteration - 1] = result
            return cells
        cells = [c for c in (result_of(r) for r in rs) if c is not None]
        return cells + ["none"] * max(0, expected - len(cells))

    rows = []
    for label, mode, expected in (("Baseline", "baseline", 1), ("Shuffled", "shuffled", shuffled_n),
                                  ("Isolated", "isolated", 0)):
        cells = cells_for(mode, expected)
        done = [c for c in cells if c != "none"]
        failed = sum(1 for c in done if c == "fail")
        summary = (f"{scope}: {plural(len(done), 'run')} done, {len(done) - failed} passed, {failed} failed"
                   if done else f"{scope}: no runs yet")
        if mode == "shuffled" and runs_of(finished, "shuffled"):
            seeds = [r.seed for r in runs_of(finished, "shuffled") if r.seed is not None]
            if seeds:
                summary += f" (seeds {seeds[0]} to {seeds[-1]})" if len(seeds) > 1 else f" (seed {seeds[0]})"
        rows.append(m.MatrixRow(label=label, summary=summary, cells=cells))  # type: ignore[arg-type]
    return rows


class LiveRun:
    """Observer for ``PerturbationMatrix.run_matrix`` that keeps ``progress.json`` current."""

    def __init__(self, run_dir: Path, run_id: str, target: str, shuffled_n: int, seed_start: int) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "progress.json"
        self.run_id = run_id
        self.target = target
        self.shuffled_n = shuffled_n
        self.seed_start = seed_start
        self.stages = {
            sid: {"name": name, "tool": tool, "detail": detail, "state": "pending", "time": None, "t0": None}
            for sid, name, tool, detail in STAGES
        }
        self.finished: list[SliceResult] = []
        self.current: m.Current | None = None
        self.status = "running"
        self.notice: m.Notice | None = None
        self._set("checkout", "running", "Preparing the target")
        self.write()

    # ------------------------------------------------------------------ stages

    def _set(self, sid: str, state: str, detail: str | None = None) -> None:
        st = self.stages[sid]
        if state == "running" and st["t0"] is None:
            st["t0"] = time.perf_counter()
        if state in ("done", "failed") and st["t0"] is not None:
            elapsed = time.perf_counter() - st["t0"]
            st["time"] = "under 1 s" if elapsed < 1 else f"{round(elapsed)} s"
        st["state"] = state
        if detail is not None:
            st["detail"] = detail

    def phase(self, sid: str, state: str) -> None:
        """Called by the run builder around bisection, retrieval and the verdict."""
        self._set(sid, state)
        if state == "running":
            labels = {"bisection": "Looking for a polluter", "retrieval": "Reading the code",
                      "verdict": "Deciding"}
            self.stages[sid]["detail"] = labels.get(sid, "Working")
            self.current = None
        self.write()

    # -------------------------------------------------------------- observer

    def on_run_start(self, mode: str, iteration: int, seed: int | None, test_id: str | None) -> None:
        if self.stages["checkout"]["state"] == "running":
            self._set("checkout", "done", "Target ready")
        sid = STAGE_OF_MODE[mode]
        order = [s for s, *_ in STAGES]
        for earlier in order[: order.index(sid)]:  # a later stage starting means earlier ones ended
            if self.stages[earlier]["state"] == "running":
                self._set(earlier, "done")
        self._set(sid, "running")
        focus = self._focus()
        condition = MODE_LABELS[mode] + (f" · seed {seed}" if seed is not None else "")
        self.current = m.Current(test=test_id or focus or "Whole suite", condition=condition)
        self._describe()
        self.write()

    def on_run_end(self, result: SliceResult) -> None:
        self.finished.append(result)
        self._describe()
        self.write()

    # ---------------------------------------------------------------- derived

    def _runs(self, mode: str) -> list[SliceResult]:
        return runs_of(self.finished, mode)

    def _failing_tests(self, modes: tuple[str, ...] | None = None) -> set[str]:
        return failing_tests(self.finished, modes)

    def _focus(self) -> str | None:
        return focus_test(self.finished)

    def _describe(self) -> None:
        base, shuf, iso = self._runs("baseline"), self._runs("shuffled"), self._runs("isolated")
        rev, rep, par = self._runs("reversed"), self._runs("repeated"), self._runs("parallel")
        if base:
            self.stages["baseline"]["detail"] = (
                f"{plural(len(base), 'run')} in default order, {plural(len(self._failing_tests(('baseline',))), 'test')} failed"
            )
        if shuf or self.stages["shuffled"]["state"] != "pending":
            seeds = [r.seed for r in shuf if r.seed is not None]
            span = (f"seeds {seeds[0]} to {seeds[-1]}" if len(seeds) > 1 else f"seed {seeds[0]}") if seeds else "no seeds yet"
            text = (
                f"{len(shuf)} of {self.shuffled_n} runs done ({span}), "
                f"{plural(len(self._failing_tests(('shuffled',))), 'test')} failed at least once"
            )
            if rev:
                text += f"; {plural(len(rev), 'reversed run')} done"
            self.stages["shuffled"]["detail"] = text
        if iso or rep or par or self.stages["isolated"]["state"] != "pending":
            parts = [f"{plural(len(iso), 'test')} run alone"]
            if rep:
                parts.append(f"{plural(len(rep), 'repeated run')} done")
            if par:
                parts.append(f"{plural(len(par), 'parallel run')} done")
            self.stages["isolated"]["detail"] = ", ".join(parts)

    def _matrix(self) -> list[m.MatrixRow]:
        return matrix_rows(self.finished, self.shuffled_n)

    def snapshot(self) -> m.RunStatus:
        stages = [
            m.Stage(id=sid, name=s["name"], detail=s["detail"], tool=s["tool"], time=s["time"], state=s["state"])
            for sid, s in self.stages.items()
        ]
        focus = self._focus()
        shuf = self._runs("shuffled")
        if focus:
            failures = sum(
                1 for r in shuf if any(o.test_id == focus and o.outcome in FAILED for o in r.outcomes)
            )
        else:
            failures = sum(1 for r in shuf if any(o.outcome in FAILED for o in r.outcomes))
        return m.RunStatus(
            id=self.run_id, target=self.target, mode="local", status=self.status, pr=None,  # type: ignore[arg-type]
            stages=stages, current=self.current,
            counters=m.Counters(
                runsDone=len(shuf), runsTotal=self.shuffled_n, failures=failures,
                flagged=len(self._failing_tests()),
            ),
            matrix=self._matrix(), notice=self.notice,
        )

    # ------------------------------------------------------------------ output

    def write(self, run: m.RunStatus | None = None) -> None:
        write_atomic(self.path, (run or self.snapshot()).model_dump_json(indent=2))

    def complete(self, built: m.RunStatus) -> None:
        """Replace the progress with the finished run from the builder."""
        matrix = built.matrix or self._matrix()  # a clean run has no followed test: show the whole suite
        self.write(built.model_copy(update={"mode": "local", "notice": None, "current": None, "matrix": matrix}))

    def fail(self, detail: str) -> None:
        self.write(stopped_early(self.snapshot(), detail))
