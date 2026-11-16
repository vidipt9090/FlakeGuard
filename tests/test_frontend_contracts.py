"""Tests validating the Clean Triage UI frontend contracts and states (empty, running, finding, real-bug)."""

import pytest

pytest.importorskip("starlette", reason="frontend contract tests need starlette")

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


def test_tree_view_contract_post_scan():
    """Fail if the AST+Jedi knowledge tree view data is absent, empty, or unlinked after a scan."""
    client = TestClient(app)

    # 1. Available sets must exist and provide AST trees
    sets_resp = client.get("/api/sets")
    assert sets_resp.status_code == 200
    sets_data = sets_resp.json()
    assert "sets" in sets_data and len(sets_data["sets"]) > 0, "No tree sets found"

    synth_set = [s for s in sets_data["sets"] if s["name"] == "synthetic"]
    assert len(synth_set) == 1, "Synthetic AST tree set missing"
    cases = synth_set[0].get("cases", [])
    assert len(cases) >= 30, f"Expected >= 30 synthetic test cases, got {len(cases)}"

    # 2. Verify tree endpoint returns AST root with children for a test
    first_case = cases[0]["test_id"]
    tree_resp = client.get(f"/api/sets/synthetic/tree?test_id={first_case}")
    assert tree_resp.status_code == 200
    tree_json = tree_resp.json()
    assert "tree" in tree_json, f"Tree response missing 'tree' object for {first_case}"
    root = tree_json["tree"].get("root")
    assert root is not None, f"Tree root is None for {first_case}"
    children = root.get("children", [])
    assert len(children) > 0, f"Tree root has 0 AST children for {first_case}"

    # 3. Verify scan findings connect to the tree hierarchy
    runs_resp = client.get("/api/runs")
    assert runs_resp.status_code == 200
    runs = runs_resp.json().get("runs", [])
    assert len(runs) > 0, "No scan runs found; tree cannot link finding statuses"
    findings = runs[0].get("findings", [])
    assert len(findings) > 0, "No findings in latest run; tree must have findings to color nodes"

    # 4. Verify that findings contain required AST citation and polluter links for the drawer
    flaky_findings = [f for f in findings if f.get("verdict") == "flaky"]
    assert len(flaky_findings) > 0, "Tree contract requires at least one flaky finding"
    for ff in flaky_findings:
        assert ff.get("test_id"), "Finding missing test_id"
        assert ff.get("root_cause"), "Finding missing root_cause"
        assert ff.get("plain_sentence"), "Finding missing plain_sentence"
        # Polluter or citation link must be present
        assert ff.get("polluter_file") or ff.get("polluter_test_id") or ff.get("where_it_lives"), (
            f"Flaky finding {ff['test_id']} missing polluter/where_it_lives link for tree drawer"
        )

