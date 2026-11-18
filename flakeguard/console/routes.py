"""HTTP routes for the console, following section 6 of the build plan.

Errors are ``{"detail": "<readable sentence>"}``. The console shows ``detail`` verbatim.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from flakeguard.console import models as m
from flakeguard.console.store import NotFound, RecordedStore

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
    return JSONResponse({"ok": True, "mode": "local", "docker": bool(docker)})


async def start_run(request: Request) -> Response:
    """Until live scans exist (M3) this replays the newest recorded run.

    The returned run has ``mode: "recorded"`` and a ``recorded-run`` notice, so the console
    says on screen that it is a replay and not a live scan.
    """
    try:
        m.StartRunRequest.model_validate(await body_of(request))
    except ValidationError:
        return detail("The scan request is missing a field. Check the repository, source, runs and Docker option.", 422)
    latest = store().latest_id()
    if latest is None:
        return detail("There is no recorded run to replay and live scans are not available yet.", 409)
    return JSONResponse({"id": latest})


async def get_run(request: Request) -> Response:
    try:
        return respond(store().run(request.path_params["run_id"]))
    except NotFound as e:
        return detail(str(e), 404)


async def get_findings(request: Request) -> Response:
    try:
        return respond(store().findings(request.path_params["run_id"]))
    except NotFound as e:
        return detail(str(e), 404)


async def get_tree(request: Request) -> Response:
    try:
        return respond(store().tree(request.path_params["run_id"]))
    except NotFound as e:
        return detail(str(e), 404)


async def get_no_tests(request: Request) -> Response:
    try:
        return respond(store().no_tests(request.path_params["run_id"]))
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
        run_id, finding = store().find_finding(finding_id)
    except NotFound as e:
        return detail(str(e), 404)
    repo = store().target_path(run_id)
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
        _, finding = store().find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    if finding.fix is None:
        return detail("There is no validated fix for this finding, so no pull request can be opened.", 409)
    return detail("Opening a fix pull request is not available yet.", 409)


async def reverify(request: Request) -> Response:
    try:
        store().find_finding(request.path_params["finding_id"])
    except NotFound as e:
        return detail(str(e), 404)
    return detail("Re-verify needs a live scan. This server is replaying a recorded run.", 409)


async def quarantine(request: Request) -> Response:
    try:
        _, finding = store().find_finding(request.path_params["finding_id"])
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
