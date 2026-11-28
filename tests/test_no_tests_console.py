"""The no-tests plan the console serves: built from a recorded state file, with dropped tests and their reasons (AC-N2)."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from flakeguard.console import models as m
from flakeguard.console import no_tests

RUN = "notests-2026-01-02-001"


def _candidate(name: str, kept: bool, reason: str | None = None, template: bool = False) -> dict:
    return {
        "test": name, "where": f"{name}.py:7", "category": "now", "what": "Reads system wall-clock time via datetime.now.",
        "kept": kept, "droppedByUser": False, "reason": reason, "fromTemplate": template, "testCode": "def test_x():\n    assert True\n",
        "checks": {"passedAtHead": kept or reason != "Test failed to pass at HEAD", "deterministic": kept, "kRunsExecuted": 3},
        "risky": {"file": f"{name}.py", "lines": [{"n": 7, "t": "    now = datetime.now()", "hot": True}]},
        "testFile": {"file": f"tests/test_{name}.py", "lines": [{"n": 1, "t": "def test_x():", "hot": True}, {"n": 2, "t": "    assert True"}]},
    }


@pytest.fixture
def state() -> dict:
    return {
        "id": RUN, "repo": "fixtures/demo",
        "candidates": [_candidate("kept_a", True), _candidate("failed_b", False, "Failed shuffled determinism check on run 2/3", template=True),
                       _candidate("kept_c", True)],
        "provenance": {"date_utc": "2026-01-02T00:00:00Z", "command": "python scripts/run_no_tests.py", "commit": "0123456789abcdef", "model": "m",
                       "seed": 42, "k_shuffled_runs": 3, "sandbox": "local", "risky_sites_found": 3},
    }


def test_plan_lists_dropped_tests_with_the_reason_and_names_the_real_k(state):
    plan = no_tests.plan_from_state(state)
    assert [s.test for s in plan.spots] == ["kept_a", None, "kept_c"]
    assert [(d.test, d.reason, d.byUser) for d in plan.dropped] == [("failed_b", "Failed shuffled determinism check on run 2/3", False)]
    assert [c.label for c in plan.checks] == ["Runs and passes on the current commit", "Same result in 3 runs with different shuffle seeds"]
    assert plan.example is not None and plan.example.test.role == "the test FlakeGuard wrote"
    assert plan.canOpenPr is False and [s.state for s in plan.steps][-1] == "pending"
    assert any("2 of 3 tests came from the model" in n for n in plan.notes)  # the template case is counted, not hidden


def test_drop_is_local_records_the_reason_and_moves_the_example(tmp_path, state):
    no_tests.write_plan(RUN, state, tmp_path)
    plan = no_tests.drop_test(RUN, "kept_a", tmp_path)
    assert [d.test for d in plan.dropped] == ["kept_a", "failed_b"] or {d.test for d in plan.dropped} == {"kept_a", "failed_b"}
    assert next(d for d in plan.dropped if d.test == "kept_a").byUser is True
    assert plan.spots[0].test is None and plan.spots[2].test == "kept_c"
    saved = json.loads((tmp_path / RUN / "no_tests.json").read_text(encoding="utf-8"))
    assert m.NoTestsPlan.model_validate(saved).dropped[0].reason
    assert sorted(p.name for p in (tmp_path / RUN).iterdir()) == ["no_tests.json", "state.json"]  # nothing else was written
    with pytest.raises(no_tests.NoTestsRefused):
        no_tests.drop_test(RUN, "kept_a", tmp_path)
    with pytest.raises(no_tests.NoTestsNotFound):
        no_tests.drop_test(RUN, "nope", tmp_path)


def test_ids_are_checked_before_any_path_is_built():
    for bad in ("../x", "notests-1", "run-2026-01-02-001", "notests-2026-01-02-001/../x"):
        assert not no_tests.is_no_tests_id(bad)
        with pytest.raises(no_tests.NoTestsNotFound):
            no_tests.read_state(bad)


def test_routes_serve_and_drop_only_a_recorded_no_tests_scan(tmp_path, state, monkeypatch):
    from flakeguard.app.api import app

    monkeypatch.setattr(no_tests, "NO_TESTS_DIR", tmp_path)
    no_tests.write_plan(RUN, state)
    client = TestClient(app)
    plan = m.NoTestsPlan.model_validate(client.get(f"/api/runs/{RUN}/no-tests").json())
    assert len(plan.spots) == 3 and plan.dropped[0].test == "failed_b"
    after = m.NoTestsPlan.model_validate(client.post(f"/api/runs/{RUN}/no-tests/drop", json={"test": "kept_a"}).json())
    assert {d.test for d in after.dropped} == {"failed_b", "kept_a"}
    assert client.post(f"/api/runs/{RUN}/no-tests/drop", json={"test": "kept_a"}).status_code == 409
    assert client.post(f"/api/runs/{RUN}/no-tests/drop", json={}).status_code == 422
    assert client.post(f"/api/runs/{RUN}/no-tests/drop", json={"test": "zzz"}).status_code == 404
    assert client.post("/api/runs/run-2026-11-21-001/no-tests/drop", json={"test": "x"}).status_code == 409
    assert client.get("/api/runs/notests-2030-01-01-009/no-tests").status_code == 404


def test_latest_resolves_to_the_newest_recorded_scan_and_drop_follows_it(tmp_path, state, monkeypatch):
    from flakeguard.app.api import app

    monkeypatch.setattr(no_tests, "NO_TESTS_DIR", tmp_path)
    older = {**state, "id": "notests-2026-01-02-001", "repo": "older"}
    newer = {**state, "id": "notests-2026-01-02-002", "repo": "newer"}
    no_tests.write_plan(older["id"], older)
    no_tests.write_plan(newer["id"], newer)
    client = TestClient(app)
    assert m.NoTestsPlan.model_validate(client.get("/api/runs/latest/no-tests").json()).repo == "newer"
    assert client.get(f"/api/runs/{older['id']}/no-tests").json()["repo"] == "older"  # the older record stays reachable by id
    assert client.post("/api/runs/latest/no-tests/drop", json={"test": "kept_a"}).status_code == 200
    assert {d.test for d in no_tests.read_plan(newer["id"]).dropped} == {"failed_b", "kept_a"}
    assert {d.test for d in no_tests.read_plan(older["id"]).dropped} == {"failed_b"}  # the older scan was not touched
    monkeypatch.setattr(no_tests, "NO_TESTS_DIR", tmp_path / "empty")
    assert client.get("/api/runs/latest/no-tests").status_code == 404


def test_the_screens_carry_the_kept_note_and_the_live_link_points_at_the_latest_scan():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "console" / "src" / "pages"
    assert "Kept means the test passed validation, not that it is a strong test." in (src / "NoTests.tsx").read_text(encoding="utf-8")
    assert '<Link to="/no-tests?plan=latest">See how FlakeGuard handles it</Link>' in (src / "Live.tsx").read_text(encoding="utf-8")
