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
from pydantic import BaseModel, TypeAdapter
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


def test_run_source_comes_from_the_recorded_meta_and_is_null_when_unknown(client):
    meta = json.loads((RECORDED_DIR / "run-2026-11-21-002" / "meta.json").read_text(encoding="utf-8"))
    run = m.RunStatus.model_validate(client.get("/api/runs/run-2026-11-21-002").json())
    assert run.source == m.SourceRef(repo=meta["source_repo"], ref=meta["source_commit"])
    fixture = m.RunStatus.model_validate(client.get("/api/runs/run-2026-11-18-001").json())
    assert fixture.source is None  # a local fixture is not on GitHub, so nothing may link to it


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


def test_results_are_dashes_when_there_is_no_recorded_run(tmp_path):
    from flakeguard.console.results import load_results

    for label in ("injected", "natural", "planted"):
        data = load_results(label, tmp_path)  # an empty results folder
        assert data.ablation.provenance.labelType == label
        assert all(cell is None for row in data.ablation.table.rows for cell in row[1:])  # the four settings, dashes
        assert data.baselines.table.rows == [] and data.triageTable.table.rows == []
        assert data.ablation.provenance.command is None and data.baselines.provenance.commit is None
        assert data.runsToDecision.fixed is None and data.triage.realQuarantined is None
        assert data.status == "not run"


def test_natural_is_always_dashes_and_says_why(client):
    data = m.ResultsData.model_validate(client.get("/api/results?label=natural").json())
    assert data.baselines.table.rows == [] and data.runsToDecision.adaptive is None
    assert data.status == "not run" and "No natural dataset" in data.notes[0]


def test_results_for_planted_and_injected_come_from_the_recorded_files(client):
    for label, n in (("planted", 31), ("injected", 476)):
        data = m.ResultsData.model_validate(client.get(f"/api/results?label={label}").json())
        p = data.baselines.provenance
        assert p.labelType == label and p.n == n and p.command.startswith("python scripts/run_eval.py") and p.commit
        assert data.status == "run" and data.baselines.table.rows
        assert all(row[1] is None or "of" in row[1] for row in data.baselines.table.rows)  # counts come with their N
        assert any("tests between executions" in (row[1] or "") for row in data.baselines.table.rows)  # B1 tolerance
        assert f"N={n} tests" in data.runsToDecision.adaptive
    notes = m.ResultsData.model_validate(client.get("/api/results?label=injected").json()).notes
    assert any("08:00 to 18:00" in x for x in notes) and any("same fault classes" in x for x in notes)


def test_the_superseded_eval3_numbers_are_never_served(client, tmp_path):
    from flakeguard.console.results import load_results

    (tmp_path / "eval3").mkdir()
    (tmp_path / "eval3" / "rq1.json").write_text("{}", encoding="utf-8")
    assert client.get("/api/results?label=eval3").status_code == 422
    with pytest.raises(ValueError):
        load_results("eval3", tmp_path)  # a folder that exists but is not one of the three label types is not read


