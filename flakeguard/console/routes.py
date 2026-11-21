"""HTTP routes for the console, following section 6 of the build plan.

Errors are ``{"detail": "<readable sentence>"}``. The console shows ``detail`` verbatim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from flakeguard.console import models as m
from flakeguard.console.actions import (
    TARGET,
    ApiError,
    BudgetExhausted,
    NoRun,
    actions_source,
    github_token,
    is_actions_id,
)
from flakeguard.console.runs import Refused, is_live_id, manager, seed_start_from_env
from flakeguard.console.store import FINDING_SEPARATOR, NotFound, RecordedStore, empty_no_tests_plan
from flakeguard.runner.matrix import DEFAULT_SEED_START

STOPWORDS = {
    "the", "and", "why", "what", "how", "does", "did", "this", "that", "with", "from", "are", "was",
    "for", "has", "have", "can", "not", "its", "test", "tests", "fail", "fails", "failing", "when",
    "which", "where", "who", "should", "would", "could", "about", "into", "than", "then", "there",
}
RESULTS_LABELS = ("injected", "natural", "planted")

_store: RecordedStore | None = None
_indexes: dict[str, Any] = {}


def store() -> RecordedStore:
    global _store
    if _store is None:
        _store = RecordedStore()
    return _store


def set_store(value: RecordedStore | None) -> None:
    """Point the routes at another recorded directory (used by tests)."""
    global _store
    _store = value
    _indexes.clear()


def detail(message: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def respond(model: BaseModel | list[BaseModel]) -> Response:
    if isinstance(model, list):
        return Response("[" + ",".join(x.model_dump_json() for x in model) + "]", media_type="application/json")
    return Response(model.model_dump_json(), media_type="application/json")


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
        return TypeAdapter(list[m.Finding]).validate_json(_source().findings_json(run_id))
    if is_live_id(run_id):
        return TypeAdapter(list[m.Finding]).validate_json(manager().findings_json(run_id))
    return store().findings(run_id)


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
        if is_live_id(run_id) or is_actions_id(run_id):
            return respond(empty_no_tests_plan((await run_in_threadpool(_run, run_id)).target))
        return respond(store().no_tests(run_id))
    except NotFound as e:
        return detail(str(e), 404)


async def get_results(request: Request) -> Response:
    label = request.query_params.get("label", "injected")
    if label not in RESULTS_LABELS:
        return detail("Pick one of injected, natural or planted.", 422)
    empty = m.Provenance(dataset=None, labelType=label, n=None, command=None, date=None, commit=None)  # type: ignore[arg-type]
    return respond(m.ResultsData(
        ablation=m.TableWithProvenance(
            table=m.ResultsTable(columns=[
                "Context given to the model", "Diagnosis matches the known cause",
                "Fix passes validation under shuffle", "Code sent to the model"], rows=[]),
            provenance=empty),
        baselines=m.TableWithProvenance(
            table=m.ResultsTable(columns=["Method", "Flaky tests found", "Wrongly flagged", "CI minutes used"], rows=[]),
            provenance=empty),
        runsToDecision=m.RunsToDecision(fixed=None, adaptive=None),
        triage=m.TriageNumbers(redPrsCleared=None, realQuarantined=None),
    ))


# --------------------------------------------------------------------------- actions


def _tokens(question: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", question.replace("_", " "))
    return {w.lower() for w in words if len(w) >= 3 and w.lower() not in STOPWORDS}


def _identifier_parts(*names: str) -> set[str]:
    parts: set[str] = set()
    for name in names:
        parts.update(p.lower() for p in re.findall(r"[A-Za-z][A-Za-z0-9]*", name.replace("_", " ")))
    return parts


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

    from flakeguard.rag.index import CodebaseIndexer

    key = str(repo)
    if key not in _indexes:
        idx = CodebaseIndexer(repo)
        idx.index()
        _indexes[key] = idx
    tokens = _tokens(question)
    scored = []
    for chunk in _indexes[key].chunks:
        if chunk.kind == "ci_event":
            continue
        parts = _identifier_parts(chunk.name, Path(chunk.file).stem, *chunk.reads, *chunk.writes)
        hits = tokens & parts
        if hits:
            scored.append((len(hits), chunk))
    scored.sort(key=lambda x: (-x[0], x[1].file, x[1].line_start))
    top = [c for _, c in scored[:5]]
    if not top:
        return respond(m.AskAnswer(text="", citations=[], chunks=0))
    cites = [m.AskCitation(label=f"{c.file}:{c.line_start}", file=c.file, line=c.line_start) for c in top]
    names = ", ".join(f"{c.name} ({c.file}:{c.line_start})" for c in top)
    text = f"Code that matches your question: {names}. What the scan found for {finding.test}: {finding.why}"
    return respond(m.AskAnswer(text=text, citations=cites, chunks=len(top)))


async def fix(request: Request) -> Response:
    try:
        _, finding = _find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    if finding.fix is None:
        return detail("There is no validated fix for this finding, so no pull request can be opened.", 409)
    return detail("Opening a fix pull request is not available yet.", 409)


async def reverify(request: Request) -> Response:
    try:
        _find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    return detail("Re-verify needs a live scan. This server is replaying a recorded run.", 409)


async def quarantine(request: Request) -> Response:
    try:
        _, finding = _find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    if not finding.quarantine.allowed:
        return detail(finding.quarantine.reason or "Quarantine is refused for this test.", 409)
    return detail(
        "Quarantine needs write access to a GitHub repository. This run is a local fixture, so nothing was changed.",
        409,
    )


ROUTES = [
    Route("/api/health", health),
    Route("/api/runs", start_run, methods=["POST"]),
    Route("/api/runs/{run_id}", get_run),
    Route("/api/runs/{run_id}/findings", get_findings),
    Route("/api/runs/{run_id}/tree", get_tree),
    Route("/api/runs/{run_id}/no-tests", get_no_tests),
    Route("/api/findings/{finding_id}/ask", ask, methods=["POST"]),
    Route("/api/findings/{finding_id}/fix", fix, methods=["POST"]),
    Route("/api/findings/{finding_id}/reverify", reverify, methods=["POST"]),
    Route("/api/findings/{finding_id}/quarantine", quarantine, methods=["POST"]),
    Route("/api/results", get_results),
]
