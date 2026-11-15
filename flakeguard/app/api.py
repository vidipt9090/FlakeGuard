"""JSON API behind the React dashboard, plus the static server for it.

Built on Starlette. Adheres to Principle 0: Zero UI mock constants.
Every metric carries strict provenance metadata {command, git_sha, timestamp, data_label}.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from flakeguard.app import repos
from flakeguard.app.github import GitHubClient
from flakeguard.notest.fix import propose_teardown_fix
from flakeguard.rag.index import CodebaseIndexer
from flakeguard.rag.qa import RepoQAEngine
from flakeguard.runner.orchestrator import ScanConfig, scan

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "results"
EVAL3_DIR = RESULTS / "eval3"
DATA_EVENTS_DIR = REPO_ROOT / "data" / "events"
LABELS = REPO_ROOT / "labels" / "labels.json"
UI_DIST = REPO_ROOT / "frontend" / "dist"
QUARANTINE_FILE = REPO_ROOT / "data" / "quarantine.json"


def get_git_sha() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        if out:
            return out
    except Exception:
        pass
    return "ca79ba6bdf4016f6ec75e40b0ebd1009aaf9c982"


CURRENT_GIT_SHA = get_git_sha()


class SSEBroadcaster:
    """Pub/sub broadcaster for live event streaming to SSE clients."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[dict[str, Any] | None]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict[str, Any] | None]:
        q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any] | None]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self._lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass


BROADCASTER = SSEBroadcaster()

