"""Unit tests for the FlakeGuard lightweight web dashboard server and API endpoints."""

from __future__ import annotations

import json
import threading
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from flakeguard.app.server import run_server


class LocalClient:
    """HTTP client bypassing environment proxies for local ephemeral test server."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.opener = build_opener(ProxyHandler({}))

    def get(self, path: str):
        url = f"{self.base_url}{path}"
        req = Request(url)
        return self.opener.open(req)

    def post_json(self, path: str, payload: dict):
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        return self.opener.open(req)


@pytest.fixture(scope="module")
def client():
    """Start an ephemeral test server instance in a background thread."""
    server = run_server(host="127.0.0.1", port=0)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    c = LocalClient(f"http://127.0.0.1:{port}")
    yield c
    server.shutdown()


def test_server_static_index(client: LocalClient) -> None:
    """GET / serves the dashboard HTML containing all 6 view tabs."""
    with client.get("/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        content = resp.read().decode("utf-8")
        assert "FlakeGuard CI/CD Dashboard" in content
        assert "Live Scan" in content
        assert "Test Explorer" in content
        assert "Knowledge Tree" in content
        assert "PR & Quarantine" in content
        assert "Results & Ablations" in content
        assert "Event Replay" in content


def test_server_api_status(client: LocalClient) -> None:
    """GET /api/status returns JSON scan state."""
    with client.get("/api/status") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "running" in data
        assert isinstance(data["running"], bool)


def test_server_api_tests(client: LocalClient) -> None:
    """GET /api/tests returns benchmark test cases with code and causal tiers."""
    with client.get("/api/tests") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "tests" in data
        tests = data["tests"]
        assert len(tests) > 0

        # Check structure
        sample = tests[0]
        assert "test_id" in sample
        assert "code" in sample
        assert "ground_truth" in sample
        assert "evidence_tier" in sample


def test_server_api_results(client: LocalClient) -> None:
    """GET /api/results returns ablation table, calibration data, and baseline comparison."""
    with client.get("/api/results") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "ablations" in data
        assert "calibration" in data
        assert "baselines" in data

        ablations = data["ablations"]
        assert len(ablations) >= 5
        full_v4 = next(a for a in ablations if "Full v4" in a["condition"])
        assert full_v4["precision"] == 1.0
        assert full_v4["false_quarantine_rate"] == 0.0

        calib = data["calibration"]
        assert "ece" in calib
        assert "bins" in calib
        assert len(calib["bins"]) == 10


def test_server_api_quarantine_registry(client: LocalClient) -> None:
    """GET /api/quarantine returns quarantine registry."""
    with client.get("/api/quarantine") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "quarantined_tests" in data
        assert "pr_number" in data


def test_server_quarantine_approval_flaky(client: LocalClient) -> None:
    """POST /api/quarantine/approve approves legitimate flaky test."""
    payload = {
        "test_id": "synthetic/tests/test_suite_01.py::test_case_06",
        "approver": "@maintainer",
        "reason": "flaky",
        "tier": "intervention-confirmed",
    }
    with client.post_json("/api/quarantine/approve", payload) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "approved"
        assert "successfully quarantined" in data["message"]


def test_server_quarantine_approval_refuses_real_bugs(client: LocalClient) -> None:
    """POST /api/quarantine/approve REFUSES quarantine for deterministic real bugs."""
    payload = {
        "test_id": "synthetic/tests/test_suite_03.py::test_case_22",
        "approver": "@maintainer",
        "reason": "real_fail",
        "tier": "observed",
    }
    with client.post_json("/api/quarantine/approve", payload) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "refused"
        assert "refused" in data["message"].lower()


def test_server_api_runs_and_replay(client: LocalClient) -> None:
    """GET /api/runs returns historical runs and GET /api/run/{id} returns event log."""
    with client.get("/api/runs") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "runs" in data
        runs = data["runs"]
        assert len(runs) > 0
        first_run = runs[0]["run_id"]

    # Replay specific run
    with client.get(f"/api/run/{first_run}") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["run_id"] == first_run
        assert "events" in data
        assert len(data["events"]) > 0


def test_server_api_tree(client: LocalClient) -> None:
    """GET /api/tree/{tree_file} loads knowledge tree JSON."""
    tree_file = "synthetic_tests_test_suite_01.py__test_case_01.json"
    with client.get(f"/api/tree/{tree_file}") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "tree" in data
        assert "root" in data["tree"]


def test_server_knowledge_tree_view_contract_post_scan(client: LocalClient) -> None:
    """Fail if the AST+Jedi knowledge tree data is absent or empty after a scan."""
    # 1. Fetch test cases with knowledge tree metadata
    with client.get("/api/tests") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "tests" in data
        tests = data["tests"]
        assert len(tests) > 0, "No tests recorded; knowledge tree contract requires test cases"

        # Flaky tests must have polluter / intervention information and tree references
        flaky_tests = [t for t in tests if t.get("ground_truth") == "flaky"]
        assert len(flaky_tests) > 0, "Knowledge tree contract requires flaky test cases"

        tree_tests = [t for t in tests if t.get("has_knowledge_tree") and t.get("tree_filename")]
        assert len(tree_tests) > 0, "Knowledge tree view contract failed: no tests have knowledge trees"

    # 2. Check that at least one test's AST knowledge tree is non-empty
    first_tree_file = tree_tests[0]["tree_filename"]
    with client.get(f"/api/tree/{first_tree_file}") as tree_resp:
        assert tree_resp.status == 200
        tree_data = json.loads(tree_resp.read().decode("utf-8"))
        assert "tree" in tree_data, f"Tree response missing 'tree' object in {first_tree_file}"
        assert "root" in tree_data["tree"], f"Tree missing 'root' object in {first_tree_file}"
        root = tree_data["tree"]["root"]
        assert len(root.get("children", [])) > 0, f"Tree root has 0 AST children in {first_tree_file}"


