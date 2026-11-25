"""HTTP routes for the console, following section 6 of the build plan.

Errors are ``{"detail": "<readable sentence>"}``. The console shows ``detail`` verbatim.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from flakeguard.console import forge
from flakeguard.console import models as m
from flakeguard.console import reverify as reverify_mod
from flakeguard.console.actions import (
    TARGET,
    ApiError,
    BudgetExhausted,
    NoRun,
    actions_source,
    github_token,
    is_actions_id,
)
from flakeguard.console.ask import answer_question, clear_indexes
from flakeguard.console.no_tests import (
    NoTestsNotFound,
    NoTestsRefused,
    drop_test,
    is_no_tests_id,
    read_plan,
)
from flakeguard.console.results import load_results
from flakeguard.console.runs import DEMO_REPOS, Refused, is_live_id, manager, seed_start_from_env
from flakeguard.console.store import FINDING_SEPARATOR, NotFound, RecordedStore, empty_no_tests_plan
from flakeguard.runner.matrix import DEFAULT_SEED_START

RESULTS_LABELS = ("injected", "natural", "planted")

_store: RecordedStore | None = None


def store() -> RecordedStore:
    global _store
    if _store is None:
        _store = RecordedStore()
    return _store


def set_store(value: RecordedStore | None) -> None:
    """Point the routes at another recorded directory (used by tests)."""
    global _store
    _store = value
    clear_indexes()


def detail(message: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def respond(model: BaseModel | list[BaseModel]) -> Response:
    if isinstance(model, list):
        return Response("[" + ",".join(x.model_dump_json() for x in model) + "]", media_type="application/json")
    return Response(model.model_dump_json(), media_type="application/json")


def respond_json(payload: dict) -> Response:
    return Response(json.dumps(payload), media_type="application/json")


def _source():
    """The GitHub Actions source, or an error the person can read when there is no token."""
    src = actions_source(manager().root)
    if src is None:
        raise Refused("The backend has no GitHub token. Set GITHUB_TOKEN, or sign in with `gh auth login`.", 503)
    return src


def _run(run_id: str) -> m.RunStatus:
    if is_actions_id(run_id):
        return _source().status(run_id)
    return manager().status(run_id) if is_live_id(run_id) else store().run(run_id)


def _findings(run_id: str) -> list[m.Finding]:
    if is_actions_id(run_id):
        found = TypeAdapter(list[m.Finding]).validate_json(_source().findings_json(run_id))
    elif is_live_id(run_id):
        found = TypeAdapter(list[m.Finding]).validate_json(manager().findings_json(run_id))
    else:
        return store().findings(run_id)
    return reverify_mod.with_evidence(manager().root / run_id, found)


def _tree_json(run_id: str) -> str | None:
    """The tree as JSON text for live and Actions runs; None for recorded runs (validated models)."""
    if is_actions_id(run_id):
        return _source().tree_json(run_id)
    if is_live_id(run_id):
        return manager().tree_json(run_id)
    return None


def github_failure(e: Exception) -> JSONResponse:
    """Readable answers for GitHub-side problems."""
    if isinstance(e, BudgetExhausted):
        return detail("The GitHub request budget for this hour is used up (the console plans for 1,000 requests per hour). "
                      "Try again later.", 429)
    if isinstance(e, NoRun):
        return detail(str(e), 404)
    if isinstance(e, ApiError):
        if e.status == 404:
            return detail("GitHub could not find that pull request or run. Check the repository and the number.", 404)
        if e.status in (401, 403):
            return detail("GitHub refused the backend's token for that request.", 502)
        return detail(f"GitHub did not answer as expected (HTTP {e.status}).", 502)
    raise e


def _find_finding(finding_id: str) -> tuple[str, m.Finding]:
    run_id, sep, _ = finding_id.partition(FINDING_SEPARATOR)
    if run_id.startswith("gh-"):
        run_id = "actions-" + run_id[len("gh-"):]  # the Actions job names its run gh-<id>; the console calls it actions-<id>
    if sep:
        for f in _findings(run_id):
            if f.id == finding_id:
                return run_id, f
    raise NotFound(f"There is no finding called {finding_id}.")


def _target_path(run_id: str) -> Path | None:
    if not is_live_id(run_id):
        return store().target_path(run_id)
    meta = manager().dir(run_id) / "meta.json"
    if not meta.is_file():
        return None
    path = Path(json.loads(meta.read_text(encoding="utf-8")).get("target", ""))
    return path if path.is_dir() else None


async def body_of(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# ----------------------------------------------------------------------------- reads


async def health(request: Request) -> Response:
    from flakeguard.runner.sandbox import DockerSandbox

    docker = DockerSandbox(repo_path=Path(".")).is_available()
    return JSONResponse({
        "ok": True, "mode": "actions" if github_token() else "local", "docker": bool(docker),
        "recorded": store().latest_id(),  # newest recorded run, if any, for the explicit replay link
    })


async def start_run(request: Request) -> Response:
    """Start a real scan on this machine. One at a time; Docker is never silently skipped."""
    try:
        req = m.StartRunRequest.model_validate(await body_of(request))
    except ValidationError:
        return detail("The scan request is missing a field. Check the repository, source, runs and Docker option.", 422)
    if not 1 <= req.runs <= 50:
        return detail("Shuffled runs must be between 1 and 50.", 422)
    if req.source == "pull-request":
        match = TARGET.match(req.target.strip())
        if match is None:
            return detail("Write the pull request as owner/repo#7, for example vidipt9090/flakeguard-demo#3.", 422)
        try:
            src = _source()
            run_id = await run_in_threadpool(src.attach, match["repo"], int(match["pr"]))
        except Refused as e:
            return detail(str(e), e.status)
        except (ApiError, BudgetExhausted, NoRun) as e:
            return github_failure(e)
        return JSONResponse({"id": run_id})
    mgr = manager()
    try:
        target, label = mgr.resolve_target(req)
        if req.docker:
            from flakeguard.runner.sandbox import DockerSandbox

            if not DockerSandbox(repo_path=Path(".")).is_available():
                return JSONResponse({"id": mgr.refuse_docker(req, label)})
        run_id = mgr.start(req, target, label, seed_start_from_env() or DEFAULT_SEED_START)
    except Refused as e:
        return detail(str(e), e.status)
    return JSONResponse({"id": run_id})


async def get_run(request: Request) -> Response:
    try:
        return respond(await run_in_threadpool(_run, request.path_params["run_id"]))
    except NotFound as e:
        return detail(str(e), 404)
    except Refused as e:
        return detail(str(e), e.status)
    except (ApiError, BudgetExhausted) as e:
        return github_failure(e)


async def get_findings(request: Request) -> Response:
    try:
        return respond(await run_in_threadpool(_findings, request.path_params["run_id"]))
    except NotFound as e:
        return detail(str(e), 404)
    except Refused as e:
        return detail(str(e), e.status)
    except (ApiError, BudgetExhausted) as e:
        return github_failure(e)


async def get_tree(request: Request) -> Response:
    run_id = request.path_params["run_id"]
    try:
        text = await run_in_threadpool(_tree_json, run_id)
        if text is not None:
            return Response(text, media_type="application/json")
        return respond(store().tree(run_id))
    except NotFound as e:
        return detail(str(e), 404)
    except Refused as e:
        return detail(str(e), e.status)
    except (ApiError, BudgetExhausted) as e:
        return github_failure(e)


async def get_no_tests(request: Request) -> Response:
    run_id = request.path_params["run_id"]
    try:
        if is_no_tests_id(run_id):
            return respond(await run_in_threadpool(read_plan, run_id))
        if is_live_id(run_id) or is_actions_id(run_id):
            return respond(empty_no_tests_plan((await run_in_threadpool(_run, run_id)).target))
        return respond(store().no_tests(run_id))
    except (NotFound, NoTestsNotFound) as e:
        return detail(str(e), 404)


async def drop_no_test(request: Request) -> Response:
    """Drop one generated test. Local only: it edits two files under recorded_no_tests/ and nothing else."""
    run_id = request.path_params["run_id"]
    if not is_no_tests_id(run_id):
        return detail("Only a recorded no-tests scan has generated tests that can be dropped.", 409)
    test = str((await body_of(request)).get("test", "")).strip()
    if not test:
        return detail("Say which test to drop.", 422)
    try:
        return respond(await run_in_threadpool(drop_test, run_id, test))
    except NoTestsNotFound as e:
        return detail(str(e), 404)
    except NoTestsRefused as e:
        return detail(str(e), 409)


async def get_results(request: Request) -> Response:
    label = request.query_params.get("label", "injected")
    if label not in RESULTS_LABELS:
        return detail("Pick one of injected, natural or planted.", 422)
    return respond(await run_in_threadpool(load_results, label))


# --------------------------------------------------------------------------- actions


async def ask(request: Request) -> Response:
    finding_id = request.path_params["finding_id"]
    question = str((await body_of(request)).get("question", "")).strip()
    if not question:
        return detail("Type a question first.", 422)
    try:
        run_id, finding = _find_finding(finding_id)
    except NotFound as e:
        return detail(str(e), 404)
    repo = _target_path(run_id)
    if repo is None:
        return detail("The scanned repository is not on this machine, so there is no code to search.", 409)
    return respond(await run_in_threadpool(answer_question, repo, finding, question))


def _run_dir(run_id: str) -> Path | None:
    """Where backend-side data for a live or Actions run lives. Recorded runs are read-only."""
    return manager().root / run_id if is_live_id(run_id) or is_actions_id(run_id) else None


def _known_failing(run_id: str) -> set[str]:
    return {f"{f.file}::{f.test}" for f in _findings(run_id)}


def _run_url(run_id: str) -> str | None:
    pr = _run(run_id).pr
    return pr.runUrl if pr else None


async def fix(request: Request) -> Response:
    try:
        run_id, finding = _find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    if finding.fix is None:
        return detail("There is no validated fix for this finding, so no pull request can be opened.", 409)
    source = _run(run_id).source
    if source is None:
        return detail("This run did not scan a GitHub repository, so there is no fork to open a pull request on.", 409)
    if source.repo not in DEMO_REPOS:
        return detail(f"{source.repo} is not a repository FlakeGuard may run without Docker, and the fix is validated by "
                      "running its tests. No pull request was opened.", 409)
    owner = os.environ.get("FLAKEGUARD_FORK_OWNER", "").strip()
    if not owner:
        return detail("No fork owner is set. Set FLAKEGUARD_FORK_OWNER to the GitHub user whose fork receives the fix.", 409)
    try:
        result = await run_in_threadpool(
            forge.open_fix_pr, source, finding, _known_failing(run_id), fork_owner=owner, token=forge.fork_token(owner))
    except forge.ForgeError as e:
        return detail(str(e), e.status)
    return respond_json({"prUrl": result.pr_url})


async def reverify(request: Request) -> Response:
    try:
        run_id, finding = _find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    run_dir = _run_dir(run_id)
    if run_dir is None:
        return detail("Re-verify needs a live scan. This server is replaying a recorded run.", 409)
    body = await body_of(request)
    if body.get("runs", reverify_mod.RUNS) != reverify_mod.RUNS:
        return detail(f"Re-verify runs exactly {reverify_mod.RUNS} shuffled runs.", 422)
    repo = _target_path(run_id)
    cleanup: Path | None = None
    if repo is None:
        source = _run(run_id).source
        if source is None or source.repo not in DEMO_REPOS:
            return detail("The scanned repository is not on this machine and is not one FlakeGuard may run without Docker.", 409)
        cleanup = Path(tempfile.mkdtemp(prefix="flakeguard-reverify-src-"))
        try:
            await run_in_threadpool(forge.fetch_source, source, cleanup / "repo")
        except forge.ForgeError as e:
            shutil.rmtree(cleanup, ignore_errors=True)
            return detail(str(e), e.status)
        repo = cleanup / "repo"
    if not reverify_mod.claim(finding.id):
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)
        return detail("A re-verify of this finding is already running.", 409)

    def work() -> None:
        try:
            reverify_mod.run_reverify(repo, run_dir, finding)
        finally:
            reverify_mod.release(finding.id)
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)

    threading.Thread(target=work, daemon=True).start()
    return respond_json({"started": True})


async def quarantine(request: Request) -> Response:
    try:
        run_id, finding = _find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    refusal = forge.quarantine_refusal(finding)
    if refusal:
        return detail(refusal, 409)
    source = _run(run_id).source
    if source is None:
        return detail("Quarantine needs write access to a GitHub repository. This run is a local fixture, "
                      "so nothing was changed.", 409)
    token = github_token()
    if token is None:
        return detail("The backend has no GitHub token. Set GITHUB_TOKEN, or sign in with `gh auth login`.", 503)
    gh = forge.GitHub(token)
    try:
        login = gh.json("GET", "/user")["login"]
        if not forge.can_write(gh, source.repo, login):
            return detail(f"Quarantine is refused: {login} does not have write access to {source.repo}.", 409)
        url = await run_in_threadpool(
            forge.open_quarantine_issue, gh, source.repo, finding, requester=login, run_url=_run_url(run_id))
    except forge.ForgeError as e:
        return detail(str(e), e.status)
    return respond_json({"issueUrl": url})


ROUTES = [
    Route("/api/health", health),
    Route("/api/runs", start_run, methods=["POST"]),
    Route("/api/runs/{run_id}", get_run),
    Route("/api/runs/{run_id}/findings", get_findings),
    Route("/api/runs/{run_id}/tree", get_tree),
    Route("/api/runs/{run_id}/no-tests", get_no_tests),
    Route("/api/runs/{run_id}/no-tests/drop", drop_no_test, methods=["POST"]),
    Route("/api/findings/{finding_id}/ask", ask, methods=["POST"]),
    Route("/api/findings/{finding_id}/fix", fix, methods=["POST"]),
    Route("/api/findings/{finding_id}/reverify", reverify, methods=["POST"]),
    Route("/api/findings/{finding_id}/quarantine", quarantine, methods=["POST"]),
    Route("/api/results", get_results),
]
