"""GitHub Actions mode: show a real ``scan.yml`` run as a ``RunStatus``.

``ActionsRunSource`` reads three things from the GitHub API and maps them onto the console:

* jobs and steps: ``scan / scan`` (steps ``checkout``, ``install``, ``baseline``), one job
  ``shuffled (seed N)`` per seed, ``scan / analyze`` (steps ``isolated``, ``bisection``,
  ``retrieval``, ``verdict``) and ``scan / comment`` (step ``pr-comment``). Names are matched by
  their last segment, because GitHub prefixes them with the caller's job id.
* artifacts: ``junit-baseline`` and ``junit-shuffled-N`` (read while the run is still going, to
  fill the dot matrix for the followed test) and ``flakeguard-console`` (the finished
  ``run.json``, ``findings.json`` and ``tree.json``).
* the pull request, for the title, state and links.

Request budget. GitHub documents 1,000 requests per hour per repository for ``GITHUB_TOKEN``
(a request made with it from inside a run reported 5,000 on 2026-11-21, but the documented number
is what this plans for). Every response is cached for ``CACHE_SECONDS``; artifacts are listed only
when the number of finished jobs changes; a finished run is frozen and costs no more requests;
and requests stop at ``BUDGET_PER_HOUR`` minus a reserve.
"""

from __future__ import annotations

import functools
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import zipfile
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from flakeguard.console import models as m
from flakeguard.console.live import (
    STAGES,
    failing_tests,
    focus_test,
    matrix_rows,
    plural,
    runs_of,
    stopped_early,
)
from flakeguard.runner.matrix import SliceResult, parse_junit_xml
from flakeguard.runner.matrix import TestRunOutcome as RunOutcome

API_URL = "https://api.github.com"
CACHE_SECONDS = 3.0
PR_CACHE_SECONDS = 30.0  # a pull request's title and state change rarely
BUDGET_PER_HOUR = 1000  # the documented limit for GITHUB_TOKEN
BUDGET_RESERVE = 50
ACTIONS_ID = re.compile(r"^actions-\d+$")
TARGET = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<pr>\d+)$")
TOOLS = {sid: tool for sid, _name, tool, _detail in STAGES}
TOOLS.update({"checkout": "GitHub Actions", "install": "pip", "pr-comment": "GitHub API"})
NAMES = {sid: name for sid, name, _tool, _detail in STAGES}
JOB_STEPS = {
    "scan": ("checkout", "install", "baseline"),
    "analyze": ("isolated", "bisection", "retrieval", "verdict"),
    "comment": ("pr-comment",),
}
CALLER_WORKFLOW = "flakeguard.yml"
# Workflow steps that are not stage ids, in words a person can follow while they run.
SETUP_STEPS = {
    "plan": "Planning the run", "python": "Setting up Python", "get-code": "Fetching the code",
    "get-target": "Fetching the repository under test", "get-engine": "Fetching the FlakeGuard engine",
    "deps": "Installing dependencies", "download": "Downloading the run results", "upload": "Uploading the results",
}


def is_actions_id(run_id: str) -> bool:
    return bool(ACTIONS_ID.match(run_id))


class BudgetExhausted(Exception):
    """No requests left in this hour's budget."""


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class NoRun(Exception):
    """There is no FlakeGuard run for that pull request (yet). The message is for the person."""


