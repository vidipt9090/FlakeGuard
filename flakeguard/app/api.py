"""JSON API behind the React dashboard, plus the static server for it.

Built on Starlette, which is already a dependency (Streamlit pulls it in), so
the web UI adds no new Python package.

Two kinds of endpoint, and the difference matters:

* **reads** -- serve what the pipeline exported to ``results/``. These are
  fast, work with no checkout, and are what the dashboard opens with.
* **/api/navigate** -- actually runs the navigator against a repository on
  this machine, right now. Nothing is read from ``results/``; the tree and
  the trace in the response were produced by the request. This is what makes
  the UI a demonstration rather than a slideshow.

Run it:

    python -m flakeguard.app.api                 # serve API + built UI
    python -m flakeguard.app.api --reload        # development

In development the React dev server proxies ``/api`` here, so CORS is open
for localhost only.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from flakeguard.app import repos

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "results"
LABELS = REPO_ROOT / "labels" / "labels.json"
UI_DIST = REPO_ROOT / "frontend" / "dist"

# A navigator is cheap to construct but caches parsed sources, so reusing one
# per repository turns a second navigation of the same tree from ~1.5s into
# ~0.3s. Keyed by resolved path; the UI hits the same repo repeatedly.
_NAVIGATORS: dict[tuple[str, str, str], Any] = {}


# ----------------------------------------------------------------- helpers


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
    """CSV gives strings; the UI wants numbers where a value is numeric."""
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


def tree_sets() -> dict[str, Path]:
    """Exported tree directories, by the repo they were navigated in."""
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


def ok(payload: Any) -> JSONResponse:
    return JSONResponse(payload)


def fail(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


# ------------------------------------------------------------------ routes


async def health(request: Request) -> Response:
    return ok({"status": "ok", "repo_root": str(REPO_ROOT)})


async def sets(request: Request) -> Response:
    """Every exported tree set, with its summary and its case list."""
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
            cases.append(
                {
                    "test_id": payload.get("test_id") or path.stem,
                    "file": path.name,
                    "label": payload.get("label") or "",
                    "root_cause": payload.get("root_cause") or "",
                    "nodes": stats.get("nodes", 0),
                    "max_depth": stats.get("max_depth", 0),
                    "jedi_calls": trace.get("jedi_calls", 0),
                    "steps": trace.get("events", 0),
                }
            )
        out.append(
            {
                "name": name,
                "summary": summary,
                "cases": cases,
                "trace_rows": numify(read_csv(directory.parent / "nav_trace.csv")),
            }
        )
    return ok({"sets": out})


async def tree(request: Request) -> Response:
    """One exported tree, trace and all."""
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


async def navigate(request: Request) -> Response:
    """Run the navigator now, against a checkout on this machine.

    This is the live path. It imports the navigator, resolves a real test id
    against real source, and returns the tree and the full ordered trace that
    the run produced.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
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

    # A path is used as-is; a URL is cloned into .cache/repos first.
    try:
        resolved = repos.resolve(repo, refresh=bool(body.get("refresh")))
    except repos.RepoError as exc:
        return fail(str(exc), 404, hint=exc.hint)
    repo_path = resolved.path
    if resolved.kind == "clone" and repo_name in {"repo", ""}:
        repo_name = resolved.name

    from flakeguard.navigator.ast_nav import AstNavigator

    key = (str(repo_path), repo_name, "live")
    navigator = _NAVIGATORS.get(key)
    if navigator is None:
        navigator = AstNavigator(repo_path, repo=repo_name, sha="live")
        _NAVIGATORS[key] = navigator

    started = time.perf_counter()
    try:
        explained = navigator.explain(test_id)
    except Exception as exc:  # a bad id must not take the server down
        return fail(f"{type(exc).__name__}: {exc}", 500)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    payload = explained.to_dict(include_text=True)
    payload["rendered"] = explained.tree.render()
    payload["rows"] = explained.tree.rows()
    payload["source"] = "live"
    payload["elapsed_ms"] = elapsed_ms
    payload["repo"] = {**resolved.to_dict(), "name": repo_name}
    payload["resolved"] = bool(
        explained.result.code_under_test or explained.result.shared_state
    )
    return ok(payload)


