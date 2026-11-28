"""The no-tests flow as the console shows it: a recorded scan of a repository without tests.

``scripts/run_no_tests.py`` scans the fixture, asks the model for one test per risky spot and validates each (flakeguard/notest),
then writes ``recorded_no_tests/<id>/state.json`` with every candidate, kept or dropped, and the plan the screen reads.
The Drop action only edits those two files on disk. Nothing here talks to GitHub.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from flakeguard.console import models as m

REPO_ROOT = Path(__file__).resolve().parents[2]
NO_TESTS_DIR = REPO_ROOT / "recorded_no_tests"
ID = re.compile(r"^notests-\d{4}-\d{2}-\d{2}-\d{3}$")
STEPS = ("Find risky spots", "Write tests", "Check them", "Open PR on your fork")

# One plain sentence per scanner category (flakeguard/notest/scanner.py RiskCategory plus the "randomness" name it emits).
WHY = {
    "now": "The result changes with the time of day.",
    "random": "The result changes every run.",
    "randomness": "The result changes every run.",
    "sleep": "The timing changes with machine speed.",
    "globals": "State kept between calls changes what the next call returns.",
    "threads": "A background worker can finish at a different moment.",
    "network": "The answer depends on a service outside the code.",
}


def is_no_tests_id(run_id: str) -> bool:
    return bool(ID.match(run_id))


class NoTestsNotFound(Exception):
    """Raised with a sentence the person using the console can read."""


class NoTestsRefused(Exception):
    """The action is not possible for this plan; the message says why."""


def resolve_id(run_id: str, root: Path | None = None) -> str:
    """``latest`` means the newest recorded scan (by id); any other id is returned unchanged."""
    if run_id != "latest":
        return run_id
    base = root or NO_TESTS_DIR
    ids = sorted(p.name for p in base.glob("notests-*") if is_no_tests_id(p.name) and (p / "state.json").is_file()) if base.is_dir() else []
    if not ids:
        raise NoTestsNotFound("No no-tests scan has been recorded yet.")
    return ids[-1]


def _dir(run_id: str, root: Path | None = None) -> Path:
    if not is_no_tests_id(run_id):
        raise NoTestsNotFound(f"There is no no-tests scan called {run_id}.")
    return (root or NO_TESTS_DIR) / run_id


def read_state(run_id: str, root: Path | None = None) -> dict:
    path = _dir(run_id, root) / "state.json"
    if not path.is_file():
        raise NoTestsNotFound(f"There is no no-tests scan called {run_id}.")
    return json.loads(path.read_text(encoding="utf-8"))


def snippet_lines(path: Path, line: int, before: int = 2, after: int = 2, note: str | None = None) -> list[dict]:
    """Source lines around ``line`` (1-based), the one at ``line`` marked hot."""
    text = path.read_text(encoding="utf-8").splitlines()
    lo, hi = max(1, line - before), min(len(text), line + after)
    return [{"n": n, "t": text[n - 1], **({"hot": True, **({"note": note} if note else {})} if n == line else {})}
            for n in range(lo, hi + 1)]


def code_lines(code: str, hot_prefix: str = "def test_") -> list[dict]:
    lines = code.strip("\n").splitlines()
    return [{"n": i, "t": t, **({"hot": True} if t.startswith(hot_prefix) else {})} for i, t in enumerate(lines, 1)]


def plan_from_state(state: dict) -> m.NoTestsPlan:
    cands = state["candidates"]
    active = [c for c in cands if c["kept"]]
    k = state["provenance"]["k_shuffled_runs"]
    spots = [m.RiskySpot(where=c["where"], what=c["what"], why=WHY.get(c["category"], c["what"]),
                         test=c["test"] if c["kept"] else None) for c in cands]
    dropped = [m.DroppedTest(test=c["test"], where=c["where"], reason=c["reason"] or "No reason was recorded.", byUser=c["droppedByUser"])
               for c in cands if not c["kept"]]
    example = checks = None
    if active:
        c = active[0]
        example = m.NoTestsExample(
            risky=m.CodeSnippet(file=c["risky"]["file"], role="the risky spot", lines=[m.CodeLine(**x) for x in c["risky"]["lines"]]),
            test=m.CodeSnippet(file=c["testFile"]["file"], role="the test FlakeGuard wrote", lines=[m.CodeLine(**x) for x in c["testFile"]["lines"]]))
        checks = [m.NoTestsCheck(label="Runs and passes on the current commit", ok=c["checks"]["passedAtHead"]),
                  m.NoTestsCheck(label=f"Same result in {k} runs with different shuffle seeds", ok=c["checks"]["deterministic"])]
    pv = state["provenance"]
    from_model = sum(not c["fromTemplate"] for c in cands)
    notes = [
        f"Written by {pv['model']} through Ollama (temperature 0, seed {pv['seed']}): {from_model} of {len(cands)} tests came from the model; "
        f"{len(cands) - from_model} came from the generic template because the reply had no usable test.",
        f"Checks run in a local process on a temporary copy of the repository, not in Docker. Each generated file holds one test, so the order "
        f"cannot change; the {k} seeds change what random returns. A clock-dependent test can pass all {k} runs on the same day.",
        "The mutation check is not run in this build.",
        f"Recorded {pv['date_utc']} at commit {pv['commit'][:7]} with: {pv['command']}",
    ]
    states = ["done", "done", "done", "pending"]
    return m.NoTestsPlan(
        repo=state["repo"], steps=[m.NoTestsStep(name=n, state=s) for n, s in zip(STEPS, states)],  # type: ignore[arg-type]
        spots=spots, example=example, checks=checks or [], dropped=dropped, notes=notes, canOpenPr=False)


def write_plan(run_id: str, state: dict, root: Path | None = None) -> m.NoTestsPlan:
    plan = plan_from_state(state)
    d = _dir(run_id, root)
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    (d / "no_tests.json").write_text(plan.model_dump_json(indent=1), encoding="utf-8")
    return plan


def read_plan(run_id: str, root: Path | None = None) -> m.NoTestsPlan:
    return plan_from_state(read_state(run_id, root))


def drop_test(run_id: str, test: str, root: Path | None = None) -> m.NoTestsPlan:
    """Mark one kept test as dropped by the person. Local files only; the test file in the repository is never touched."""
    state = read_state(run_id, root)
    for c in state["candidates"]:
        if c["test"] == test:
            if not c["kept"]:
                raise NoTestsRefused(f"{test} is already dropped.")
            c["kept"], c["droppedByUser"], c["reason"] = False, True, "Dropped by you on this screen."
            return write_plan(run_id, state, root)
    raise NoTestsNotFound(f"This scan has no test called {test}.")