@functools.lru_cache(maxsize=1)
def _gh_cli_token() -> str | None:
    """The gh CLI's token, looked up once per process."""
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def github_token() -> str | None:
    """The backend's own token: GITHUB_TOKEN, GH_TOKEN, or the gh CLI's. Never sent to the browser."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or _gh_cli_token()


class GitHubApi:
    """GET-only GitHub client with a short cache and an hourly request budget."""

    def __init__(
        self, token: str, *, base: str = API_URL, clock: Callable[[], float] = time.monotonic,
        budget: int = BUDGET_PER_HOUR, reserve: int = BUDGET_RESERVE,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base = base.rstrip("/")
        self._clock = clock
        self._limit = max(1, budget - reserve)
        self._window: deque[float] = deque()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._frozen: dict[str, bytes | Any] = {}
        self._lock = threading.Lock()
        self.requests_made = 0
        self._http = httpx.Client(
            timeout=20, follow_redirects=True, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )

    def used_this_hour(self) -> int:
        now = self._clock()
        while self._window and now - self._window[0] > 3600:
            self._window.popleft()
        return len(self._window)

    def _spend(self) -> None:
        if self.used_this_hour() >= self._limit:
            raise BudgetExhausted(f"{self._limit} requests used in the last hour")
        self._window.append(self._clock())
        self.requests_made += 1

    def _request(self, path: str) -> httpx.Response:
        try:
            resp = self._http.get(f"{self.base}{path}")
        except httpx.HTTPError as e:
            raise ApiError(503, f"Could not reach GitHub: {e}") from e
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text[:200])
        return resp

    def get(self, path: str, *, ttl: float = CACHE_SECONDS) -> Any:
        """JSON for ``path``. Fresh within ``ttl`` seconds of the last real request for it."""
        with self._lock:
            hit = self._cache.get(path)
            if hit and self._clock() - hit[0] < ttl:
                return hit[1]
            self._spend()
        resp = self._request(path)
        data = resp.json()
        with self._lock:
            self._cache[path] = (self._clock(), data)
        return data

    def download(self, path: str) -> bytes:
        """A file (an artifact zip). Artifacts never change, so it is fetched once."""
        with self._lock:
            if path in self._frozen:
                return self._frozen[path]
            self._spend()
        resp = self._request(path)
        with self._lock:
            self._frozen[path] = resp.content
        return resp.content


def short_name(job_name: str) -> str:
    """'scan / shuffled (seed 3)' -> 'shuffled (seed 3)'."""
    return job_name.split(" / ")[-1]


def step_state(step: dict) -> str:
    status, conclusion = step.get("status"), step.get("conclusion")
    if status == "in_progress":
        return "running"
    if status == "completed":
        if conclusion == "success":
            return "done"
        if conclusion in ("failure", "cancelled", "timed_out"):
            return "failed"
    return "pending"  # queued, pending, or skipped


def _seconds(start: str | None, end: str | None) -> str | None:
    if not start or not end:
        return None
    from datetime import datetime

    delta = (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
    return "under 1 s" if delta < 1 else f"{round(delta)} s"


def _junit_slice(data: bytes, filename: str, mode: str, iteration: int, seed: int | None) -> SliceResult:
    with zipfile.ZipFile(io.BytesIO(data)) as z, tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_bytes(z.read(filename))
        outcomes: list[RunOutcome] = parse_junit_xml(path)
    return SliceResult(mode=mode, iteration=iteration, exit_code=0, duration_s=0.0, outcomes=outcomes, seed=seed)


class ActionsRunSource:
    def __init__(self, api: GitHubApi, root: Path) -> None:
        self.api = api
        self.root = root
        self._final: dict[str, m.RunStatus] = {}
        self._last: dict[str, m.RunStatus] = {}
        self._head: dict[str, str] = {}
        self._files: dict[str, dict[str, bytes]] = {}

    # ----------------------------------------------------------------- attach

    def attach(self, repo: str, pr_number: int) -> str:
        """Find the newest FlakeGuard run for a pull request and remember it as ``actions-<id>``."""
        pr = self.api.get(f"/repos/{repo}/pulls/{pr_number}", ttl=PR_CACHE_SECONDS)
        sha = pr["head"]["sha"]
        runs = self.api.get(f"/repos/{repo}/actions/runs?event=pull_request&head_sha={sha}&per_page=30")
        mine = [r for r in runs["workflow_runs"] if r["path"].endswith(f"/{CALLER_WORKFLOW}")]
        if not mine:
            raise NoRun(
                f"No FlakeGuard run exists for {repo}#{pr_number} at commit {sha[:7]} yet. "
                "It starts when the pull request is opened or updated."
            )
        run = max(mine, key=lambda r: (r["created_at"], r["id"]))
        run_id = f"actions-{run['id']}"
        folder = self.root / run_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(
            json.dumps({"repo": repo, "run_id": run["id"], "pr_number": pr_number}, indent=2), encoding="utf-8")
        return run_id

    def _meta(self, run_id: str) -> dict:
        path = self.root / run_id / "meta.json"
        if not is_actions_id(run_id) or not path.is_file():
            from flakeguard.console.store import NotFound

            raise NotFound(f"There is no run called {run_id}.")
        return json.loads(path.read_text(encoding="utf-8"))

    # ----------------------------------------------------------------- status

    def status(self, run_id: str) -> m.RunStatus:
        run = self._status(run_id)
        head = self._head.get(run_id)
        if head is None:
            return run
        return run.model_copy(update={"source": m.SourceRef(repo=self._meta(run_id)["repo"], ref=head)})

    def _status(self, run_id: str) -> m.RunStatus:
        if run_id in self._final:
            return self._final[run_id]
        meta = self._meta(run_id)
        try:
            run = self._build(run_id, meta)
        except BudgetExhausted as e:
            last = self._last.get(run_id)
            if last is None:
                raise
            return last.model_copy(update={"notice": m.Notice(
                kind="actions-unavailable",
                detail=f"GitHub API budget reached ({e}; planning for {BUDGET_PER_HOUR} requests per hour). "
                       "Showing the last data until the hour allows more requests.")})
        self._last[run_id] = run
        return run

    def _build(self, run_id: str, meta: dict) -> m.RunStatus:
        repo, rid = meta["repo"], meta["run_id"]
        run = self.api.get(f"/repos/{repo}/actions/runs/{rid}")
        self._head[run_id] = run["head_sha"]  # the pull request's head commit, which GitHub can show
        jobs = self.api.get(f"/repos/{repo}/actions/runs/{rid}/jobs?per_page=100")["jobs"]
        pr = self.api.get(f"/repos/{repo}/pulls/{meta['pr_number']}", ttl=PR_CACHE_SECONDS)
        finished = run["status"] == "completed"
        by_name = {short_name(j["name"]): j for j in jobs}
        seed_jobs = sorted(
            (j for j in jobs if short_name(j["name"]).startswith("shuffled (seed ")),
            key=lambda j: int(re.search(r"seed (\d+)", j["name"]).group(1)),  # type: ignore[union-attr]
        )
        slices = self._slices(repo, rid, run, jobs, seed_jobs)
        console = self._console_files(repo, rid, jobs, finished)

        stages = [self._stage(sid, by_name, seed_jobs, slices, console) for sid, *_ in STAGES]
        pr_info = self._pr_info(repo, pr, run)
        shuffled_n = len(seed_jobs)
        shuf = runs_of(slices, "shuffled")
        focus = focus_test(slices)

        failed_job = next((j for j in jobs if j.get("conclusion") in ("failure", "timed_out")), None)
        if finished:
            if console is not None and run["conclusion"] == "success":
                final = m.RunStatus.model_validate_json(console["run.json"])
                done = final.model_copy(update={
                    "id": run_id, "mode": "actions", "pr": pr_info, "notice": None, "current": None,
                    "matrix": final.matrix or matrix_rows(slices, shuffled_n),  # clean run: whole-suite dots
                    "stages": [self._finalise(s, final) for s in stages],
                })
                self._files[run_id] = console
                self._final[run_id] = done
                return done
            # A run that failed or was cancelled is final. A run that says success but has no result yet
            # (the artifact list can lag) is not frozen, so the next poll looks again.
            return self._failed(run_id, repo, run, stages, shuffled_n, pr_info, slices, failed_job,
                                freeze=run["conclusion"] != "success")

        counters = m.Counters(
            runsDone=sum(1 for j in seed_jobs if j["status"] == "completed" and j["conclusion"] == "success"),
            runsTotal=shuffled_n,
            failures=sum(
                1 for r in shuf if focus and any(o.test_id == focus and o.outcome in ("FAIL", "ERROR") for o in r.outcomes)
            ) if focus else sum(1 for r in shuf if any(o.outcome in ("FAIL", "ERROR") for o in r.outcomes)),
            flagged=len(failing_tests(slices)),
        )
        return m.RunStatus(
            id=run_id, target=f"{repo}#{meta['pr_number']}", mode="actions", status="running", pr=pr_info,
            stages=stages, current=self._current(stages, seed_jobs, focus, jobs), counters=counters,
            matrix=matrix_rows(slices, shuffled_n), notice=None,
        )

    # ---------------------------------------------------------------- pieces

    def _slices(self, repo: str, rid: int, run: dict, jobs: list[dict], seed_jobs: list[dict]) -> list[SliceResult]:
        """Baseline and shuffled runs, read from the JUnit artifacts of the jobs that have finished."""
        done_jobs = [j for j in jobs if j["status"] == "completed"]
        key = f"{repo}:{rid}:{len(done_jobs)}"
        listing = self.api.get(f"/repos/{repo}/actions/runs/{rid}/artifacts?per_page=100&_k={key}", ttl=3600) \
            if done_jobs else {"artifacts": []}
        wanted = {a["name"]: a["id"] for a in listing["artifacts"]}
        out: list[SliceResult] = []
        if "junit-baseline" in wanted:
            data = self.api.download(f"/repos/{repo}/actions/artifacts/{wanted['junit-baseline']}/zip")
            out.append(_junit_slice(data, "junit_baseline.xml", "baseline", 1, None))
        seeds = [int(re.search(r"seed (\d+)", j["name"]).group(1)) for j in seed_jobs]  # type: ignore[union-attr]
        for i, seed in enumerate(seeds, 1):
            name = f"junit-shuffled-{i}"
            if name in wanted:
                data = self.api.download(f"/repos/{repo}/actions/artifacts/{wanted[name]}/zip")
                out.append(_junit_slice(data, f"junit_shuffled_{i}.xml", "shuffled", i, seed))
        return out

    def _console_files(self, repo: str, rid: int, jobs: list[dict], finished: bool) -> dict[str, bytes] | None:
        analyze = next((j for j in jobs if short_name(j["name"]) == "analyze"), None)
        if not (finished or (analyze and analyze["status"] == "completed")):
            return None
        listing = self.api.get(f"/repos/{repo}/actions/runs/{rid}/artifacts?per_page=100&_k=final", ttl=CACHE_SECONDS)
        art = next((a for a in listing["artifacts"] if a["name"] == "flakeguard-console"), None)
        if art is None:
            return None
        data = self.api.download(f"/repos/{repo}/actions/artifacts/{art['id']}/zip")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return {n: z.read(n) for n in z.namelist()}

    def _stage(self, sid: str, by_name: dict, seed_jobs: list[dict], slices: list[SliceResult],
               console: dict[str, bytes] | None) -> m.Stage:
        tool, name = TOOLS[sid], NAMES[sid]
        if sid == "shuffled":
            states = [("done" if j["conclusion"] == "success" else "failed") if j["status"] == "completed"
                      else ("running" if j["status"] == "in_progress" else "pending") for j in seed_jobs]
            if not seed_jobs:
                return m.Stage(id=sid, name=name, detail="Waiting to start", tool=tool, time=None, state="pending")
            state = ("failed" if "failed" in states else "done" if all(s == "done" for s in states)
                     else "running" if any(s in ("running", "done") for s in states) else "pending")
            seeds = [int(re.search(r"seed (\d+)", j["name"]).group(1)) for j in seed_jobs]  # type: ignore[union-attr]
            span = f"seeds {seeds[0]} to {seeds[-1]}" if len(seeds) > 1 else f"seed {seeds[0]}"
            n_done = states.count("done")
            bad = failing_tests(slices, ("shuffled",))
            detail = f"{n_done} of {len(seed_jobs)} runs done ({span}), {plural(len(bad), 'test')} failed at least once"
            starts = [j["started_at"] for j in seed_jobs if j.get("started_at")]
            ends = [j["completed_at"] for j in seed_jobs if j.get("completed_at")]
            elapsed = _seconds(min(starts), max(ends)) if state == "done" and starts and ends else None
            return m.Stage(id=sid, name=name, detail=detail, tool=tool, time=elapsed, state=state)  # type: ignore[arg-type]
        job_key = next(k for k, steps in JOB_STEPS.items() if sid in steps)
        job = by_name.get(job_key)
        step = next((s for s in (job or {}).get("steps", []) if s["name"] == sid), None)
        if step is None:
            return m.Stage(id=sid, name=name, detail="Waiting to start", tool=tool, time=None, state="pending")
        state = step_state(step)
        detail = {"done": "Done", "running": "Running", "pending": "Waiting to start",
                  "failed": "Failed. Open the Actions run to see why."}[state]
        elapsed = _seconds(step.get("started_at"), step.get("completed_at")) if state in ("done", "failed") else None
        return m.Stage(id=sid, name=name, detail=detail, tool=tool, time=elapsed, state=state)  # type: ignore[arg-type]

    @staticmethod
    def _finalise(stage: m.Stage, final: m.RunStatus) -> m.Stage:
        """On a finished run the engine's own stage text (real counts) replaces the generic text."""
        engine = {s.id: s for s in final.stages}.get(stage.id)
        if engine is None or stage.id in ("checkout", "install", "pr-comment"):
            return stage
        return stage.model_copy(update={"detail": engine.detail})

    @staticmethod
    def _current(stages: list[m.Stage], seed_jobs: list[dict], focus: str | None, jobs: list[dict]) -> m.Current | None:
        running = [s for s in stages if s.state == "running"]
        if not running:
            # Between stages the run is busy with setup steps (installing the engine takes about 30 s).
            for job in jobs:
                if job["status"] != "in_progress":
                    continue
                for step in job.get("steps", []):
                    if step.get("status") == "in_progress":
                        return m.Current(test=focus or "Whole suite",
                                         condition=SETUP_STEPS.get(step["name"], f"Step {step['name']}"))
            return None
        # Stages can overlap (the scan job installs while the seed jobs run); the seeds say more.
        stage = next((s for s in running if s.id == "shuffled"), running[0])
        if stage.id == "shuffled":
            live_seeds = [re.search(r"seed (\d+)", j["name"]).group(1) for j in seed_jobs if j["status"] == "in_progress"]  # type: ignore[union-attr]
            cond = "Shuffled order · seeds " + ", ".join(live_seeds) + " running" if live_seeds else "Shuffled order"
        else:
            cond = stage.name
        return m.Current(test=focus or "Whole suite", condition=cond)

    @staticmethod
    def _pr_info(repo: str, pr: dict, run: dict) -> m.PrInfo:
        state = "merged" if pr.get("merged") else pr["state"]
        check = {"queued": "queued", "in_progress": "in progress", "pending": "queued"}.get(run["status"])
        if check is None:
            check = "complete" if run.get("conclusion") == "success" else (run.get("conclusion") or "complete")
        return m.PrInfo(
            number=pr["number"], title=pr["title"], state=state, checkState=check,  # type: ignore[arg-type]
            postMergeState="waiting for merge" if state == "open" else ("merged" if state == "merged" else "not applicable"),
            prUrl=pr["html_url"], runUrl=run["html_url"],
        )

    def _failed(self, run_id: str, repo: str, run: dict, stages: list[m.Stage], shuffled_n: int,
                pr_info: m.PrInfo, slices: list[SliceResult], failed_job: dict | None, *, freeze: bool) -> m.RunStatus:
        conclusion = run.get("conclusion")
        if conclusion == "cancelled":
            why = ("The GitHub Actions run was cancelled. A newer push to the pull request replaces a scan that is "
                   "still running, or someone cancelled it.")
        elif failed_job is not None:
            bad = next((s["name"] for s in failed_job.get("steps", []) if s.get("conclusion") == "failure"), None)
            why = f"The GitHub Actions run failed in {short_name(failed_job['name'])}" + (f", step {bad}." if bad else ".")
        else:
            why = f"The GitHub Actions run ended with '{conclusion}' and produced no result."
        base = m.RunStatus(
            id=run_id, target=f"{repo}#{pr_info.number}", mode="actions", status="running", pr=pr_info,
            stages=stages, current=None,
            counters=m.Counters(runsDone=len(runs_of(slices, "shuffled")), runsTotal=shuffled_n, failures=0,
                                flagged=len(failing_tests(slices))),
            matrix=matrix_rows(slices, shuffled_n), notice=None,
        )
        out = stopped_early(base, f"{why} No verdict is shown.")
        if freeze:
            self._final[run_id] = out
        return out

    # ---------------------------------------------------------- finished files

    def findings_json(self, run_id: str) -> str:
        return self._file(run_id, "findings.json")

    def tree_json(self, run_id: str) -> str:
        return self._file(run_id, "tree.json")

    def _file(self, run_id: str, name: str) -> str:
        from flakeguard.console.runs import Refused

        run = self.status(run_id)
        if run.status == "running":
            raise Refused("The scan has not finished, so there is no verdict yet.", 409)
        if run.status != "complete" or run_id not in self._files:
            raise Refused("The scan stopped early, so there is no verdict.", 409)
        return self._files[run_id][name].decode("utf-8")


_source: ActionsRunSource | None = None
_source_lock = threading.Lock()


def actions_source(root: Path) -> ActionsRunSource | None:
    """The shared source, or None when the backend has no GitHub token."""
    global _source
    with _source_lock:
        if _source is None:
            token = github_token()
            if token is None:
                return None
            _source = ActionsRunSource(GitHubApi(token), root)
        return _source


def set_actions_source(value: ActionsRunSource | None) -> None:
    global _source
    _source = value