async def discover(request: Request) -> Response:
    """Test ids in a repository, so a freshly cloned repo is usable.

    Clones when given a URL. The repository is parsed, never imported, so
    nothing in it runs as a result of this call.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return fail("expected a JSON body")

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
    return ok(
        {
            "repo": resolved.to_dict(),
            "tests": tests,
            "files": [
                {"file": f, "tests": n}
                for f, n in sorted(files.items(), key=lambda kv: -kv[1])
            ],
            "count": len(tests),
            "truncated": len(tests) >= limit,
            "cache_mb": repos.cache_size_mb(),
        }
    )


async def cached(request: Request) -> Response:
    """Repositories already cloned, offered without another network hop."""
    return ok({"repos": repos.cached_repos(), "cache_mb": repos.cache_size_mb()})


async def suggestions(request: Request) -> Response:
    """Test ids worth trying, so the live panel is never a blank box."""
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
    cachetools = (REPO_ROOT.parent / "cachetools")
    if cachetools.is_dir():
        out.extend(
            [
                {
                    "repo": str(cachetools),
                    "repo_name": "cachetools",
                    "test_id": "tests/test_ttl.py::TTLCacheTest::test_ttl",
                    "note": "inheritance + operators: reaches hop 2 via jedi.infer",
                },
                {
                    "repo": str(cachetools),
                    "repo_name": "cachetools",
                    "test_id": "tests/test_lru.py::LRUCacheTest::test_lru",
                    "note": "an inherited test body in a mixin",
                },
            ]
        )
    return ok({"suggestions": out, "cachetools_present": cachetools.is_dir()})


async def pipeline(request: Request) -> Response:
    status = read_json(RESULTS / "pipeline_status.json")
    workflows = []
    wf_dir = REPO_ROOT / ".github" / "workflows"
    if wf_dir.is_dir():
        for path in sorted(wf_dir.glob("*.yml")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            workflows.append(
                {"name": path.name, "lines": len(text.splitlines()), "text": text}
            )
    return ok({"status": status, "workflows": workflows})


async def results(request: Request) -> Response:
    labels = read_json(LABELS) or []
    label_counts: dict[str, int] = {}
    cause_counts: dict[str, int] = {}
    for item in labels if isinstance(labels, list) else []:
        label_counts[item.get("label", "?")] = label_counts.get(item.get("label", "?"), 0) + 1
        cause = item.get("root_cause", "?")
        cause_counts[cause] = cause_counts.get(cause, 0) + 1

    return ok(
        {
            "llm": numify(read_csv(RESULTS / "llm_metrics.csv")),
            "baselines": numify(read_csv(RESULTS / "baseline_metrics.csv")),
            "navigation": numify(read_csv(RESULTS / "navigation.csv")),
            "nav_summary": read_json(RESULTS / "nav_trace_summary.json"),
            "external_summary": read_json(
                RESULTS / "cachetools" / "nav_trace_summary.json"
            ),
            "failures": numify(read_csv(RESULTS / "failure_log.csv")),
            "labels": labels if isinstance(labels, list) else [],
            "label_counts": label_counts,
            "root_cause_counts": cause_counts,
        }
    )


async def runs(request: Request) -> Response:
    """Per-run outcomes, for the flip-rate view."""
    rows = read_csv(RESULTS / "runs.csv")
    per_test: dict[str, dict] = {}
    for row in rows:
        test_id = row.get("test_id", "")
        entry = per_test.setdefault(
            test_id, {"test_id": test_id, "passes": 0, "fails": 0, "total": 0}
        )
        entry["total"] += 1
        if row.get("outcome") == "PASS":
            entry["passes"] += 1
        else:
            entry["fails"] += 1
    for entry in per_test.values():
        entry["flip_rate"] = (
            round(min(entry["passes"], entry["fails"]) / entry["total"], 4)
            if entry["total"]
            else 0.0
        )
    return ok({"tests": sorted(per_test.values(), key=lambda e: -e["flip_rate"])})


async def case_llm(request: Request) -> Response:
    """The three prompt versions' raw output for one benchmark case."""
    number = request.path_params["number"]
    out = {}
    for version in ("v1", "v2", "v3"):
        payload = read_json(
            RESULTS / "llm_raw" / version / f"test_case_{int(number):02d}.json"
        )
        if payload:
            out[version] = payload
    return ok({"case": int(number), "versions": out})


async def spa(request: Request) -> Response:
    """Serve the built UI, falling back to index.html for client routes."""
    index = UI_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            {
                "error": "the UI has not been built",
                "fix": "cd frontend && npm install && npm run build",
                "api": "the JSON API under /api is already live",
            },
            status_code=503,
        )
    return FileResponse(index)


routes = [
    Route("/api/health", health),
    Route("/api/sets", sets),
    Route("/api/sets/{set_name}/tree", tree),
    Route("/api/navigate", navigate, methods=["POST"]),
    Route("/api/discover", discover, methods=["POST"]),
    Route("/api/cached", cached),
    Route("/api/suggestions", suggestions),
    Route("/api/pipeline", pipeline),
    Route("/api/results", results),
    Route("/api/runs", runs),
    Route("/api/case/{number:int}/llm", case_llm),
]

if (UI_DIST / "assets").is_dir():
    routes.append(Mount("/assets", StaticFiles(directory=UI_DIST / "assets")))
routes.append(Route("/{path:path}", spa))

app = Starlette(
    routes=routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            # The Vite dev server runs on another port and proxies to here.
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

    if not UI_DIST.is_file() and not (UI_DIST / "index.html").is_file():
        print("note: frontend/dist not built yet — the API works, the UI 503s.")
        print("      cd frontend && npm install && npm run build")
    print(f"FlakeGuard API + UI on http://{args.host}:{args.port}")
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