@pytest.fixture
def github_calls(monkeypatch):
    """The routes' GitHub client on a mock transport. ``permission`` is what the mock answers for write access."""
    import functools

    import httpx

    from flakeguard.console import forge, routes

    calls: list[tuple[str, str]] = []
    state = {"permission": "admin"}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "someone"})
        if request.url.path.endswith("/permission"):
            return httpx.Response(200, json={"permission": state["permission"]})
        if request.url.path.endswith("/issues"):
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/1"})
        return httpx.Response(404, json={"message": "unexpected"})

    monkeypatch.setattr(forge, "GitHub", functools.partial(forge.GitHub, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(routes, "github_token", lambda: "test-token")
    return calls, state


def test_quarantine_is_refused_for_the_real_failure_and_never_calls_github(client, run_id, github_calls):
    calls, _ = github_calls
    findings = client.get(f"/api/runs/{run_id}/findings").json()
    real = next(f for f in findings if f["verdict"] == "real")
    resp = client.post(f"/api/findings/{real['id']}/quarantine")
    assert resp.status_code == 409
    assert resp.json()["detail"] == real["quarantine"]["reason"]
    unknown = next(f for f in findings if f["verdict"] == "unknown")
    resp = client.post(f"/api/findings/{unknown['id']}/quarantine")
    assert resp.status_code == 409 and resp.json()["detail"] == unknown["quarantine"]["reason"]
    assert calls == []  # a refusal calls nothing on GitHub


def test_quarantine_of_a_flaky_test_needs_write_access_and_then_opens_one_issue(client, run_id, github_calls):
    calls, state = github_calls
    flaky = next(f for f in client.get(f"/api/runs/{run_id}/findings").json() if f["verdict"] == "flaky")
    state["permission"] = "read"
    resp = client.post(f"/api/findings/{flaky['id']}/quarantine")
    assert resp.status_code == 409 and "does not have write access" in resp.json()["detail"]
    assert ("POST", "/repos/vidipt9090/flakeguard-demo/issues") not in calls
    state["permission"] = "write"
    resp = client.post(f"/api/findings/{flaky['id']}/quarantine")
    assert resp.status_code == 200 and resp.json() == {"issueUrl": "https://github.com/o/r/issues/1"}
    assert calls.count(("POST", "/repos/vidipt9090/flakeguard-demo/issues")) == 1


def test_quarantine_on_a_local_fixture_changes_nothing(client, github_calls):
    calls, _ = github_calls
    findings = client.get("/api/runs/run-2026-11-18-001/findings").json()
    flaky = next(f for f in findings if f["verdict"] == "flaky")
    resp = client.post(f"/api/findings/{flaky['id']}/quarantine")
    assert resp.status_code == 409 and "local fixture" in resp.json()["detail"]
    assert calls == []


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


def test_the_default_console_question_gets_an_answer_scoped_to_the_order_dependent_finding(client, run_id):
    """The question the Findings screen starts with has no identifier in it; the finding supplies the search terms."""
    finding = next(f for f in client.get(f"/api/runs/{run_id}/findings").json() if f["verdict"] == "flaky")
    answer = m.AskAnswer.model_validate(
        client.post(f"/api/findings/{finding['id']}/ask", json={"question": "Why is this test order-dependent?"}).json()
    )
    assert answer.chunks > 0 and answer.citations
    cited = {c.label for c in answer.citations}
    assert {"tests/test_report.py:4", "tests/test_warmup.py:4", "src/inventory/cache.py:3"} <= cited  # victim, polluter, CACHE
    for c in answer.citations:
        lines = (recorded_target(run_id) / c.file).read_text(encoding="utf-8").splitlines()
        assert 1 <= c.line <= len(lines)
    assert "Code behind this finding" in answer.text


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


def test_an_actions_finding_id_resolves_to_its_actions_run(monkeypatch):
    """Findings made in Actions are named gh-<run>_finding-N; the console's run id is actions-<run>."""
    from flakeguard.console import routes

    seen = []
    recorded = TypeAdapter(list[m.Finding]).validate_json(
        (RECORDED_DIR / "run-2026-11-21-002" / "findings.json").read_text(encoding="utf-8"))
    finding = recorded[0].model_copy(update={"id": "gh-123_finding-1"})
    monkeypatch.setattr(routes, "_findings", lambda run_id: (seen.append(run_id), [finding])[1])
    assert routes._find_finding("gh-123_finding-1") == ("actions-123", finding)
    assert seen == ["actions-123"]


def test_rq4_table_and_notes_are_read_from_the_result_files(client):
    import json

    from flakeguard.console.results import RESULTS_DIR

    integ = json.loads((RESULTS_DIR / "injected" / "rq4_integrity.json").read_text(encoding="utf-8"))
    leak = json.loads((RESULTS_DIR / "injected" / "rq4_leakage_split.json").read_text(encoding="utf-8"))
    data = m.ResultsData.model_validate(client.get("/api/results?label=injected").json())
    rows = {r[0]: r for r in data.ablation.table.rows}
    assert len(data.ablation.table.columns) == 5 and all(len(r) == 5 for r in data.ablation.table.rows)
    for name, key in (("AST tree only", "none_vs_ast"), ("AST + Jedi tree", "none_vs_ast_jedi"), ("The whole file", "none_vs_file")):
        pair = integ["mcnemar_exact_paired"][key]
        assert f"p = {pair['p_two_sided']:.4f} ({pair['kind']})" in rows[name][2]  # p and planned or exploratory come from the file
    assert rows["No code"][2] == "reference setting"
    text = " ".join(data.notes)
    sm = leak["summary"]["ast"]
    assert f"{sm['a_has_injector_specific_identifier']} of {sm['tests']} tests in the AST setting" in text
    assert str(integ["mcnemar_multiplicity"]["bonferroni_threshold"]) in text
    assert "does not measure the product's template fixer" in text and "counts as a miss" in text
    planted = m.ResultsData.model_validate(client.get("/api/results?label=planted").json())
    assert all(cell is None for r in planted.ablation.table.rows for cell in r[1:])  # no RQ4 on the planted set
