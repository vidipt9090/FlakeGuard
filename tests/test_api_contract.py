"""Contract tests for the console API.

* The Pydantic models must match ``console/src/types.ts`` (field names, which fields are
  optional, and the string unions).
* A field snapshot fails when any model field is renamed, added or removed. If the change is
  intended, regenerate it: ``python tests/test_api_contract.py --update``.
* Every endpoint's JSON must validate against the models and agree with the raw JUnit files
  the recorded run was built from.
"""

from __future__ import annotations

import json
import re
import sys
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from flakeguard.console import models as m
from flakeguard.console.store import RECORDED_DIR

REPO = Path(__file__).resolve().parents[1]
TYPES_TS = REPO / "console" / "src" / "types.ts"
SNAPSHOT = REPO / "tests" / "data" / "contract_snapshot.json"


def model_classes() -> dict[str, type[BaseModel]]:
    return {
        name: obj for name, obj in vars(m).items()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == m.__name__
        and not name.startswith("_")
    }


def parse_interfaces(source: str) -> dict[str, dict[str, bool]]:
    """interface name -> {field: is_optional}. Only top-level fields (two-space indent)."""
    out: dict[str, dict[str, bool]] = {}
    for match in re.finditer(r"export interface (\w+) \{\n(.*?)\n\}", source, re.S):
        fields = {}
        for line in match.group(2).split("\n"):
            f = re.match(r"^  (\w+)(\?)?:", line)
            if f:
                fields[f.group(1)] = bool(f.group(2))
        out[match.group(1)] = fields
    return out


def parse_unions(source: str) -> dict[str, set[str]]:
    out = {}
    for match in re.finditer(r"export type (\w+)\s*=\s*((?:\s*\|?\s*'[^']+')+);", source):
        out[match.group(1)] = set(re.findall(r"'([^']+)'", match.group(2)))
    return out


def test_models_match_typescript_interfaces():
    interfaces = parse_interfaces(TYPES_TS.read_text(encoding="utf-8"))
    models = model_classes()
    assert len(interfaces) >= 19, "types.ts parsing found too few interfaces"
    for name, fields in interfaces.items():
        assert name in models, f"types.ts declares {name} but there is no model for it"
        model_fields = models[name].model_fields
        assert set(model_fields) == set(fields), f"{name}: field names differ from types.ts"
        for field, optional in fields.items():
            assert (not model_fields[field].is_required()) == optional, (
                f"{name}.{field}: optional in types.ts is {optional}"
            )


def test_string_unions_match_typescript():
    unions = parse_unions(TYPES_TS.read_text(encoding="utf-8"))
    assert {"Verdict", "ScreenState", "RunMode"} <= set(unions)
    for name, values in unions.items():
        assert set(typing.get_args(getattr(m, name))) == values, f"{name} differs from types.ts"
    # NodeStatus is declared as `Verdict | 'polluter' | 'clean'`, which the parser above skips.
    assert "NodeStatus = Verdict | 'polluter' | 'clean'" in TYPES_TS.read_text(encoding="utf-8")
    assert set(typing.get_args(m.NodeStatus)) == unions["Verdict"] | {"polluter", "clean"}


def current_snapshot() -> dict[str, list[str]]:
    return {name: sorted(cls.model_fields) for name, cls in sorted(model_classes().items())}


def test_field_snapshot_fails_when_a_field_is_renamed():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current_snapshot() == expected, (
        "A model field changed. If this is intended, update types.ts, then run "
        "`python tests/test_api_contract.py --update`."
    )


# --------------------------------------------------------------------------- endpoints


@pytest.fixture(scope="module")
def client():
    from flakeguard.app.api import app

    return TestClient(app)


@pytest.fixture(scope="module")
def run_id():
    ids = sorted(p.name for p in RECORDED_DIR.glob("run-*") if p.is_dir())
    assert ids, "recorded/ has no run; run scripts/record_run.py"
    return ids[-1]


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["mode"] in ("actions", "local")
    assert isinstance(body["docker"], bool)


def test_run_status_validates_and_is_a_labelled_replay(client, run_id):
    resp = client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    run = m.RunStatus.model_validate(resp.json())
    assert run.mode == "recorded"
    assert run.notice is not None and run.notice.kind == "recorded-run"
    assert run.pr is None, "a local fixture has no pull request"
    assert [s.id for s in run.stages] == [
        "checkout", "install", "baseline", "shuffled", "isolated", "bisection", "retrieval", "verdict", "pr-comment",
    ]


def test_findings_tree_and_no_tests_validate(client, run_id):
    findings = [m.Finding.model_validate(x) for x in client.get(f"/api/runs/{run_id}/findings").json()]
    tree = m.TreeData.model_validate(client.get(f"/api/runs/{run_id}/tree").json())
    plan = m.NoTestsPlan.model_validate(client.get(f"/api/runs/{run_id}/no-tests").json())
    assert findings and tree.root.children
    assert plan.spots == [] and plan.example is None, "nothing was run for the no-tests flow"
    ids = {f.id for f in findings}
    tree_ids = set()

    def walk(node: m.TreeNode) -> None:
        tree_ids.add(node.id)
        if node.findingId:
            assert node.findingId in ids
        for child in node.children:
            walk(child)

    walk(tree.root)
    for s in tree.sharedState:
        assert set(s.writers) | set(s.readers) <= tree_ids


