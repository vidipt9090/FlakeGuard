"""Build the console's JSON (RunStatus, Findings, TreeData) from a real scan's artifacts.

Inputs are the files ``flakeguard scan`` writes: ``events.jsonl`` and one JUnit XML per run.
Every count on screen is computed here from those per-run outcomes. A value the engine did
not produce is ``None``, never a placeholder.

Verdict rules (rule-based, no LLM):

* ``real``    the test failed in every run it was in.
* ``flaky``   it passed and failed, passed when run alone, a bisection named a polluter test,
              and running that pair in that order failed 5 times out of 5.
              Evidence tier is ``reproduced``. ``intervention-confirmed`` needs a change that
              removed the failure, which is not done here.
* ``unknown`` it passed and failed, and the rules above did not establish a cause.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from flakeguard.console import models as m
from flakeguard.console.analysis import (
    RepoAnalysis,
    SharedLink,
    TestDef,
    analyse_repo,
    shared_links,
)
from flakeguard.evidence.bisection import BisectionResult, bisect_polluter
from flakeguard.runner.matrix import parse_junit_xml, to_node_id

PAIR_REPEATS = 5
_REPEAT_SUFFIX = re.compile(r"\[\d+-\d+\]$")
MODE_LABELS = {
    "baseline": "Default order",
    "shuffled": "Shuffled order",
    "reversed": "Reversed order",
    "isolated": "Alone",
    "repeated": "Repeated",
    "parallel": "Parallel",
}


@dataclass
class RunRecord:
    mode: str
    iteration: int | None
    order: list[str]
    outcomes: dict[str, str]  # node id -> PASS | FAIL | ERROR | SKIP (a failing copy wins)
    messages: dict[str, str] = field(default_factory=dict)
    copies: dict[str, list[str]] = field(default_factory=dict)  # node id -> every outcome, one per copy


def node_id(repo: Path, junit_id: str) -> str:
    """JUnit id to pytest node id, also for ids that include a class (``tests.test_a.TestX::t``)."""
    converted = to_node_id(repo, junit_id)
    if converted != junit_id or "::" not in junit_id:
        return converted
    module, _, name = junit_id.partition("::")
    parts = module.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:cut]) + ".py"
        if (repo / candidate).is_file():
            return "::".join([candidate, *parts[cut:], name])
    return junit_id


def load_runs(repo: Path, artifacts: Path) -> list[RunRecord]:
    runs: list[RunRecord] = []
    for path in sorted(artifacts.glob("junit_*.xml")):
        stem = path.stem[len("junit_"):]
        mode, _, number = stem.partition("_")
        outcomes = parse_junit_xml(path)
        record = RunRecord(mode=mode, iteration=int(number) if number.isdigit() else None, order=[], outcomes={})
        for o in outcomes:
            nid = node_id(repo, o.test_id)
            if mode == "repeated":
                nid = _REPEAT_SUFFIX.sub("", nid)
            record.order.append(nid)
            record.copies.setdefault(nid, []).append(o.outcome)
            # A repeated run holds several copies of one test; any failing copy counts as a failure.
            if record.outcomes.get(nid) != "FAIL":
                record.outcomes[nid] = o.outcome
            if o.message and nid not in record.messages:
                record.messages[nid] = o.message
        runs.append(record)
    runs.sort(key=lambda r: (list(MODE_LABELS).index(r.mode) if r.mode in MODE_LABELS else 99, r.iteration or 0))
    return runs


@dataclass
class TestStats:
    test_id: str
    cells: dict[str, list[str]]  # mode -> outcomes in run order
    first_message: str | None

    @property
    def runs(self) -> list[str]:
        return [o for outs in self.cells.values() for o in outs if o in ("PASS", "FAIL", "ERROR")]

    @property
    def failures(self) -> int:
        return sum(1 for o in self.runs if o in ("FAIL", "ERROR"))

    @property
    def passes(self) -> int:
        return sum(1 for o in self.runs if o == "PASS")

    def count(self, mode: str) -> tuple[int, int]:
        """(failed, total) for one condition."""
        outs = [o for o in self.cells.get(mode, []) if o in ("PASS", "FAIL", "ERROR")]
        return sum(1 for o in outs if o in ("FAIL", "ERROR")), len(outs)


def collect_stats(runs: list[RunRecord]) -> dict[str, TestStats]:
    stats: dict[str, TestStats] = {}
    for run in runs:
        for tid, outcomes in run.copies.items():
            s = stats.setdefault(tid, TestStats(tid, {}, None))
            s.cells.setdefault(run.mode, []).extend(outcomes)
            if any(o in ("FAIL", "ERROR") for o in outcomes) and s.first_message is None:
                s.first_message = run.messages.get(tid)
    return stats


def _run_pair(repo: Path, ids: list[str]) -> bool:
    """True when the tests, run in exactly this order, make the last one fail."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", *ids],
        cwd=repo, capture_output=True, text=True, timeout=60,
    )
    return proc.returncode != 0 and f"FAILED {ids[-1]}" in proc.stdout


