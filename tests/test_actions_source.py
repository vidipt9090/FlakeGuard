"""ActionsRunSource against real GitHub API responses captured from a finished scan.yml run
(vidipt9090/flakeguard-demo, PR #2, run 44876577191, 2026-11-21)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from flakeguard.console import models as m
from flakeguard.console.actions import (
    ActionsRunSource,
    ApiError,
    BudgetExhausted,
    GitHubApi,
    NoRun,
    is_actions_id,
    short_name,
    step_state,
)

FIX = Path(__file__).parent / "data" / "actions" / "smoke-run-44876577191"
REPO, PR, RUN = "vidipt9090/flakeguard-demo", 2, 44876577191


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeGitHub:
    """Serves the captured responses and counts every request."""

    def __init__(self, overrides: dict[str, object] | None = None) -> None:
        self.requests: list[str] = []
        self.overrides = overrides or {}
        self.artifacts = load("artifacts.json")["artifacts"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        self.requests.append(path)
        bare = path.split("?")[0]
        for key, value in self.overrides.items():
            if bare.endswith(key):
                if isinstance(value, int):
                    return httpx.Response(value, json={"message": "nope"})
                return httpx.Response(200, json=value)
        if bare == f"/repos/{REPO}/pulls/{PR}":
            return httpx.Response(200, json=load("pr.json"))
        if bare == f"/repos/{REPO}/actions/runs" and "head_sha" in path:
            return httpx.Response(200, json=load("runs_for_head.json"))
        if bare == f"/repos/{REPO}/actions/runs/{RUN}":
            return httpx.Response(200, json=load("run.json"))
        if bare == f"/repos/{REPO}/actions/runs/{RUN}/jobs":
            return httpx.Response(200, json=load("jobs.json"))
        if bare == f"/repos/{REPO}/actions/runs/{RUN}/artifacts":
            return httpx.Response(200, json=load("artifacts.json"))
        if bare.startswith(f"/repos/{REPO}/actions/artifacts/") and bare.endswith("/zip"):
            return httpx.Response(200, content=(FIX / f"artifact-{bare.split('/')[-2]}.zip").read_bytes())
        return httpx.Response(404, json={"message": f"unexpected {path}"})


@pytest.fixture
def source(tmp_path: Path):
    gh = FakeGitHub()
    clock = Clock()
    api = GitHubApi("token", clock=clock, transport=httpx.MockTransport(gh.handler))
    src = ActionsRunSource(api, tmp_path / "runs")
    src.gh, src.clock = gh, clock  # type: ignore[attr-defined]
    return src


def test_ids_and_names():
    assert is_actions_id("actions-44876577191") and not is_actions_id("live-2026-11-21-001")
    assert short_name("scan / shuffled (seed 3)") == "shuffled (seed 3)"
    assert short_name("plan") == "plan"
    assert step_state({"status": "completed", "conclusion": "success"}) == "done"
    assert step_state({"status": "in_progress", "conclusion": None}) == "running"
    assert step_state({"status": "completed", "conclusion": "skipped"}) == "pending"
    assert step_state({"status": "completed", "conclusion": "failure"}) == "failed"


def test_attach_finds_the_newest_flakeguard_run_for_the_pull_request(source):
    run_id = source.attach(REPO, PR)
    assert run_id == f"actions-{RUN}"
    meta = json.loads((source.root / run_id / "meta.json").read_text())
    assert meta == {"repo": REPO, "run_id": RUN, "pr_number": PR}


def test_attach_says_so_when_no_run_exists(source):
    source.api._http = httpx.Client(transport=httpx.MockTransport(FakeGitHub({"/actions/runs": {"workflow_runs": []}}).handler))
    with pytest.raises(NoRun, match="No FlakeGuard run exists"):
        source.attach(REPO, PR)


def test_a_finished_run_maps_to_the_contract_with_real_step_times_and_engine_counts(source):
    source.attach(REPO, PR)
    run = source.status(f"actions-{RUN}")
    m.RunStatus.model_validate(run.model_dump())  # valid against the contract
    assert run.status == "complete" and run.mode == "actions" and run.notice is None and run.current is None
    assert run.source == m.SourceRef(repo=REPO, ref=json.loads((FIX / "run.json").read_text())["head_sha"])
    assert run.pr is not None
    assert run.pr.prUrl.endswith("/pull/2") and run.pr.runUrl.endswith(f"/actions/runs/{RUN}")
    assert run.pr.state == "open" and run.pr.checkState == "complete" and run.pr.postMergeState == "waiting for merge"
    assert [s.id for s in run.stages] == [
        "checkout", "install", "baseline", "shuffled", "isolated", "bisection", "retrieval", "verdict", "pr-comment"]
    assert all(s.state == "done" for s in run.stages)
    stage = {s.id: s for s in run.stages}
    assert stage["shuffled"].detail == "10 runs, seeds 1 to 10, 0 tests failed at least once"  # the engine's own text
    assert stage["baseline"].detail == "1 run in default order, 0 tests failed"
    assert stage["checkout"].tool == "GitHub Actions" and stage["pr-comment"].tool == "GitHub API"
    assert run.counters.model_dump() == {"runsDone": 10, "runsTotal": 10, "failures": 0, "flagged": 0}


def test_a_clean_run_still_shows_whole_suite_dots(source):
    source.attach(REPO, PR)
    run = source.status(f"actions-{RUN}")
    rows = {r.label: r for r in run.matrix}
    assert rows["Baseline"].cells == ["pass"]
    assert rows["Shuffled"].cells == ["pass"] * 10
    assert "seeds 1 to 10" in rows["Shuffled"].summary


def test_findings_and_tree_come_from_the_finished_artifact(source):
    run_id = source.attach(REPO, PR)
    assert json.loads(source.findings_json(run_id)) == []
    tree = m.TreeData.model_validate_json(source.tree_json(run_id))
    assert tree.root.faults == 0 and tree.sharedState == []


def test_responses_are_cached_for_about_three_seconds(tmp_path: Path):
    """An unfinished run is re-read at most once per 3 s however often the console polls."""
    jobs = load("jobs.json")
    for job in jobs["jobs"]:
        if job["name"].endswith("analyze"):
            job.update(status="in_progress", conclusion=None, completed_at=None)
    run = load("run.json") | {"status": "in_progress", "conclusion": None}
    gh = FakeGitHub({f"/actions/runs/{RUN}/jobs": jobs, f"/actions/runs/{RUN}": run})
    clock = Clock()
    src = ActionsRunSource(GitHubApi("t", clock=clock, transport=httpx.MockTransport(gh.handler)), tmp_path / "runs")
    run_id = src.attach(REPO, PR)
    first = src.status(run_id)
    assert first.status == "running"
    before = len(gh.requests)
    for _ in range(5):  # the console polls every 2 s; the backend sees these within one cache window
        src.status(run_id)
    assert len(gh.requests) == before, "polls inside the cache window must not reach GitHub"
    clock.now += 3.1
    src.status(run_id)
    assert len(gh.requests) > before, "after about 3 s the data is refreshed"
    assert sum(1 for r in gh.requests[before:] if "/jobs" in r) == 1


def test_a_finished_run_is_frozen_and_costs_no_more_requests(source):
    run_id = source.attach(REPO, PR)
    source.status(run_id)
    spent = len(source.gh.requests)  # type: ignore[attr-defined]
    for _ in range(20):
        source.clock.now += 10  # type: ignore[attr-defined]
        source.status(run_id)
        source.findings_json(run_id)
    assert len(source.gh.requests) == spent  # type: ignore[attr-defined]


def test_reading_a_finished_run_stays_far_inside_the_documented_hourly_limit(source):
    run_id = source.attach(REPO, PR)
    source.status(run_id)
    assert source.api.used_this_hour() < 30, "one finished scan must cost a few dozen requests, not hundreds"


def test_the_budget_plans_for_one_thousand_requests_an_hour():
    clock = Clock()
    api = GitHubApi("t", clock=clock, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"n": 1})))
    allowed = 0
    with pytest.raises(BudgetExhausted):
        for i in range(2000):
            api.get(f"/x/{i}")
            allowed += 1
    assert allowed == 950, "1,000 per hour minus a reserve of 50"
    clock.now += 3601  # the window slides: requests are allowed again an hour later
    api.get("/x/again")


def test_when_the_budget_is_used_up_the_last_data_is_shown_with_a_notice(tmp_path: Path):
    jobs = load("jobs.json")
    for job in jobs["jobs"]:
        if job["name"].endswith("analyze"):
            job.update(status="in_progress", conclusion=None, completed_at=None)
    run = load("run.json") | {"status": "in_progress", "conclusion": None}
    gh = FakeGitHub({f"/actions/runs/{RUN}/jobs": jobs, f"/actions/runs/{RUN}": run})
    clock = Clock()
    api = GitHubApi("t", clock=clock, budget=80, reserve=10, transport=httpx.MockTransport(gh.handler))  # 70 requests
    src = ActionsRunSource(api, tmp_path / "runs")
    run_id = src.attach(REPO, PR)
    assert src.status(run_id).status == "running"
    used_by_one_read = api.used_this_hour()
    assert used_by_one_read < 40
    with pytest.raises(BudgetExhausted):  # something else uses up the rest of the hour's budget
        for i in range(1000):
            api.get(f"/repos/{REPO}/pulls/{PR}?n={i}")
    clock.now += 4  # past the cache window, so GitHub would be asked again
    shown = src.status(run_id)
    assert shown.notice is not None and shown.notice.kind == "actions-unavailable"
    assert "1000 requests per hour" in shown.notice.detail and "70 requests used" in shown.notice.detail
    assert shown.stages, "the last good data is still shown"


def test_a_cancelled_run_is_stopped_early_with_no_verdict(tmp_path: Path):
    run = load("run.json") | {"conclusion": "cancelled"}
    jobs = load("jobs.json")
    for job in jobs["jobs"]:
        if job["name"].endswith("comment"):
            job.update(conclusion="cancelled", steps=[])
    gh = FakeGitHub({f"/actions/runs/{RUN}": run, f"/actions/runs/{RUN}/jobs": jobs,
                     f"/actions/runs/{RUN}/artifacts": {"total_count": 0, "artifacts": []}})
    src = ActionsRunSource(GitHubApi("t", transport=httpx.MockTransport(gh.handler)), tmp_path / "runs")
    run_id = src.attach(REPO, PR)
    status = src.status(run_id)
    assert status.status == "failed" and status.notice is not None and status.notice.kind == "scan-incomplete"
    assert "cancelled" in status.notice.detail and "No verdict is shown" in status.notice.detail
    from flakeguard.console.runs import Refused

    with pytest.raises(Refused, match="stopped early"):
        src.findings_json(run_id)


def test_github_errors_become_api_errors(tmp_path: Path):
    gh = FakeGitHub({f"/pulls/{PR}": 404})
    src = ActionsRunSource(GitHubApi("t", transport=httpx.MockTransport(gh.handler)), tmp_path / "runs")
    with pytest.raises(ApiError) as e:
        src.attach(REPO, PR)
    assert e.value.status == 404


MID = Path(__file__).parent / "data" / "actions" / "act1-run-44877437008"


def mid_run_source(tmp_path: Path, snapshot: str, finished_artifacts: set[str]) -> tuple[ActionsRunSource, FakeGitHub]:
    """A real mid-run job listing (captured while PR #3 was being scanned), served as the run."""
    jobs = json.loads((MID / snapshot).read_text(encoding="utf-8"))
    run = load("run.json") | {"status": "in_progress", "conclusion": None}
    listing = load("artifacts.json")
    listing["artifacts"] = [a for a in listing["artifacts"] if a["name"] in finished_artifacts]
    gh = FakeGitHub({f"/actions/runs/{RUN}/jobs": jobs, f"/actions/runs/{RUN}": run,
                     f"/actions/runs/{RUN}/artifacts": listing})
    src = ActionsRunSource(GitHubApi("t", transport=httpx.MockTransport(gh.handler)), tmp_path / "runs")
    return src, gh


SEED_ARTIFACTS = {"junit-baseline"} | {f"junit-shuffled-{i}" for i in range(1, 11)}


def test_while_the_engine_installs_the_console_says_what_the_run_is_doing(tmp_path: Path):
    """Real snapshot: the analyze job was installing the engine, which is not a stage id."""
    src, _ = mid_run_source(tmp_path, "jobs-analyze-deps.json", SEED_ARTIFACTS)
    run = src.status(src.attach(REPO, PR))
    assert run.status == "running" and run.current is not None
    assert run.current.condition == "Installing dependencies"
    stage = {s.id: s for s in run.stages}
    assert stage["shuffled"].state == "done" and stage["isolated"].state == "pending"


def test_a_snapshot_with_the_analysis_running_names_the_stage(tmp_path: Path):
    src, _ = mid_run_source(tmp_path, "jobs-analyze-retrieval.json", SEED_ARTIFACTS)
    run = src.status(src.attach(REPO, PR))
    assert run.current is not None and run.current.condition == "Retrieval"
    assert {s.id: s.state for s in run.stages}["retrieval"] == "running"


def test_seed_jobs_in_progress_show_their_seeds_and_only_finished_seeds_get_a_mark(tmp_path: Path):
    """Real snapshot taken about 25 s in: seeds 4, 5, 6 and 8 had finished, six were still running,
    and the scan job was still installing."""
    src, _ = mid_run_source(tmp_path, "jobs-seeds-running.json", {f"junit-shuffled-{i}" for i in (4, 5, 6, 8)})
    run = src.status(src.attach(REPO, PR))
    assert run.current is not None
    assert run.current.condition == "Shuffled order · seeds 1, 2, 3, 7, 9, 10 running"
    assert run.counters.runsDone == 4 and run.counters.runsTotal == 10
    shuffled = next(r for r in run.matrix if r.label == "Shuffled")
    assert shuffled.cells == ["none", "none", "none", "pass", "pass", "pass", "none", "pass", "none", "none"]
    stage = {s.id: s for s in run.stages}
    assert stage["shuffled"].state == "running" and stage["install"].state == "running"
    assert stage["shuffled"].detail.startswith("4 of 10 runs done (seeds 1 to 10)")