def test_optional_keys_are_absent_not_null(client, run_id):
    snippet = next(f["writer"] for f in client.get(f"/api/runs/{run_id}/findings").json() if f["writer"])
    for line in snippet["lines"]:
        assert "note" not in line or line["note"] is not None
        assert "hot" not in line or line["hot"] is True
    notice = client.get(f"/api/runs/{run_id}").json()["notice"]
    assert "detail" not in notice or isinstance(notice["detail"], str)


def test_unknown_run_is_a_readable_404(client):
    resp = client.get("/api/runs/run-2000-01-01-001")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "There is no run called run-2000-01-01-001."}
    assert client.get("/api/runs/not-a-run/findings").status_code == 404


def test_results_are_dashes_until_a_run_exists(client):
    for label in ("injected", "natural", "planted"):
        data = m.ResultsData.model_validate(client.get(f"/api/results?label={label}").json())
        assert data.ablation.provenance.labelType == label
        assert data.ablation.table.rows == [] and data.baselines.table.rows == []
        assert data.ablation.provenance.command is None and data.baselines.provenance.commit is None
        assert data.runsToDecision.fixed is None and data.triage.realQuarantined is None
    assert client.get("/api/results?label=made-up").status_code == 422


def test_quarantine_is_refused_for_the_real_failure_and_never_calls_github(client, run_id):
    findings = client.get(f"/api/runs/{run_id}/findings").json()
    real = next(f for f in findings if f["verdict"] == "real")
    resp = client.post(f"/api/findings/{real['id']}/quarantine")
    assert resp.status_code == 409
    assert resp.json()["detail"] == real["quarantine"]["reason"]
    flaky = next(f for f in findings if f["verdict"] == "flaky")
    resp = client.post(f"/api/findings/{flaky['id']}/quarantine")
    assert resp.status_code == 409 and "local fixture" in resp.json()["detail"]


def test_fix_is_refused_when_there_is_no_fix(client, run_id):
    finding = client.get(f"/api/runs/{run_id}/findings").json()[0]
    assert finding["fix"] is None
    resp = client.post(f"/api/findings/{finding['id']}/fix")
    assert resp.status_code == 409 and "no validated fix" in resp.json()["detail"]


def recorded_target(run_id: str) -> Path:
    """The repository the run scanned, from the run's meta.json (a fixture path or a saved copy)."""
    from flakeguard.console.store import RecordedStore

    target = RecordedStore().target_path(run_id)
    assert target is not None, f"{run_id} has no readable target in meta.json"
    return target


def test_ask_cites_real_lines_and_says_nothing_when_nothing_matches(client, run_id):
    finding = next(f for f in client.get(f"/api/runs/{run_id}/findings").json() if f["verdict"] == "flaky")
    answer = m.AskAnswer.model_validate(
        client.post(f"/api/findings/{finding['id']}/ask", json={"question": "Why does CACHE matter here?"}).json()
    )
    assert answer.chunks > 0 and answer.citations
    for c in answer.citations:
        lines = (recorded_target(run_id) / c.file).read_text(encoding="utf-8").splitlines()
        assert 1 <= c.line <= len(lines)
    empty = m.AskAnswer.model_validate(
        client.post(f"/api/findings/{finding['id']}/ask", json={"question": "xyzzy plugh frobnicate"}).json()
    )
    assert empty.chunks == 0 and empty.citations == [] and empty.text == ""


def test_recorded_counts_match_the_raw_junit_files(run_id):
    """Every count in the evidence bullets is recomputed from raw/artifacts/junit_*.xml."""
    from flakeguard.console.builder import collect_stats, load_runs
    from flakeguard.console.store import RecordedStore

    target = recorded_target(run_id)
    stats = collect_stats(load_runs(target, RECORDED_DIR / run_id / "raw" / "artifacts"))
    findings = RecordedStore().findings(run_id)
    assert findings
    for f in findings:
        s = stats[f"{f.file}::{f.test}"]
        for bullet in f.evidence:
            mode = re.match(r"^(.*?): (passed|failed) in (\d+) of (\d+) runs?", bullet)
            if not mode:
                continue
            label = mode.group(1)
            key = {"Default order": "baseline", "Shuffled order": "shuffled", "Reversed order": "reversed",
                   "Alone": "isolated", "Repeated": "repeated", "Parallel": "parallel"}[label]
            failed, total = s.count(key)
            claimed_failed = int(mode.group(3)) if mode.group(2) == "failed" else 0
            assert (claimed_failed, int(mode.group(4))) == (failed, total), (f.test, bullet)


if __name__ == "__main__":
    if "--update" in sys.argv:
        SNAPSHOT.write_text(json.dumps(current_snapshot(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {SNAPSHOT}")