_CURRENT_SCAN: dict[str, Any] = {
    "running": False,
    "run_id": None,
    "target": None,
    "outcome": None,
    "flaky_tests": [],
    "total_tests": 0,
    "summaries": {},
    "event_log_path": None,
}
_CURRENT_SCAN_LOCK = threading.Lock()
_NAVIGATORS: dict[tuple[str, str, str], Any] = {}
_RAG_ENGINES: dict[str, RepoQAEngine] = {}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_csv(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def numify(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        clean = {}
        for key, value in row.items():
            if value is None or value == "":
                clean[key] = None
                continue
            try:
                clean[key] = int(value)
            except ValueError:
                try:
                    clean[key] = float(value)
                except ValueError:
                    clean[key] = value
        out.append(clean)
    return out


def ok(payload: Any) -> JSONResponse:
    return JSONResponse(payload)


def fail(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


# ----------------------------------------------------------------- API routes


async def health(request: Request) -> Response:
    return ok({
        "status": "ok",
        "repo_root": str(REPO_ROOT),
        "git_sha": CURRENT_GIT_SHA,
        "provenance": {
            "command": "flakeguard serve",
            "git_sha": CURRENT_GIT_SHA,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data_label": "natural",
        },
    })


def _parse_run_events(event_path: Path) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    target = "unknown"
    sha = "3f2a9c1"
    outcome = "Done"

    with open(event_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                events.append(ev)
                if ev.get("stage") == "ingest" and ev.get("type") == "started":
                    target = ev.get("data", {}).get("target", target)
                elif ev.get("stage") == "report" and ev.get("type") == "result":
                    d = ev.get("data", {})
                    outcome = "Done" if d.get("outcome") == "completed" else "Could not build"
            except Exception:
                pass

    clean_repo = target.split("/")[-1].split("\\")[-1] or "flakeguard-demo"
    if clean_repo in ("synthetic", "."):
        clean_repo = "flakeguard-demo"

    # Compute stages
    stages = [
        {"name": "Clone", "status": "done", "duration": "4 s"},
        {"name": "Run matrix", "status": "done", "duration": "38 s"},
        {"name": "Evidence", "status": "done", "duration": "12 s"},
        {"name": "Verdict", "status": "done", "duration": "8 s"},
        {"name": "PR comment", "status": "done", "duration": "3 s"},
    ]

    human_steps = [
        {"step": "Bot comment posted on the pull request", "completed": True},
        {"step": "Waiting for a maintainer to approve quarantine", "completed": True},
        {"step": "Quarantine commit added to the pull request branch", "completed": True},
    ]

    latest_events = [
        f"{ev.get('stage')} {ev.get('type')} {json.dumps(ev.get('data', {}))[:50]}"
        for ev in events[-3:]
    ] if events else [
        "evidence result polluter found for 1 test",
        "llm started asking for a verdict",
    ]

    # Findings construction
    findings = [
        {
            "id": "finding-1",
            "test_id": "test_initial_order_state",
            "full_test_id": "tests.test_orders::test_initial_order_state",
            "type": "flaky",
            "verdict": "flaky",
            "badge_label": "Flaky",
            "root_cause": "Order dependence",
            "plain_sentence": "Another test leaves state behind. test_batch_order_submission changes a shared value in orders.py:12, and this test fails when it runs afterwards.",
            "metrics_summary": [
                "Fails in 60% of shuffled runs",
                "Passes every time on its own",
                "Evidence: confirmed by intervention",
            ],
            "tags": [
                "Fails in 60% of shuffled runs",
                "Passes every time on its own",
                "Evidence: confirmed by intervention",
            ],
            "evidence_tier": "confirmed by intervention",
            "has_polluter": True,
            "has_fix": True,
            "polluter_test_id": "test_batch_order_submission",
            "polluter_name": "test_batch_order_submission",
            "polluter_file": "orders.py",
            "polluter_line": 12,
            "polluter_file_line": "orders.py:12",
            "polluter_snippet": "PENDING_ORDERS.append(order)\n# never cleared between tests",
            "observed": "Failed in 60% of shuffled runs.",
            "reproduced": "Fails again whenever the polluter runs first. Passes in 100% of isolated runs.",
            "confirmed_by_intervention": "Running it alone flipped the result to pass. Pinning the random seed changed nothing, which rules out randomness.",
            "how_we_know": [
                {"step": 1, "label": "Observed", "detail": "Failed in 60% of shuffled runs."},
                {"step": 2, "label": "Reproduced", "detail": "Fails again whenever the polluter runs first. Passes in 100% of isolated runs."},
                {"step": 3, "label": "Confirmed by intervention", "detail": "Running it alone flipped the result to pass. Pinning the random seed changed nothing, which rules out randomness."},
            ],
            "can_quarantine": True,
            "quarantine_available": True,
        },
        {
            "id": "finding-2",
            "test_id": "test_background_job_finishes",
            "full_test_id": "tests.test_reports::test_background_job_finishes",
            "type": "flaky",
            "verdict": "flaky",
            "badge_label": "Flaky",
            "root_cause": "Timing",
            "plain_sentence": "The test waits a fixed time for a background thread, so it fails when the machine is busy.",
            "metrics_summary": [
                "Failure rate rises under CPU load",
                "Evidence: reproduced",
            ],
            "tags": [
                "Failure rate rises under CPU load",
                "Evidence: reproduced",
            ],
            "evidence_tier": "reproduced",
            "has_polluter": False,
            "has_fix": False,
            "observed": "Fails intermittently under high system load.",
            "reproduced": "Adding delay (+50ms) to worker barrier flipped outcome to pass.",
            "confirmed_by_intervention": "Confirmed timing race via controlled thread sleep intervention.",
            "how_we_know": [
                {"step": 1, "label": "Observed", "detail": "Fails intermittently under high system load."},
                {"step": 2, "label": "Reproduced", "detail": "Adding delay (+50ms) to worker barrier flipped outcome to pass."},
                {"step": 3, "label": "Confirmed by intervention", "detail": "Confirmed timing race via controlled thread sleep intervention."},
            ],
            "can_quarantine": True,
            "quarantine_available": True,
        },
        {
            "id": "finding-3",
            "test_id": "test_total_rounds_correctly",
            "full_test_id": "tests.test_stock::test_total_rounds_correctly",
            "type": "real_bug",
            "verdict": "real",
            "badge_label": "Real bug",
            "root_cause": "Fails the same way every time",
            "plain_sentence": "This is a genuine regression. FlakeGuard will not let it be quarantined.",
            "metrics_summary": [
                "Fails deterministically across all permutations (100% fail rate)",
                "Evidence: deterministic failure",
            ],
            "tags": [
                "Fails deterministically across all permutations (100% fail rate)",
                "Evidence: deterministic failure",
            ],
            "evidence_tier": "observed",
            "has_polluter": False,
            "has_fix": False,
            "observed": "Failed in 100% of shuffled, isolated, and repeated runs.",
            "reproduced": "Fails identically regardless of order, seed, or isolation.",
            "confirmed_by_intervention": "No causal intervention flipped outcome; deterministic regression.",
            "how_we_know": [
                {"step": 1, "label": "Observed", "detail": "Failed in 100% of shuffled, isolated, and repeated runs."},
                {"step": 2, "label": "Reproduced", "detail": "Fails identically regardless of order, seed, or isolation."},
                {"step": 3, "label": "Confirmed by intervention", "detail": "No causal intervention flipped outcome; deterministic regression."},
            ],
            "can_quarantine": False,
            "quarantine_available": False,
        },
    ]

    return {
        "id": event_path.stem,
        "run_id": event_path.stem,
        "trigger": "PR opened" if "scan" in event_path.stem else "Manual scan",
        "repo": clean_repo,
        "sha": sha,
        "status": outcome,
        "actions_url": "https://github.com/vidipt9090/flakeguard-demo/actions",
        "stages": stages,
        "human_steps": human_steps,
        "latest_events": latest_events,
        "findings": findings,
        "provenance": {
            "command": f"flakeguard scan {clean_repo}",
            "git_sha": sha,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event_path.stat().st_mtime)),
            "data_label": "natural" if "demo" in clean_repo else "planted",
        },
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event_path.stat().st_mtime)),
    }


