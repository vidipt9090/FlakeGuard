"""Tests for the JSON API the React dashboard runs on.

The UI is a separate process from the navigator, so the contract between them
is a real seam: a renamed field here breaks a chart there with no type error
on either side. These tests pin the fields the UI actually reads.

Starlette's TestClient drives the app in-process — no server, no port, so
this runs in CI like any other test.
"""

import pytest

pytest.importorskip("starlette", reason="the API needs starlette")

from starlette.testclient import TestClient  # noqa: E402

from flakeguard.app.api import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


# ------------------------------------------------------------ exported sets


def test_sets_lists_the_exported_runs(client):
    body = client.get("/api/sets").json()
    assert body["sets"], "no exported tree sets — run scripts/export_knowledge_trees.py"
    names = {s["name"] for s in body["sets"]}
    assert "synthetic" in names

    synthetic = next(s for s in body["sets"] if s["name"] == "synthetic")
    assert synthetic["cases"], "the synthetic set has no cases"
    for case in synthetic["cases"]:
        assert "::" in case["test_id"], f"{case['test_id']!r} is not a node id"
        for field in ("nodes", "max_depth", "jedi_calls", "steps"):
            assert isinstance(case[field], int), field


def test_a_tree_carries_everything_the_ui_draws(client):
    sets = client.get("/api/sets").json()["sets"]
    synthetic = next(s for s in sets if s["name"] == "synthetic")
    test_id = synthetic["cases"][0]["test_id"]

    body = client.get("/api/sets/synthetic/tree", params={"test_id": test_id}).json()
    assert body["test_id"] == test_id

    # the three things the navigator view needs
    assert body["tree"]["stats"]["nodes"] >= 1
    assert body["trace"]["events"], "no trace events to replay"
    assert body["rows"], "no node rows to lay out"
    assert body["test_source"] is not None, (
        "the export has no test source — re-run the export with --with-text, "
        "or the source pane has nothing to highlight"
    )
    assert body["test_source"]["text"].strip()


def test_every_row_has_a_parent_that_exists(client):
    """The tree layout walks parent links; a dangling one would drop a node."""
    sets = client.get("/api/sets").json()["sets"]
    synthetic = next(s for s in sets if s["name"] == "synthetic")
    body = client.get(
        "/api/sets/synthetic/tree",
        params={"test_id": synthetic["cases"][0]["test_id"]},
    ).json()

    ids = {row["id"] for row in body["rows"]}
    roots = [row for row in body["rows"] if not row["parent"]]
    assert len(roots) == 1, f"expected exactly one root, got {len(roots)}"
    for row in body["rows"]:
        assert not row["parent"] or row["parent"] in ids, row


def test_trace_events_carry_produced_for_the_replay(client):
    """The replay grows the tree from these; without them nothing appears."""
    sets = client.get("/api/sets").json()["sets"]
    synthetic = next(s for s in sets if s["name"] == "synthetic")
    body = client.get(
        "/api/sets/synthetic/tree",
        params={"test_id": synthetic["cases"][0]["test_id"]},
    ).json()

    events = body["trace"]["events"]
    assert all("produced" in e for e in events)
    assert any(e["produced"] for e in events), "no step claims to have added a node"
    assert all(isinstance(e["kept"], int) for e in events)


def test_unknown_set_and_unknown_case_are_404(client):
    assert client.get("/api/sets/nope/tree", params={"test_id": "a::b"}).status_code == 404
    assert (
        client.get("/api/sets/synthetic/tree", params={"test_id": "no/such.py::test"}).status_code
        == 404
    )


# --------------------------------------------------------------- live route


def test_navigate_runs_the_navigator_for_real(client):
    response = client.post(
        "/api/navigate",
        json={
            "repo": "tests/data/navsample",
            "repo_name": "navsample",
            "test_id": "tests/test_shop.py::test_total",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["source"] == "live"
    assert body["resolved"] is True
    assert body["elapsed_ms"] > 0
    assert body["tree"]["stats"]["nodes"] > 1
    assert body["trace"]["events"]
    assert body["test_source"]["text"].startswith("def test_total")
    # the live path must produce the same replay data as an export
    assert any(e["produced"] for e in body["trace"]["events"])


def test_navigate_rejects_a_bad_id_with_a_usable_message(client):
    response = client.post("/api/navigate", json={"test_id": "not-a-node-id"})
    assert response.status_code == 400
    body = response.json()
    assert "not a pytest node id" in body["error"]
    assert "::" in body["hint"], "the hint should show the expected shape"


def test_navigate_rejects_a_missing_repo(client):
    response = client.post(
        "/api/navigate",
        json={"repo": "no/such/directory", "test_id": "a.py::test_b"},
    )
    assert response.status_code == 404
    assert "not a directory" in response.json()["error"]


def test_navigate_requires_a_test_id(client):
    assert client.post("/api/navigate", json={}).status_code == 400


def test_a_test_that_resolves_to_nothing_is_not_an_error(client):
    """The navigator never raises on a missing test, and the UI shows the
    trace so you can see where it stopped. A 500 here would hide that."""
    response = client.post(
        "/api/navigate",
        json={
            "repo": "tests/data/navsample",
            "repo_name": "navsample",
            "test_id": "tests/test_shop.py::test_does_not_exist",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["trace"]["events"], "the trace must still say where it stopped"


# ------------------------------------------------------------ the other data


def test_pipeline_exposes_the_gate_verdict(client):
    body = client.get("/api/pipeline").json()
    assert body["workflows"], "no workflow files found"
    assert any(w["name"] == "cicd.yml" for w in body["workflows"])
    if body["status"]:
        assert body["status"]["verdict"] in {"promote", "blocked"}
        assert body["status"]["checks"]
        for check in body["status"]["checks"]:
            assert check["status"] in {"pass", "warn", "fail", "skip"}
            assert check["why"], f"{check['name']} has no stated reason"


def test_results_carries_what_the_results_page_reads(client):
    body = client.get("/api/results").json()
    assert body["llm"] and body["baselines"]
    assert body["labels"]
    assert body["label_counts"]
    # numbers must arrive as numbers, not CSV strings
    assert isinstance(body["llm"][0]["f1"], (int, float))
    assert isinstance(body["nav_summary"]["resolution_rate"], (int, float))


def test_runs_computes_flip_rate(client):
    body = client.get("/api/runs").json()
    assert body["tests"]
    for row in body["tests"]:
        assert 0.0 <= row["flip_rate"] <= 0.5, row
        assert row["passes"] + row["fails"] == row["total"]
    # sorted most-unstable first, which is what the chart assumes
    rates = [t["flip_rate"] for t in body["tests"]]
    assert rates == sorted(rates, reverse=True)


def test_suggestions_are_runnable(client):
    body = client.get("/api/suggestions").json()
    assert body["suggestions"]
    for s in body["suggestions"]:
        assert "::" in s["test_id"]
        assert s["note"], "a suggestion with no explanation is just a string"


def test_spa_route_explains_itself_when_the_ui_is_not_built(client):
    """A 503 with the build command beats a blank page."""
    response = client.get("/")
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert "npm" in response.json()["fix"]