@dataclass
class Diagnosis:
    bisection: BisectionResult | None
    seconds: float
    reproduced: bool
    order_length: int = 0


def diagnose_order_dependence(repo: Path, victim: str, runs: list[RunRecord]) -> Diagnosis:
    """Bisect from a shuffled run where the victim failed, then confirm the pair by repetition."""
    start = time.perf_counter()
    failing = next(
        (r for r in runs if r.mode == "shuffled" and r.outcomes.get(victim) in ("FAIL", "ERROR")), None
    )
    if failing is None:
        return Diagnosis(None, time.perf_counter() - start, False)
    result = bisect_polluter(repo, victim, failing.order)
    polluter = result.polluter_id
    reproduced = False
    if polluter and result.relationship == "polluter" and polluter != victim:
        reproduced = all(_run_pair(repo, [polluter, victim]) for _ in range(PAIR_REPEATS))
    prefix = failing.order[: failing.order.index(victim)] if victim in failing.order else []
    return Diagnosis(result, time.perf_counter() - start, reproduced, len(prefix))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _lines(repo: Path, rel: str, start: int, end: int) -> list[str]:
    return (repo / rel).read_text(encoding="utf-8").splitlines()[start - 1:end]


def _call_line(repo: Path, test: TestDef, callee: str) -> int | None:
    tree = ast.parse((repo / test.file).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.lineno == test.line:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                    if name == callee:
                        return node.lineno
    return None


def _snippet(
    repo: Path, test: TestDef, role: str, note: str, hot_line: int | None
) -> m.CodeSnippet:
    lines = []
    for offset, text in enumerate(_lines(repo, test.file, test.line, test.end_line)):
        n = test.line + offset
        hot = n == hot_line
        lines.append(m.CodeLine(n=n, t=text, note=note if hot else None, hot=True if hot else None))
    return m.CodeSnippet(file=test.file, role=role, lines=lines)  # type: ignore[arg-type]


def _evidence_by_condition(s: TestStats) -> list[str]:
    bullets = []
    for mode, label in MODE_LABELS.items():
        failed, total = s.count(mode)
        if total == 0:
            continue
        unit = "run" if total == 1 else "runs"
        if failed == 0:
            bullets.append(f"{label}: passed in {total} of {total} {unit}.")
        elif failed == total:
            bullets.append(f"{label}: failed in {failed} of {total} {unit}.")
        else:
            bullets.append(f"{label}: failed in {failed} of {total} {unit}, passed in {total - failed}.")
    return bullets


@dataclass
class Built:
    run: m.RunStatus
    findings: list[m.Finding]
    tree: m.TreeData
    facts: dict


def build_run(
    repo: Path,
    artifacts: Path,
    events_path: Path,
    run_id: str,
    target_label: str,
    shuffled_n: int,
    live: bool = False,
    progress: Callable[[str, str], None] | None = None,
    stage_text: dict[str, str] | None = None,
) -> Built:
    """``live=True`` builds a local scan (mode ``local``, no notice); otherwise a recorded replay.

    ``progress(stage_id, state)`` is called around retrieval, bisection and the verdict.
    ``stage_text`` overrides the detail text of the checkout, install and pr-comment stages.
    """
    note = progress or (lambda stage, state: None)
    repo = repo.resolve()
    runs = load_runs(repo, artifacts)
    stats = collect_stats(runs)
    note("retrieval", "running")
    analysis = analyse_repo(repo)
    links = shared_links(analysis)
    tests = {t.id: t for t in analysis.tests}
    note("retrieval", "done")

    note("bisection", "running")
    t0 = time.perf_counter()
    diagnoses: dict[str, Diagnosis] = {}
    for tid, s in stats.items():
        if s.failures and s.passes:
            diagnoses[tid] = diagnose_order_dependence(repo, tid, runs)
    bisection_seconds = time.perf_counter() - t0
    note("bisection", "done")
    note("verdict", "running")

    findings: list[m.Finding] = []
    status_by_test: dict[str, str] = {}
    finding_id_by_test: dict[str, str] = {}
    polluters: dict[str, str] = {}  # polluter test id -> victim test id

    ordered = sorted(
        (s for s in stats.values() if s.failures and s.test_id in tests),
        key=lambda s: (tests[s.test_id].file, tests[s.test_id].line),
    )
    for s in ordered:
        t = tests[s.test_id]
        fid = f"{run_id}_finding-{len(findings) + 1}"
        runs_n = len(s.runs)
        diag = diagnoses.get(s.test_id)
        link = next((lk for lk in links if s.test_id in (*lk.readers, *lk.writers)), None)
        evidence = _evidence_by_condition(s)
        directory = t.file.rsplit("/", 1)[0] + "/" if "/" in t.file else ""
        filename = t.file.rsplit("/", 1)[-1]
        chips = [m.LivesChip(text=directory, tone="plain")] if directory else []
        chips += [m.LivesChip(text=filename, tone="plain"), m.LivesChip(text=t.name, tone="plain")]
        writer = reader = None
        repro: str | None = None
        did = "Nothing was posted or changed. This run scanned a local fixture, not a GitHub pull request."
        subtype: str | None = None
        quarantine = m.Quarantine(allowed=True, reason=None)

        if s.passes == 0:
            verdict, tier, severity = "real", "observed", "blocking"
            first = (s.first_message or "").strip().splitlines()[0] if s.first_message else None
            why = f"This test failed in all {_plural(runs_n, 'run')} it was in, including when run on its own, so test order does not explain it."
            if s.count("isolated")[1] == 0:
                why = f"This test failed in all {_plural(runs_n, 'run')} it was in, so it is not an intermittent failure."
            if first:
                why += f" The failure message is: {first}"
            summary = f"Real failure · failed in {s.failures} of {_plural(runs_n, 'run')}. Quarantine refused."
            limits = "FlakeGuard did not look for the cause of the bug. A failure in every run is treated as a real defect."
            quarantine = m.Quarantine(allowed=False, reason="Fails in every run. A real failure cannot be quarantined.")
            iso_failed, iso_total = s.count("isolated")
            if iso_total and iso_failed == iso_total:
                repro = f"pytest {t.id}"
            label = f"Real failure · {s.failures} of {runs_n}"
        else:
            polluter_id = diag.bisection.polluter_id if diag and diag.bisection else None
            if diag and diag.reproduced and polluter_id in tests:
                verdict, tier, severity, subtype = "flaky", "reproduced", "suggestion", "order-dependent"
                p = tests[polluter_id]
                steps = len(diag.bisection.history) if diag.bisection else 0
                evidence.append(
                    f"Bisection names {p.name} as the polluter (narrowed from {_plural(diag.order_length, 'preceding test')} in {_plural(steps, 'step')})."
                )
                evidence.append(
                    f"Running {p.name} then {t.name} failed in {PAIR_REPEATS} of {PAIR_REPEATS} repeats."
                )
                repro = f"pytest {p.id} {t.id} -p no:randomly"
                polluters[p.id] = s.test_id
                if link and s.test_id in link.readers and polluter_id in link.writers:
                    w_acc = next(a for a in analysis.accesses if a.test_id == polluter_id and a.state == link.state and a.kind == "write")
                    r_acc = next(a for a in analysis.accesses if a.test_id == s.test_id and a.state == link.state and a.kind == "read")
                    name = link.state.name
                    via_w = " through " + " → ".join(w_acc.via) if w_acc.via else ""
                    via_r = " through " + " → ".join(r_acc.via) if r_acc.via else ""
                    why = (
                        f"This test reads the shared {name} ({link.state.file}:{link.state.line}){via_r} at {r_acc.file}:{r_acc.line}. "
                        f"Another test, {p.name}, writes it{via_w} at {w_acc.file}:{w_acc.line}. "
                        f"If {p.name} runs first, this test fails."
                    )
                    chips += [
                        m.LivesChip(text=f"reads {name}", tone="read"),
                        m.LivesChip(text=f"written by {p.name}", tone="write"),
                    ]
                    w_call = _call_line(repo, p, w_acc.via[0]) if w_acc.via else w_acc.line
                    r_call = _call_line(repo, t, r_acc.via[0]) if r_acc.via else r_acc.line
                    writer = _snippet(repo, p, "the polluter", f"Writes {name} at {w_acc.file}:{w_acc.line}.", w_call)
                    reader = _snippet(repo, t, "the victim", f"Reads {name} at {r_acc.file}:{r_acc.line}. Fails if {p.name} ran first.", r_call)
                else:
                    why = (
                        f"This test fails when {p.name} runs before it, and passes on its own. "
                        "The shared value behind this was not identified by the static analysis."
                    )
                summary = "Order-dependent · evidence: reproduced"
                limits = "The order dependence is shown for these two tests. Other causes of flakiness in this test are not ruled out."
                label = "Flaky · order-dependent"
            else:
                verdict, tier, severity = "unknown", "observed", "needs-evidence"
                why = (
                    f"This test failed in {s.failures} of {_plural(runs_n, 'run')} and passed in the other {s.passes}. "
                    "No polluter test was found, and no targeted run reproduced the failure."
                )
                summary = f"{_plural(s.failures, 'failure')} in {_plural(runs_n, 'run')}. Too few to call it flaky."
                limits = (
                    f"{_plural(s.failures, 'failure')} in {_plural(runs_n, 'run')} is not enough to tell a flaky test from a one-off. "
                    "Run more shuffled runs to decide."
                )
                quarantine = m.Quarantine(allowed=False, reason="Too few failures to call this test flaky. Re-verify first.")
                label = f"Unknown · {s.failures} of {runs_n} failed"

        findings.append(m.Finding(
            id=fid, test=t.name, file=t.file, line=t.line, verdict=verdict, subtype=subtype,  # type: ignore[arg-type]
            severity=severity, evidenceTier=tier, summaryLine=summary, why=why, evidence=evidence,  # type: ignore[arg-type]
            lives=chips, did=did, limits=limits, writer=writer, reader=reader, repro=repro, fix=None,
            quarantine=quarantine,
        ))
        status_by_test[s.test_id] = label
        finding_id_by_test[s.test_id] = fid

    verdict_by_test = {f.test: f.verdict for f in findings}
    tree = _build_tree(repo, analysis, links, stats, findings, tests, polluters, finding_id_by_test, status_by_test)
    run = _build_status(
        repo, events_path, run_id, target_label, shuffled_n, runs, stats, findings, tests,
        diagnoses, bisection_seconds, links, analysis, live, stage_text or {},
    )
    note("verdict", "done")
    facts = {
        "tests": len(tests),
        "findings": {f.test: f.verdict for f in findings},
        "shuffled": {tid: s.count("shuffled") for tid, s in stats.items() if s.count("shuffled")[0]},
        "verdict_by_test": verdict_by_test,
    }
    return Built(run=run, findings=findings, tree=tree, facts=facts)


def _build_tree(
    repo: Path, analysis: RepoAnalysis, links: list[SharedLink], stats: dict[str, TestStats],
    findings: list[m.Finding], tests: dict[str, TestDef], polluters: dict[str, str],
    finding_id_by_test: dict[str, str], label_by_test: dict[str, str],
) -> m.TreeData:
    verdict_by_finding = {f.id: f.verdict for f in findings}
    node_ids = {tid: f"t{i}" for i, tid in enumerate(sorted(tests), 1)}
    by_file: dict[str, list[TestDef]] = {}
    for t in sorted(tests.values(), key=lambda t: (t.file, t.line)):
        by_file.setdefault(t.file, []).append(t)

    precedence = ["real", "flaky", "unknown", "polluter", "clean"]
    file_nodes: list[m.TreeNode] = []
    for i, (file, file_tests) in enumerate(by_file.items(), 1):
        leaves: list[m.TreeNode] = []
        for t in file_tests:
            fid = finding_id_by_test.get(t.id)
            if fid:
                status = verdict_by_finding[fid]
                label = label_by_test[t.id]
                link_id = fid
            elif t.id in polluters:
                writes = ", ".join(sorted({lk.state.name for lk in links if t.id in lk.writers})) or "shared state"
                status, label, link_id = "polluter", f"Polluter · writes {writes}", finding_id_by_test.get(polluters[t.id])
            else:
                status, label, link_id = "clean", "Passes in every run", None
            leaves.append(m.TreeNode(
                id=node_ids[t.id], kind="test", name=t.name, path=f"{t.file}:{t.line}", status=status,  # type: ignore[arg-type]
                label=label, faults=0, findingId=link_id, children=[],
            ))
        counts = {s: sum(1 for leaf in leaves if leaf.status == s) for s in precedence if s != "clean"}
        worst = next((s for s in precedence if counts.get(s)), "clean")
        names = {"real": "real failure", "flaky": "flaky", "unknown": "unknown", "polluter": "polluter"}
        label = ", ".join(f"{n} {names[s]}" for s, n in counts.items() if n) or "Passes in every run"
        file_nodes.append(m.TreeNode(
            id=f"f{i}", kind="file", name=file.rsplit("/", 1)[-1], path=file, status=worst,  # type: ignore[arg-type]
            label=label, faults=sum(counts.values()), findingId=None, children=leaves,
        ))
    root = m.TreeNode(
        id="repo", kind="repo", name=repo.name, path=None, status="clean",
        label=f"{len(tests)} tests · {_plural(len(findings), 'fault')}", faults=len(findings),
        findingId=None, children=file_nodes,
    )
    shared = []
    for k, lk in enumerate(links, 1):
        shared.append(m.SharedState(
            id=f"s{k}", name=lk.state.name, path=f"{lk.state.file}:{lk.state.line}",
            note=f"A module-level value written by {len(lk.writers)} and read by {len(lk.readers)} test(s)",
            writers=[node_ids[w] for w in lk.writers], readers=[node_ids[r] for r in lk.readers],
        ))
    return m.TreeData(root=root, sharedState=shared)


def _seconds(a: datetime, b: datetime) -> str:
    delta = (b - a).total_seconds()
    return "under 1 s" if delta < 1 else f"{round(delta)} s"


def shuffled_seeds(events_path: Path) -> list[int]:
    """The seed of each shuffled run, in order, as recorded by the engine."""
    seeds = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ev = json.loads(line)
            if ev["stage"] == "run" and ev["type"] == "progress" and ev["data"].get("mode") == "shuffled":
                if "seed" in ev["data"]:
                    seeds.append(ev["data"]["seed"])
    return seeds


def _event_times(events_path: Path) -> list[tuple[datetime, dict]]:
    out = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ev = json.loads(line)
            out.append((datetime.fromisoformat(ev["ts"]), ev))
    return out


def _build_status(
    repo: Path, events_path: Path, run_id: str, target_label: str, shuffled_n: int,
    runs: list[RunRecord], stats: dict[str, TestStats], findings: list[m.Finding],
    tests: dict[str, TestDef], diagnoses: dict[str, Diagnosis], bisection_seconds: float,
    links: list[SharedLink], analysis: RepoAnalysis, live: bool, stage_text: dict[str, str],
) -> m.RunStatus:
    events = _event_times(events_path)

    def first(stage: str, kind: str, mode: str | None = None) -> datetime | None:
        for ts, ev in events:
            if ev["stage"] == stage and ev["type"] == kind and (mode is None or ev["data"].get("mode") == mode):
                return ts
        return None

    t_ingest = first("ingest", "started")
    t_discover = first("discover", "started")
    t_base = first("run", "progress", "baseline")
    t_shuf = first("run", "progress", "shuffled")
    t_rev = first("run", "progress", "reversed")
    t_iso = first("run", "progress", "isolated")
    t_rep = first("run", "progress", "repeated")

    def span(a: datetime | None, b: datetime | None) -> str | None:
        return _seconds(a, b) if a and b else None

    def mode_counts(mode: str) -> tuple[int, int]:
        """(distinct tests that failed in at least one run of this mode, number of runs)."""
        rs = [r for r in runs if r.mode == mode]
        failing = {tid for r in rs for tid, o in r.outcomes.items() if o in ("FAIL", "ERROR")}
        return len(failing), len(rs)

    b_failed, b_n = mode_counts("baseline")
    s_failed, s_n = mode_counts("shuffled")
    seeds = shuffled_seeds(events_path)
    seed_text = (f"seeds {seeds[0]} to {seeds[-1]}" if len(seeds) > 1 else f"seed {seeds[0]}") if seeds else "seeds not recorded"
    i_rs = [r for r in runs if r.mode == "isolated"]
    pollutions = [d for d in diagnoses.values() if d.reproduced and d.bisection]
    stages = [
        m.Stage(id="checkout", name="Checkout",
                detail=stage_text.get("checkout", "Local fixture, used in place. No clone was needed."),
                tool="local path", time=span(t_ingest, t_discover), state="done"),
        m.Stage(id="install", name="Install", detail=stage_text.get("install", "Not run. The fixture has no dependencies to install."),
                tool="not run", time=None, state="pending"),
        m.Stage(id="baseline", name="Baseline",
                detail=f"{_plural(b_n, 'run')} in default order, {_plural(b_failed, 'test')} failed", tool="pytest",
                time=span(t_base, t_shuf), state="done"),
        m.Stage(id="shuffled", name="Shuffled runs",
                detail=f"{_plural(s_n, 'run')}, {seed_text}, {_plural(s_failed, 'test')} failed at least once",
                tool="pytest, pytest-randomly", time=span(t_shuf, t_rev), state="done"),
        m.Stage(id="isolated", name="Isolated runs",
                detail=f"{_plural(len(i_rs), 'test')} run alone", tool="pytest", time=span(t_iso, t_rep), state="done"),
        m.Stage(id="bisection", name="Bisection",
                detail=(f"Named {_plural(len(pollutions), 'polluter')}" if pollutions else "No polluter found"),
                tool="FlakeGuard evidence engine", time=f"{round(bisection_seconds)} s" if bisection_seconds >= 1 else "under 1 s",
                state="done"),
        m.Stage(id="retrieval", name="Retrieval",
                detail=f"Found {_plural(len(analysis.states), 'shared name')} and {_plural(len(links), 'shared link')} in {_plural(len(tests), 'test')}",
                tool="AST + Jedi", time=None, state="done"),
        m.Stage(id="verdict", name="Verdict",
                detail=", ".join(f"{sum(1 for f in findings if f.verdict == v)} {v}" for v in ("flaky", "real", "unknown")),
                tool="FlakeGuard rules (no LLM)", time=None, state="done"),
        m.Stage(id="pr-comment", name="PR comment", detail=stage_text.get("pr-comment", "Not run. This is a local fixture, not a pull request."),
                tool="not run", time=None, state="pending"),
    ]

    focus = next((f for f in findings if f.verdict == "flaky"), findings[0] if findings else None)
    matrix: list[m.MatrixRow] = []
    if focus:
        s = stats[next(tid for tid, t in tests.items() if (t.file, t.line) == (focus.file, focus.line))]

        def row(label: str, mode: str) -> m.MatrixRow:
            cells = ["pass" if o == "PASS" else "fail" for o in s.cells.get(mode, []) if o in ("PASS", "FAIL", "ERROR")]
            f, n = s.count(mode)
            summary = f"{_plural(n, 'run')}: {n - f} passed, {f} failed" if n else "No runs"
            return m.MatrixRow(label=label, summary=summary, cells=cells)  # type: ignore[arg-type]

        matrix = [row("Baseline", "baseline"), row("Shuffled", "shuffled"), row("Isolated", "isolated")]
    sh_done = len([r for r in runs if r.mode == "shuffled"])
    focus_failures = s.count("shuffled")[0] if focus else 0
    return m.RunStatus(
        id=run_id, target=target_label, mode="local" if live else "recorded", status="complete", pr=None,
        stages=stages,
        current=None,
        counters=m.Counters(runsDone=sh_done, runsTotal=shuffled_n, failures=focus_failures, flagged=len(findings)),
        matrix=matrix,
        notice=None if live else m.Notice(
            kind="recorded-run", detail="Replay of a saved scan of a local fixture, not a GitHub pull request."
        ),
    )
