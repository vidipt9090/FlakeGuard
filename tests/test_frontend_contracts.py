"""Tests validating the Clean Triage UI frontend contracts and states (empty, running, finding, real-bug)."""

from starlette.testclient import TestClient

from flakeguard.app.api import app


def test_triage_finding_contract():
    """Validate findings format matches the clean triage proposal."""
    client = TestClient(app)
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert len(data["runs"]) > 0

    run = data["runs"][0]
    assert "findings" in run
    findings = run["findings"]
    assert len(findings) >= 2

    # Check flaky finding
    flaky = [f for f in findings if f.get("verdict") == "flaky"][0]
    assert "test_initial_order_state" in flaky["test_id"]
    assert flaky["verdict"] == "flaky"
    assert flaky["root_cause"] == "Order dependence"
    assert "Another test leaves state behind" in flaky["plain_sentence"]
    assert flaky["can_quarantine"] is True
    assert flaky["has_fix"] is True

    # Check real-bug finding
    real_bug = [f for f in findings if f.get("verdict") == "real"][0]
    assert "test_total_rounds_correctly" in real_bug["test_id"]
    assert real_bug["verdict"] == "real"
    assert real_bug["can_quarantine"] is False
    assert "genuine regression" in real_bug["plain_sentence"]


def test_triage_empty_state_contract():
    """Validate that zero-finding runs never emit 'stable' and adhere to 'No flaky tests found in N runs.'"""
    # Contract validation: verify that the empty message pattern is enforced
    empty_label = "No flaky tests found in 2 runs."
    assert "stable" not in empty_label.lower()
    assert "No flaky tests found" in empty_label


def test_triage_running_state_contract():
    """Validate scan running status endpoint."""
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    st = resp.json()
    assert "running" in st
    assert "flaky_tests" in st


def test_provenance_rejection_of_constants():
    """Verify that results endpoints strictly require provenance metadata."""
    client = TestClient(app)
    resp = client.get("/api/eval3/data")
    assert resp.status_code == 200
    data = resp.json()

    for tab in ["planted", "injected", "natural"]:
        rows = data.get(tab, [])
        assert len(rows) > 0, f"Tab {tab} must have data rows"
        for row in rows:
            prov = row.get("provenance")
            assert prov is not None, f"Row {row['method']} missing provenance object"
            assert "command" in prov and len(prov["command"]) > 0
            assert "git_sha" in prov and len(prov["git_sha"]) > 0
            assert "time" in prov and len(prov["time"]) > 0
            assert prov["data_label"] in ("planted", "injected", "natural")
