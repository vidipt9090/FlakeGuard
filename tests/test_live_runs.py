"""Live runs: progress.json, the start endpoint's refusals, dead processes, and a real scan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from flakeguard.console import models as m
from flakeguard.console import runs as runs_module
from flakeguard.console.live import LiveRun, write_atomic
from flakeguard.console.live_scan import main as live_scan_main
from flakeguard.console.runs import RunManager, set_manager
from flakeguard.runner.matrix import SliceResult
from flakeguard.runner.matrix import TestRunOutcome as RunOutcome


def outcomes(**results: str) -> list[RunOutcome]:
    return [RunOutcome(test_id=f"tests.test_a::{name}", outcome=o, duration_s=0.0) for name, o in results.items()]


def slice_(mode: str, i: int, seed: int | None, **results: str) -> SliceResult:
    return SliceResult(mode=mode, iteration=i, exit_code=0, duration_s=0.1, outcomes=outcomes(**results), seed=seed)


def read(live: LiveRun) -> m.RunStatus:
    return m.RunStatus.model_validate_json(live.path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- LiveRun


def test_progress_shows_the_real_seed_of_the_run_in_progress(tmp_path: Path):
    live = LiveRun(tmp_path, "live-2026-11-21-001", "x", shuffled_n=4, seed_start=1)
    live.on_run_start("baseline", 1, None, None)
    live.on_run_end(slice_("baseline", 1, None, test_x="PASS"))
    live.on_run_start("shuffled", 1, 1, None)
    run = read(live)
    assert run.current is not None and run.current.condition == "Shuffled order · seed 1"
    live.on_run_end(slice_("shuffled", 1, 1, test_x="PASS"))
    live.on_run_start("shuffled", 2, 2, None)
    live.on_run_end(slice_("shuffled", 2, 2, test_x="FAIL"))
    live.on_run_start("shuffled", 3, 3, None)
    run = read(live)
    assert run.current is not None and run.current.condition == "Shuffled order · seed 3"
    assert run.current.test.endswith("test_x"), "the matrix follows the test that failed"


def test_progress_numbers_come_from_finished_runs_and_unrun_cells_are_none(tmp_path: Path):
    live = LiveRun(tmp_path, "live-2026-11-21-001", "x", shuffled_n=4, seed_start=1)
    live.on_run_start("baseline", 1, None, None)
    live.on_run_end(slice_("baseline", 1, None, test_x="PASS", test_y="PASS"))
    for i, (x, y) in enumerate([("PASS", "PASS"), ("FAIL", "PASS")], start=1):
        live.on_run_start("shuffled", i, i, None)
        live.on_run_end(slice_("shuffled", i, i, test_x=x, test_y=y))
    run = read(live)
    assert run.status == "running"
    assert run.counters.model_dump() == {"runsDone": 2, "runsTotal": 4, "failures": 1, "flagged": 1}
    shuffled = next(r for r in run.matrix if r.label == "Shuffled")
    assert shuffled.cells == ["pass", "fail", "none", "none"]
    assert "seeds 1 to 2" in shuffled.summary
    stage = {s.id: s for s in run.stages}
    assert stage["shuffled"].detail.startswith("2 of 4 runs done (seeds 1 to 2)")
    assert stage["baseline"].detail == "1 run in default order, 0 tests failed"
    assert stage["shuffled"].state == "running" and stage["isolated"].state == "pending"


def test_stage_text_uses_singular_and_real_counts(tmp_path: Path):
    live = LiveRun(tmp_path, "live-2026-11-21-001", "x", shuffled_n=1, seed_start=1)
    live.on_run_start("baseline", 1, None, None)
    live.on_run_end(slice_("baseline", 1, None, test_x="FAIL"))
    run = read(live)
    assert next(s for s in run.stages if s.id == "baseline").detail == "1 run in default order, 1 test failed"


def test_fail_marks_the_run_stopped_early_with_no_verdict(tmp_path: Path):
    live = LiveRun(tmp_path, "live-2026-11-21-001", "x", shuffled_n=4, seed_start=1)
    live.on_run_start("baseline", 1, None, None)
    live.fail("boom")
    run = read(live)
    assert run.status == "failed" and run.notice is not None and run.notice.kind == "scan-incomplete"
    assert run.current is None
    assert all(s.state != "running" for s in run.stages)


def test_write_atomic_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "progress.json"
    write_atomic(target, "one")
    write_atomic(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["progress.json"]


# ------------------------------------------------------------------ endpoints


class FakeProc:
    def __init__(self, returncode: int | None = None) -> None:
        self.pid = 4242
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from flakeguard.app.api import app

    manager = RunManager(tmp_path / "runs")
    set_manager(manager)
    started: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        started.append(cmd)
        return FakeProc()

    monkeypatch.setattr(runs_module.subprocess, "Popen", fake_popen)
    # No real GitHub token, whatever this machine is signed in to: tests must not depend on it.
    from flakeguard.console import routes

    monkeypatch.setattr(routes, "github_token", lambda: None)
    c = TestClient(app)
    c.manager = manager  # type: ignore[attr-defined]
    c.started = started  # type: ignore[attr-defined]
    yield c
    set_manager(None)


BODY = {"target": "", "source": "sample", "runs": 10, "docker": False}


def test_post_runs_starts_a_scan_and_never_replays_a_recorded_run(client):
    resp = client.post("/api/runs", json=BODY)
    assert resp.status_code == 200
    run_id = resp.json()["id"]
    assert run_id.startswith("live-"), "a recorded run id must never come back from POST /api/runs"
    (cmd,) = client.started
    assert cmd[cmd.index("--shuffled-n") + 1] == "10"
    assert cmd[cmd.index("--seed-start") + 1] == "1001"
    assert cmd[cmd.index("--run-id") + 1] == run_id
    assert "--docker" not in cmd


def test_seed_start_can_be_set_from_the_environment(client, monkeypatch):
    monkeypatch.setenv("FLAKEGUARD_SEED_START", "1")
    client.post("/api/runs", json=BODY)
    (cmd,) = client.started
    assert cmd[cmd.index("--seed-start") + 1] == "1"


def test_second_scan_is_refused_while_one_is_running(client):
    assert client.post("/api/runs", json=BODY).status_code == 200
    resp = client.post("/api/runs", json=BODY)
    assert resp.status_code == 409 and "already running" in resp.json()["detail"]
    assert len(client.started) == 1


def test_pull_request_target_must_look_like_owner_repo_hash_number(client):
    resp = client.post("/api/runs", json={**BODY, "source": "pull-request", "target": "just some words"})
    assert resp.status_code == 422 and "owner/repo#7" in resp.json()["detail"]
    assert client.started == []


def test_pull_request_source_without_a_backend_token_says_so(client, monkeypatch):
    from flakeguard.console import routes

    monkeypatch.setattr(routes, "actions_source", lambda root: None)
    resp = client.post("/api/runs", json={**BODY, "source": "pull-request", "target": "o/r#7"})
    assert resp.status_code == 503 and "GITHUB_TOKEN" in resp.json()["detail"]
    assert client.started == [], "a pull request scan never starts a local subprocess"


def test_pull_request_source_attaches_to_the_github_run_and_returns_its_id(client, monkeypatch):
    from flakeguard.console import routes

    seen = {}

    class FakeSource:
        def attach(self, repo, pr):
            seen["target"] = (repo, pr)
            return "actions-123"

    monkeypatch.setattr(routes, "actions_source", lambda root: FakeSource())
    resp = client.post("/api/runs", json={**BODY, "source": "pull-request", "target": "vidipt9090/flakeguard-demo#3"})
    assert resp.status_code == 200 and resp.json() == {"id": "actions-123"}
    assert seen["target"] == ("vidipt9090/flakeguard-demo", 3)
    assert client.started == []


def test_pull_request_with_no_run_yet_is_a_readable_404(client, monkeypatch):
    from flakeguard.console import routes
    from flakeguard.console.actions import NoRun

    class FakeSource:
        def attach(self, repo, pr):
            raise NoRun("No FlakeGuard run exists for o/r#7 at commit abc1234 yet.")

    monkeypatch.setattr(routes, "actions_source", lambda root: FakeSource())
    resp = client.post("/api/runs", json={**BODY, "source": "pull-request", "target": "o/r#7"})
    assert resp.status_code == 404 and "No FlakeGuard run exists" in resp.json()["detail"]


def test_github_budget_and_api_errors_have_readable_answers(client, monkeypatch):
    from flakeguard.console import routes
    from flakeguard.console.actions import ApiError, BudgetExhausted

    for exc, status, words in ((BudgetExhausted("x"), 429, "1,000 requests per hour"),
                               (ApiError(404, "x"), 404, "could not find"),
                               (ApiError(403, "x"), 502, "refused"),
                               (ApiError(500, "x"), 502, "HTTP 500")):
        class FakeSource:
            def attach(self, repo, pr, exc=exc):
                raise exc

        monkeypatch.setattr(routes, "actions_source", lambda root, f=FakeSource: f())
        resp = client.post("/api/runs", json={**BODY, "source": "pull-request", "target": "o/r#7"})
        assert resp.status_code == status and words in resp.json()["detail"], (exc, resp.json())


def test_unvetted_remote_repository_needs_docker(client):
    body = {**BODY, "source": "repo", "target": "someone/else"}
    resp = client.post("/api/runs", json=body)
    assert resp.status_code == 422 and "Docker" in resp.json()["detail"]
    assert client.started == []


def test_run_count_is_bounded(client):
    assert client.post("/api/runs", json={**BODY, "runs": 0}).status_code == 422
    assert client.post("/api/runs", json={**BODY, "runs": 51}).status_code == 422


def test_docker_requested_but_not_running_runs_nothing(client, monkeypatch):
    from flakeguard.runner.sandbox import DockerSandbox

    monkeypatch.setattr(DockerSandbox, "is_available", lambda self: False)
    resp = client.post("/api/runs", json={**BODY, "docker": True})
    assert resp.status_code == 200
    run = m.RunStatus.model_validate(client.get(f"/api/runs/{resp.json()['id']}").json())
    assert run.status == "failed" and run.notice is not None and run.notice.kind == "docker-not-running"
    assert run.counters.runsDone == 0 and all(s.state == "pending" for s in run.stages)
    assert client.started == [], "nothing may be run when Docker was requested and is not running"
    assert client.manager.processes == {}
    assert client.get(f"/api/runs/{run.id}/findings").status_code == 409


def test_a_dead_process_is_reported_as_stopped_early_with_no_verdict(client):
    run_id = client.post("/api/runs", json=BODY).json()["id"]
    live = LiveRun(client.manager.root / run_id, run_id, "x", shuffled_n=10, seed_start=1001)
    live.on_run_start("shuffled", 1, 1001, None)
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
    resp = client.get(f"/api/runs/{run_id}/findings")
    assert resp.status_code == 409 and "not finished" in resp.json()["detail"]

    client.manager.processes[run_id].returncode = -9  # the scan was killed
    run = m.RunStatus.model_validate(client.get(f"/api/runs/{run_id}").json())
    assert run.status == "failed" and run.notice is not None and run.notice.kind == "scan-incomplete"
    assert "exit code -9" in (run.notice.detail or "")
    assert client.get(f"/api/runs/{run_id}/findings").status_code == 409
    assert client.get(f"/api/runs/{run_id}/tree").status_code == 409
    # and it stays that way
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"


def test_a_run_left_over_from_a_previous_server_is_not_shown_as_running(client):
    stale = client.manager.root / "live-2026-01-01-001"
    live = LiveRun(stale, "live-2026-01-01-001", "x", shuffled_n=3, seed_start=1)
    live.on_run_start("baseline", 1, None, None)
    run = client.get("/api/runs/live-2026-01-01-001").json()
    assert run["status"] == "failed" and run["notice"]["kind"] == "scan-incomplete"


def test_recorded_runs_are_still_served_by_id(client):
    ids = sorted(p.name for p in runs_module.REPO_ROOT.joinpath("recorded").glob("run-*"))
    run = client.get(f"/api/runs/{ids[-1]}").json()
    assert run["mode"] == "recorded" and run["notice"]["kind"] == "recorded-run"
    assert client.get("/api/health").json()["recorded"] == ids[-1]


# ------------------------------------------------------------- real scan


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tiny"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_a.py").write_text("def test_ok():\n    assert True\n\n\ndef test_bad():\n    assert False\n")
    return repo


def test_live_scan_end_to_end_writes_progress_findings_and_seeds(tmp_path: Path, tiny_repo: Path):
    run_dir = tmp_path / "run"
    code = live_scan_main([
        "--run-dir", str(run_dir), "--run-id", "live-2026-11-21-001", "--target", str(tiny_repo),
        "--label", "tiny", "--shuffled-n", "3", "--seed-start", "1",
    ])
    assert code == 0
    run = m.RunStatus.model_validate_json((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert run.status == "complete" and run.mode == "local" and run.notice is None
    shuffled = next(s for s in run.stages if s.id == "shuffled")
    assert "seeds 1 to 3" in shuffled.detail
    findings = json.loads((run_dir / "findings.json").read_text(encoding="utf-8"))
    assert [f["test"] for f in findings] == ["test_bad"] and findings[0]["verdict"] == "real"
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines() if line.strip()]
    seeds = [e["data"]["seed"] for e in events if e["data"].get("mode") == "shuffled" and e["type"] == "progress"]
    assert seeds == [1, 2, 3]
    assert not list(run_dir.glob("*.tmp"))


def test_live_scan_reports_an_unusable_target_as_stopped_early(tmp_path: Path):
    run_dir = tmp_path / "run"
    code = live_scan_main([
        "--run-dir", str(run_dir), "--run-id", "live-2026-11-21-001", "--target", "not a repo at all",
        "--label", "x", "--shuffled-n", "2", "--seed-start", "1",
    ])
    assert code == 1
    run = m.RunStatus.model_validate_json((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert run.status == "failed" and run.notice is not None and run.notice.kind == "scan-incomplete"
    assert not (run_dir / "findings.json").exists()