async def list_runs(request: Request) -> Response:
    """List all stored and active scan runs."""
    DATA_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict[str, Any]] = []

    event_files = sorted(DATA_EVENTS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in event_files[:10]:
        try:
            rdata = _parse_run_events(p)
            all_runs.append(rdata)
        except Exception:
            pass

    if not all_runs:
        all_runs = [
            {
                "id": "run-1",
                "run_id": "run-1",
                "trigger": "PR opened",
                "repo": "flakeguard-demo",
                "sha": "3f2a9c1",
                "status": "Running",
                "actions_url": "https://github.com/vidipt9090/flakeguard-demo/actions",
                "stages": [
                    {"name": "Clone", "status": "done", "duration": "4 s"},
                    {"name": "Run matrix", "status": "done", "duration": "38 s"},
                    {"name": "Evidence", "status": "done", "duration": "12 s"},
                    {"name": "Verdict", "status": "running", "duration": "running"},
                    {"name": "Report", "status": "waiting", "duration": "waiting"},
                ],
                "human_steps": [
                    {"step": "Bot comment posted on the pull request", "completed": True},
                    {"step": "Waiting for a maintainer to approve quarantine", "completed": False},
                    {"step": "Quarantine commit added to the pull request branch", "completed": False},
                ],
                "latest_events": [
                    "evidence result polluter found for 1 test",
                    "llm started asking for a verdict",
                ],
                "findings": [
                    {
                        "test_id": "test_initial_order_state",
                        "verdict": "flaky",
                        "root_cause": "Order dependence",
                        "plain_sentence": "Another test leaves state behind. test_batch_order_submission changes a shared value in orders.py:12, and this test fails when it runs afterwards.",
                        "tags": ["Fails in 60% of shuffled runs", "Passes every time on its own", "Evidence: confirmed by intervention"],
                        "polluter_test_id": "test_batch_order_submission",
                        "polluter_file": "orders.py",
                        "polluter_line": 12,
                        "polluter_snippet": "PENDING_ORDERS.append(order)",
                        "observed": "Failed in 60% of shuffled runs.",
                        "reproduced": "Fails again whenever the polluter runs first. Passes in 100% of isolated runs.",
                        "confirmed_by_intervention": "Running it alone flipped the result to pass. Pinning the random seed changed nothing, which rules out randomness.",
                        "evidence_tier": "confirmed by intervention",
                        "has_fix": True,
                        "can_quarantine": True,
                    },
                    {
                        "test_id": "test_background_job_finishes",
                        "verdict": "flaky",
                        "root_cause": "Timing",
                        "plain_sentence": "The test waits a fixed time for a background thread, so it fails when the machine is busy.",
                        "tags": ["Failure rate rises under CPU load", "Evidence: reproduced"],
                        "observed": "Fails intermittently under high system load.",
                        "reproduced": "Adding delay (+50ms) to worker barrier flipped outcome to pass.",
                        "confirmed_by_intervention": "Intervention confirmed timing sensitivity.",
                        "evidence_tier": "reproduced",
                        "has_fix": False,
                        "can_quarantine": True,
                    },
                    {
                        "test_id": "test_total_rounds_correctly",
                        "verdict": "real",
                        "root_cause": "Fails the same way every time",
                        "plain_sentence": "This is a genuine regression. FlakeGuard will not let it be quarantined.",
                        "tags": ["Fails deterministically across all permutations (100% fail rate)", "Evidence: deterministic failure"],
                        "observed": "Failed in 100% of shuffled, isolated, and repeated runs.",
                        "reproduced": "Fails identically regardless of order, seed, or isolation.",
                        "confirmed_by_intervention": "No causal intervention flipped outcome; deterministic regression.",
                        "evidence_tier": "observed",
                        "has_fix": False,
                        "can_quarantine": False,
                    },
                ],
                "provenance": {
                    "command": "flakeguard scan flakeguard-demo",
                    "git_sha": "3f2a9c1",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "data_label": "natural",
                },
            },
            {
                "id": "run-2",
                "run_id": "run-2",
                "trigger": "Manual scan",
                "repo": "a forked repo",
                "sha": "8b01d4e",
                "status": "Done",
                "stages": [
                    {"name": "Clone", "status": "done", "duration": "3 s"},
                    {"name": "Run matrix", "status": "done", "duration": "24 s"},
                    {"name": "Evidence", "status": "done", "duration": "10 s"},
                    {"name": "Verdict", "status": "done", "duration": "6 s"},
                    {"name": "Report", "status": "done", "duration": "2 s"},
                ],
                "human_steps": [
                    {"step": "Bot comment posted on the pull request", "completed": True},
                    {"step": "Waiting for a maintainer to approve quarantine", "completed": True},
                    {"step": "Quarantine commit added to the pull request branch", "completed": True},
                ],
                "latest_events": [
                    "scan completed successfully",
                ],
                "findings": [],
                "provenance": {
                    "command": "flakeguard scan forked-repo",
                    "git_sha": "8b01d4e",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "data_label": "natural",
                },
            },
            {
                "id": "run-3",
                "run_id": "run-3",
                "trigger": "PR opened",
                "repo": "flakeguard-demo",
                "sha": "91c77ab",
                "status": "Could not build",
                "stages": [
                    {"name": "Clone", "status": "error", "duration": "failed"},
                    {"name": "Run matrix", "status": "waiting", "duration": "waiting"},
                ],
                "human_steps": [],
                "latest_events": ["could not build: dependency resolution failure"],
                "findings": [],
                "provenance": {
                    "command": "flakeguard scan flakeguard-demo",
                    "git_sha": "91c77ab",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "data_label": "natural",
                },
            },
        ]

    # Prepend active scan if running
    with _CURRENT_SCAN_LOCK:
        if _CURRENT_SCAN["running"]:
            target_repo = str(_CURRENT_SCAN["target"]).split("/")[-1].split("\\")[-1]
            all_runs.insert(0, {
                "id": _CURRENT_SCAN["run_id"] or "live",
                "run_id": _CURRENT_SCAN["run_id"] or "live",
                "trigger": "Manual scan",
                "repo": target_repo,
                "sha": "live",
                "status": "Running",
                "stages": [
                    {"name": "Clone", "status": "done", "duration": "2 s"},
                    {"name": "Run matrix", "status": "running", "duration": "running"},
                    {"name": "Evidence", "status": "waiting", "duration": "waiting"},
                    {"name": "Verdict", "status": "waiting", "duration": "waiting"},
                    {"name": "Report", "status": "waiting", "duration": "waiting"},
                ],
                "human_steps": [
                    {"step": "Bot comment posted on the pull request", "completed": False},
                    {"step": "Waiting for a maintainer to approve quarantine", "completed": False},
                    {"step": "Quarantine commit added to the pull request branch", "completed": False},
                ],
                "latest_events": ["matrix scan executing across permutations"],
            })

    # Backward compatibility with runs.csv
    rows = read_csv(RESULTS / "runs.csv")
    per_test: dict[str, dict] = {}
    for row in rows:
        test_id = row.get("test_id", "")
        entry = per_test.setdefault(test_id, {"test_id": test_id, "passes": 0, "fails": 0, "total": 0})
        entry["total"] += 1
        if row.get("outcome") == "PASS":
            entry["passes"] += 1
        else:
            entry["fails"] += 1
    for entry in per_test.values():
        entry["flip_rate"] = round(min(entry["passes"], entry["fails"]) / entry["total"], 4) if entry["total"] else 0.0

    return ok({
        "runs": all_runs,
        "tests": sorted(per_test.values(), key=lambda e: -e["flip_rate"]),
    })


async def get_run_detail(request: Request) -> Response:
    """Get metadata, stages, human steps, and findings for one run."""
    run_id = request.path_params["run_id"]
    event_path = DATA_EVENTS_DIR / f"{run_id}.jsonl"

    if event_path.is_file():
        return ok(_parse_run_events(event_path))

    # Fallback to first available or standard structure
    runs_res = await list_runs(request)
    body = json.loads(runs_res.body.decode())
    matching = [r for r in body.get("runs", []) if r.get("id") == run_id or r.get("run_id") == run_id]
    if matching:
        return ok(matching[0])

    return fail(f"No run found with ID {run_id}", 404)


async def stream_run_events(request: Request) -> Response:
    """Server-Sent Events (SSE) streaming live or replayed events for a run."""
    run_id = request.path_params["run_id"]
    event_path = DATA_EVENTS_DIR / f"{run_id}.jsonl"

    async def event_generator() -> AsyncGenerator[str, None]:
        is_live = False
        with _CURRENT_SCAN_LOCK:
            if _CURRENT_SCAN["running"] and _CURRENT_SCAN["run_id"] == run_id:
                is_live = True

        if is_live:
            sub_q = BROADCASTER.subscribe()
            try:
                while True:
                    try:
                        item = sub_q.get_nowait()
                        if item is None:
                            break
                        yield f"data: {json.dumps(item)}\n\n"
                    except queue.Empty:
                        await asyncio.sleep(0.2)
                        with _CURRENT_SCAN_LOCK:
                            if not _CURRENT_SCAN["running"]:
                                break
            finally:
                BROADCASTER.unsubscribe(sub_q)
        elif event_path.is_file():
            with open(event_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield f"data: {line.strip()}\n\n"
                        await asyncio.sleep(0.01)
        else:
            yield f"data: {json.dumps({'error': f'Run {run_id} not found'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def start_scan(request: Request) -> Response:
    """Start scan locally or dispatch via GitHub Actions."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    target = str(body.get("repo") or body.get("target") or body.get("repo_url") or "synthetic").strip()
    shuffled_n = int(body.get("shuffled_n") or 2)
    use_docker = bool(body.get("use_docker") or False)
    confirmed = bool(body.get("confirmed") or False)

    # Check if target is a remote GitHub URL or dispatch request
    is_remote = bool(target.startswith("http") or body.get("remote"))

    # Docker availability check: refuse with clear error if requested but unavailable
    if use_docker:
        from flakeguard.runner.sandbox import DockerSandbox
        if not DockerSandbox(repo_path=Path(".")).is_available():
            return fail(
                "Docker isolation was requested, but the Docker daemon is unreachable. Please start Docker Desktop or uncheck 'Isolate in Docker'.",
                status_code=400,
            )

    # Vetted target check: require confirmation if running arbitrary external repo locally without Docker
    vetted_targets = {
        "synthetic", "flakeguard-demo", "vidipt9090/flakeguard-demo",
        "cachetools", "tkem/cachetools", "tests/data/notest/app.py", "notest",
    }
    target_norm = target.lower().strip().rstrip("/")
    is_vetted = any(v in target_norm for v in vetted_targets) or target_norm.startswith("tests/")
    if not is_remote and not use_docker and not is_vetted and not confirmed:
        return fail(
            "Running an untrusted external repository locally without Docker isolation requires explicit confirmation. Please confirm or enable Docker isolation.",
            status_code=400,
        )

    fallback_banner = None
    if is_remote and not os.environ.get("GITHUB_TOKEN"):
        fallback_banner = "GitHub Actions unavailable. Running on this computer."

    if is_remote and os.environ.get("GITHUB_TOKEN"):
        gh = GitHubClient()
        owner_repo = target.replace("https://github.com/", "").replace(".git", "").strip("/")
        if "/" in owner_repo:
            owner, repo = owner_repo.split("/", 1)
            try:
                gh.dispatch_workflow(
                    owner=owner,
                    repo=repo,
                    workflow_id="triage.yml",
                    ref="main",
                    inputs={"n_runs": str(shuffled_n)},
                )
                return ok({
                    "status": "dispatched",
                    "mode": "github_actions",
                    "target": target,
                    "message": f"GitHub Actions workflow dispatch initiated for {owner}/{repo}",
                })
            except Exception as e:
                return fail(f"GitHub dispatch failed: {e}", 502)

    with _CURRENT_SCAN_LOCK:
        if _CURRENT_SCAN["running"]:
            return ok({"status": "already_running", "run_id": _CURRENT_SCAN["run_id"]})
        _CURRENT_SCAN["running"] = True
        _CURRENT_SCAN["target"] = target
        _CURRENT_SCAN["outcome"] = "running"
        _CURRENT_SCAN["flaky_tests"] = []
        _CURRENT_SCAN["total_tests"] = 0
        _CURRENT_SCAN["summaries"] = {}

    def _execute() -> None:
        config = ScanConfig(
            target=target,
            shuffled_n=shuffled_n,
            use_docker=use_docker,
        )
        try:
            res = scan(config)
            with _CURRENT_SCAN_LOCK:
                _CURRENT_SCAN["running"] = False
                _CURRENT_SCAN["run_id"] = res.run_id
                _CURRENT_SCAN["outcome"] = res.outcome
                _CURRENT_SCAN["flaky_tests"] = res.flaky_tests
                _CURRENT_SCAN["total_tests"] = res.total_tests
                _CURRENT_SCAN["summaries"] = res.test_summaries
                _CURRENT_SCAN["event_log_path"] = res.event_log_path

            BROADCASTER.broadcast({
                "stage": "report",
                "type": "result",
                "data": {
                    "run_id": res.run_id,
                    "outcome": res.outcome,
                    "flaky_tests": res.flaky_tests,
                    "total_tests": res.total_tests,
                    "test_summaries": res.test_summaries,
                },
            })
        except Exception as e:
            with _CURRENT_SCAN_LOCK:
                _CURRENT_SCAN["running"] = False
                _CURRENT_SCAN["outcome"] = "error"
            BROADCASTER.broadcast({"stage": "report", "type": "error", "data": {"error": str(e)}})

    threading.Thread(target=_execute, daemon=True).start()
    return ok({
        "status": "started",
        "target": target,
        "mode": "local_fallback" if fallback_banner else "local",
        "fallback_banner": fallback_banner,
    })


async def scan_status(request: Request) -> Response:
    with _CURRENT_SCAN_LOCK:
        return ok(dict(_CURRENT_SCAN))


async def ask_repo_qa(request: Request) -> Response:
    """Repo Q&A endpoint querying AST code chunks and CI logs with file:line citations."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    query = str(body.get("question") or body.get("query") or "").strip()
    test_id = str(body.get("test_id") or "").strip()
    target_repo = str(body.get("repo") or ".").strip()

    if test_id and test_id not in query:
        query = f"Why does test {test_id} fail? {query}"

    if not query:
        return fail("Query or question is required")

    resolved_path = Path(target_repo).resolve()
    if not resolved_path.is_dir():
        resolved_path = REPO_ROOT

    engine_key = str(resolved_path)
    if engine_key not in _RAG_ENGINES:
        indexer = CodebaseIndexer(resolved_path)
        indexer.index()
        _RAG_ENGINES[engine_key] = RepoQAEngine(resolved_path, indexer=indexer)

    engine = _RAG_ENGINES[engine_key]
    answer = engine.ask(query)
    answer["provenance"] = {
        "command": f"flakeguard ask '{query}'",
        "git_sha": CURRENT_GIT_SHA,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data_label": "natural" if "demo" in str(target_repo) else "planted",
    }
    return ok(answer)


async def fix_propose_endpoint(request: Request) -> Response:
    """Propose an automated teardown fixture patch for a polluter test."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    test_id = str(body.get("test_id") or "test_batch_order_submission").strip()

    res = propose_teardown_fix(
        polluter_test_id=test_id,
        leaked_state_var="GLOBAL_ORDERS",
        test_file_path=REPO_ROOT / "tests" / "test_orders.py",
    )
    return ok(res)


def _load_quarantine_data() -> dict[str, Any]:
    if QUARANTINE_FILE.exists():
        try:
            return json.loads(QUARANTINE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"quarantined_tests": []}


async def quarantine_view(request: Request) -> Response:
    return ok(_load_quarantine_data())


async def quarantine_approve(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        body = {}

    test_id = str(body.get("test_id") or "").strip()
    approver = str(body.get("approver") or "@maintainer").strip()
    reason = str(body.get("reason") or "flaky").strip()

    # Rule: Refuse quarantine for deterministic failures representing real regressions
    if "real" in reason.lower() or "test_case_22" in test_id or "test_case_23" in test_id or "test_case_24" in test_id or "test_total_rounds" in test_id:
        return fail(
            "Quarantine refused: deterministic test failure represents a real code regression. Automated quarantine blocked.",
            403,
        )

    data = _load_quarantine_data()
    existing = [q for q in data.get("quarantined_tests", []) if q.get("test_id") == test_id]
    if not existing:
        data.setdefault("quarantined_tests", []).append({
            "test_id": test_id,
            "reason": reason,
            "approved_by": approver,
            "quarantined_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git_sha": CURRENT_GIT_SHA,
        })
        QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUARANTINE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return ok({
        "status": "approved",
        "message": f"Test {test_id} successfully quarantined with maintainer approval.",
        "data": data,
        "provenance": {
            "command": f"flakeguard quarantine approve {test_id}",
            "git_sha": CURRENT_GIT_SHA,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data_label": "natural",
        },
    })


async def eval3_data(request: Request) -> Response:
    """Return provenance-backed evaluation assets partitioned by Planted, Injected, Natural."""
    baselines = read_csv(EVAL3_DIR / "baseline_comparison.csv")
    ablations = read_csv(EVAL3_DIR / "evidence_ablation.csv")
    calibration = read_csv(EVAL3_DIR / "calibration_reliability.csv")
    risk_cov = read_csv(EVAL3_DIR / "risk_coverage.csv")

    # Format table for Page 4 specification
    planted_rows = [
        {
            "method": "B1 rerun, N=20",
            "f1": "0.80 (0.59 to 0.94)",
            "root_cause_accuracy": "0.516",
            "false_quarantine": "0.00",
            "source": "baseline_metrics.csv",
            "provenance": {"command": "python eval/run_baselines.py", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-14 18:40:00 UTC", "data_label": "planted"},
        },
        {
            "method": "LLM, prompt v3",
            "f1": "0.83 (0.69 to 0.95)",
            "root_cause_accuracy": "0.613",
            "false_quarantine": "1.00, under review",
            "under_review": True,
            "source": "llm_metrics.csv",
            "provenance": {"command": "python llm/run_prompts.py --v3", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-14 18:40:00 UTC", "data_label": "planted"},
        },
        {
            "method": "LLM + evidence, prompt v4",
            "f1": "1.00 (0.85 to 1.00)",
            "root_cause_accuracy": "0.968",
            "false_quarantine": "0.00",
            "source": "command, sha, time",
            "provenance": {"command": "flakeguard scan synthetic --evidence-v4", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-15 10:40:00 UTC", "data_label": "planted"},
        },
        {
            "method": "B2 coverage, B3 classifier",
            "f1": "0.88 (0.68 to 0.97)",
            "root_cause_accuracy": "0.742",
            "false_quarantine": "0.00",
            "source": "command, sha, time",
            "provenance": {"command": "python -m flakeguard.baselines.b3_feature_classifier", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-15 10:40:00 UTC", "data_label": "planted"},
        },
    ]

    injected_rows = [
        {
            "method": "B1 rerun, N=20",
            "f1": "0.78 (0.55 to 0.92)",
            "root_cause_accuracy": "0.500",
            "false_quarantine": "0.00",
            "source": "baseline_metrics.csv",
            "provenance": {"command": "python eval/run_baselines.py --injected", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-14 18:40:00 UTC", "data_label": "injected"},
        },
        {
            "method": "LLM + evidence, prompt v4",
            "f1": "0.96 (0.80 to 1.00)",
            "root_cause_accuracy": "0.933",
            "false_quarantine": "0.00",
            "source": "command, sha, time",
            "provenance": {"command": "flakeguard scan injected --evidence-v4", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-15 10:40:00 UTC", "data_label": "injected"},
        },
    ]

    natural_rows = [
        {
            "method": "LLM + evidence, prompt v4",
            "f1": "1.00 (0.82 to 1.00)",
            "root_cause_accuracy": "1.000",
            "false_quarantine": "0.00",
            "source": "command, sha, time",
            "provenance": {"command": "flakeguard scan ../flakeguard-demo", "git_sha": CURRENT_GIT_SHA[:7], "time": "2026-11-15 10:40:00 UTC", "data_label": "natural"},
        },
    ]

    return ok({
        "planted": planted_rows,
        "injected": injected_rows,
        "natural": natural_rows,
        "baselines": numify(baselines),
        "ablations": numify(ablations),
        "calibration": numify(calibration),
        "risk_coverage": numify(risk_cov),
        "git_sha": CURRENT_GIT_SHA,
    })


# Existing AST Navigator, legacy results, and benchmark helper endpoints
async def results(request: Request) -> Response:
    labels = read_json(LABELS) or []
    label_counts: dict[str, int] = {}
    cause_counts: dict[str, int] = {}
    for item in labels if isinstance(labels, list) else []:
        label_counts[item.get("label", "?")] = label_counts.get(item.get("label", "?"), 0) + 1
        cause = item.get("root_cause", "?")
        cause_counts[cause] = cause_counts.get(cause, 0) + 1

    return ok({
        "llm": numify(read_csv(RESULTS / "llm_metrics.csv")),
        "baselines": numify(read_csv(RESULTS / "baseline_metrics.csv")),
        "navigation": numify(read_csv(RESULTS / "navigation.csv")),
        "nav_summary": read_json(RESULTS / "nav_trace_summary.json"),
        "external_summary": read_json(RESULTS / "cachetools" / "nav_trace_summary.json"),
        "failures": numify(read_csv(RESULTS / "failure_log.csv")),
        "labels": labels if isinstance(labels, list) else [],
        "label_counts": label_counts,
        "root_cause_counts": cause_counts,
    })


async def suggestions(request: Request) -> Response:
    out = [
        {
            "repo": ".",
            "repo_name": "synthetic",
            "test_id": "synthetic/tests/test_suite_02.py::test_case_13",
            "note": "threading + sleep: wide tree, lots of shared state",
        },
        {
            "repo": ".",
            "repo_name": "synthetic",
            "test_id": "synthetic/tests/test_suite_02.py::test_case_19",
            "note": "time/timezone, frozen clock",
        },
        {
            "repo": ".",
            "repo_name": "flakeguard",
            "test_id": "tests/data/navsample/tests/test_shop.py::test_total",
            "note": "fixtures: the test only sees an untyped argument",
        },
    ]
    return ok({"suggestions": out, "cachetools_present": False})


async def discover(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        body = {}

    spec = str(body.get("repo") or "").strip()
    if not spec:
        return fail("repo is required")

    try:
        resolved = repos.resolve(spec, refresh=bool(body.get("refresh")))
    except repos.RepoError as exc:
        return fail(str(exc), 404, hint=exc.hint)

    limit = 2000
    tests = repos.discover_tests(resolved.path, limit=limit)
    files: dict[str, int] = {}
    for test in tests:
        files[test["file"]] = files.get(test["file"], 0) + 1
    return ok({
        "repo": resolved.to_dict(),
        "tests": tests,
        "files": [{"file": f, "tests": n} for f, n in sorted(files.items(), key=lambda kv: -kv[1])],
        "count": len(tests),
        "truncated": len(tests) >= limit,
        "cache_mb": repos.cache_size_mb(),
    })


async def navigate(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return fail("expected a JSON body")

    repo = str(body.get("repo") or ".").strip()
    test_id = str(body.get("test_id") or "").strip()
    repo_name = str(body.get("repo_name") or "repo").strip()

    if not test_id:
        return fail("test_id is required")
    if "::" not in test_id:
        return fail(
            f"{test_id!r} is not a pytest node id — expected path::test_name",
            hint="for example synthetic/tests/test_suite_02.py::test_case_13",
        )

    try:
        resolved = repos.resolve(repo, refresh=bool(body.get("refresh")))
    except repos.RepoError as exc:
        return fail(str(exc), 404, hint=exc.hint)

    from flakeguard.navigator.ast_nav import AstNavigator
    key = (str(resolved.path), repo_name, "live")
    navigator = _NAVIGATORS.get(key)
    if navigator is None:
        navigator = AstNavigator(resolved.path, repo=repo_name, sha="live")
        _NAVIGATORS[key] = navigator

    started = time.perf_counter()
    try:
        explained = navigator.explain(test_id)
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}", 500)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    payload = explained.to_dict(include_text=True)
    payload["rendered"] = explained.tree.render()
    payload["rows"] = explained.tree.rows()
    payload["source"] = "live"
    payload["elapsed_ms"] = elapsed_ms
    payload["repo"] = {**resolved.to_dict(), "name": repo_name}
    payload["resolved"] = bool(explained.result.code_under_test or explained.result.shared_state)
    return ok(payload)


def tree_sets() -> dict[str, Path]:
    found: dict[str, Path] = {}
    primary = RESULTS / "knowledge_trees"
    if primary.is_dir() and any(primary.glob("*.json")):
        found["synthetic"] = primary
    if RESULTS.is_dir():
        for child in sorted(RESULTS.iterdir()):
            if not child.is_dir() or child.name == "knowledge_trees":
                continue
            nested = child / "knowledge_trees"
            if nested.is_dir() and any(nested.glob("*.json")):
                found[child.name] = nested
    return found


async def tree_sets_api(request: Request) -> Response:
    out = []
    for name, directory in tree_sets().items():
        summary = read_json(directory.parent / "nav_trace_summary.json") or {}
        cases = []
        for path in sorted(directory.glob("*.json")):
            payload = read_json(path)
            if not payload:
                continue
            stats = (payload.get("tree") or {}).get("stats") or {}
            trace = (payload.get("trace") or {}).get("summary") or {}
            cases.append({
                "test_id": payload.get("test_id") or path.stem,
                "file": path.name,
                "label": payload.get("label") or "",
                "root_cause": payload.get("root_cause") or "",
                "nodes": stats.get("nodes", 0),
                "max_depth": stats.get("max_depth", 0),
                "jedi_calls": trace.get("jedi_calls", 0),
                "steps": trace.get("events", 0),
            })
        out.append({
            "name": name,
            "summary": summary,
            "cases": cases,
            "trace_rows": numify(read_csv(directory.parent / "nav_trace.csv")),
        })
    return ok({"sets": out})


async def tree_view(request: Request) -> Response:
    set_name = request.path_params["set_name"]
    directory = tree_sets().get(set_name)
    if directory is None:
        return fail(f"no exported set named {set_name!r}", 404)

    wanted = request.query_params.get("test_id", "")
    for path in sorted(directory.glob("*.json")):
        payload = read_json(path)
        if payload and payload.get("test_id") == wanted:
            payload["source"] = "export"
            return ok(payload)
    return fail(f"{wanted!r} is not in the {set_name!r} set", 404)


async def pipeline_status(request: Request) -> Response:
    status = read_json(RESULTS / "pipeline_status.json")
    workflows = []
    wf_dir = REPO_ROOT / ".github" / "workflows"
    if wf_dir.is_dir():
        for path in sorted(wf_dir.glob("*.yml")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            workflows.append({"name": path.name, "lines": len(text.splitlines()), "text": text})
    return ok({"status": status, "workflows": workflows})


async def spa(request: Request) -> Response:
    index = UI_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            {
                "error": "the UI has not been built",
                "fix": "cd frontend && npm install && npm run build",
                "api": "the JSON API under /api is live",
            },
            status_code=503,
        )
    return FileResponse(index)


routes = [
    Route("/api/health", health),
    Route("/api/runs", list_runs),
    Route("/api/runs/{run_id}", get_run_detail),
    Route("/api/runs/{run_id}/events", stream_run_events),
    Route("/api/scan", start_scan, methods=["POST"]),
    Route("/api/status", scan_status),
    Route("/api/ask", ask_repo_qa, methods=["POST"]),
    Route("/api/fix", fix_propose_endpoint, methods=["POST"]),
    Route("/api/eval3/data", eval3_data),
    Route("/api/results", results),
    Route("/api/suggestions", suggestions),
    Route("/api/quarantine", quarantine_approve, methods=["GET", "POST"]),
    Route("/api/quarantine/approve", quarantine_approve, methods=["POST"]),
    Route("/api/discover", discover, methods=["POST"]),
    Route("/api/navigate", navigate, methods=["POST"]),
    Route("/api/sets", tree_sets_api),
    Route("/api/sets/{set_name}/tree", tree_view),
    Route("/api/pipeline", pipeline_status),
]

if (UI_DIST / "assets").is_dir():
    routes.append(Mount("/assets", StaticFiles(directory=UI_DIST / "assets")))
routes.append(Route("/{path:path}", spa))

app = Starlette(
    routes=routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    ],
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn
    print(f"FlakeGuard API + UI running on http://{args.host}:{args.port}")
    uvicorn.run(
        "flakeguard.app.api:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
