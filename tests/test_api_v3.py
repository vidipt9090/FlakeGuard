"""Tests for S9 / Eval 3 endpoints in flakeguard.app.api."""

import uuid

from starlette.testclient import TestClient

from flakeguard.app.api import app


def test_eval3_data_carries_provenance():
    client = TestClient(app)
    resp = client.get("/api/eval3/data")
    assert resp.status_code == 200
    data = resp.json()
    assert "baselines" in data
    assert "ablations" in data
    assert "calibration" in data
    assert "risk_coverage" in data

    # Verify provenance contract in every row
    for row in data["baselines"]:
        assert "command" in row
        assert "git_sha" in row
        assert "timestamp" in row
        assert row["data_label"] in ("planted", "injected", "natural")

    for row in data["ablations"]:
        assert "command" in row
        assert "git_sha" in row
        assert "timestamp" in row
        assert row["data_label"] in ("planted", "injected", "natural")


def test_runs_and_run_detail():
    client = TestClient(app)
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)

    if data["runs"]:
        run_id = data["runs"][0]["run_id"]
        detail_resp = client.get(f"/api/runs/{run_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["run_id"] == run_id
        assert "provenance" in detail


def test_rag_ask_endpoint():
    client = TestClient(app)
    # Refusal on unindexed dynamic query
    dynamic_query = f"unmatched_test_term_{uuid.uuid4().hex}"
    resp = client.post("/api/ask", json={"query": dynamic_query})
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "refused"
    assert "Refusal" in res["answer"]
    assert "provenance" in res

    # Answer on relevant query
    resp_valid = client.post("/api/ask", json={"query": "Why does test_initial_order_state fail?", "repo": "."})
    assert resp_valid.status_code == 200
    res_valid = resp_valid.json()
    assert res_valid["status"] == "answered"
    assert len(res_valid["citations"]) > 0


def test_quarantine_refusal_on_deterministic_bug():
    client = TestClient(app)
    # Deterministic bug refusal
    resp = client.post(
        "/api/quarantine/approve",
        json={"test_id": "test_case_22", "reason": "real failure deterministic", "approver": "@maintainer"}
    )
    assert resp.status_code == 403
    assert "refused" in resp.json()["error"].lower()

    # Flaky bug accepted
    resp_flaky = client.post(
        "/api/quarantine/approve",
        json={"test_id": "synthetic/tests/test_suite_01.py::test_case_02", "reason": "flaky (order_dep)", "approver": "@maintainer"}
    )
    assert resp_flaky.status_code == 200
    assert resp_flaky.json()["status"] == "approved"
    assert "provenance" in resp_flaky.json()
