# FlakeGuard audit (M0)

Written 2026-11-18 on branch `c/eval3-console`, created from `c/eval3-actions` at `146d4d3`.
No feature code was written for this milestone. Every status below is backed by a command or a file reference. Where I could not prove something, it says so.

Status words used: **works** (a command I ran proves it), **exists, untested** (code is there, no proof), **partial** (some of the requirement is met), **missing**.

## 1. Branches (step 0.1)

`git fetch --all --prune` ran clean.

| Branch | Head | Note |
|---|---|---|
| `origin/main` (default branch) | `a8f8308` (2026-11-15, merge of PR #22) | No `scan.yml`, no `post-merge.yml`, no `cicd.yml` |
| `main` (local) | `88c4596` | 2 commits behind `origin/main` |
| `origin/develop` | `0489d1c` | Has `scan.yml` and `cicd.yml`, no `post-merge.yml` |
| `develop` (local) | `6e7eca2` | 16 commits behind `origin/develop` |
| `c/eval3-actions` (= `origin/c/eval3-actions`) | `146d4d3` | 4 commits ahead of `origin/develop`; only branch with `post-merge.yml`. 26 commits not in `origin/main`, 12 commits on `origin/main` not in it |
| `origin/c/eval3-integration` | `feca478` | Has `scan.yml` |
| `c/eval3-console` (new) | `146d4d3` | Branched from `c/eval3-actions`, then rebased onto `origin/main` (`a8f8308`) at the owner's request (DECISIONS M0-2). Hashes in this table are pre-rebase |

## 2. Inventory (step 0.2)

- Python package `flakeguard/` (about 16.5k lines): `runner/` (matrix, orchestrator, sandbox, detector, events), `evidence/` (bisection, interventions, read_write_map, engine), `stats/` (bayesian, adaptive, comparison), `navigator/` (ast_nav 1605 lines, knowledge_tree, trace), `rag/` (index, qa, langchain_retriever), `retrieval/` (embed, chunker), `llm/` (providers, prompt_v4, ablation, calibration, schema, run_prompts), `notest/` (scanner, generator, validator, orchestrator, fix), `baselines/` (b2, b3), `eval/` (baseline_rerun, run_baselines, metrics), `injector/`, `app/` (api.py, server.py, dashboard.py, pages_*.py, github.py, repos.py, viz.py).
- **Two backends exist.** `flakeguard/app/api.py` is Starlette (uvicorn) and serves the existing React app in `frontend/`. `flakeguard/app/server.py` is a stdlib `http.server` with SSE, and `dashboard.py` / `pages_*.py` look like a third UI path (not opened in M0; `streamlit` and `plotly` are in the dev dependencies). The plan assumes one backend; M2 has to pick `api.py`.
- Existing React app `frontend/` (36 source files). The plan puts the new console in `console/`, so the old one stays untouched until M9.
- `tests/`: 28 test modules. `scripts/`: 13 scripts. `eval/run_baselines.py`, `run_eval.py` at repo root.
- Workflows in `.github/workflows/`: `ci.yml`, `cicd.yml`, `collect.yml`, `post-merge.yml`, `quarantine-approve.yml`, `scan.yml`, `test.yml`, `triage.yml`.
- Docs: `docs/eval3/decision-log.md` (D11 to D39), `docs/eval3/planning/*`, `docs/limitations.md`, `docs/cicd.md`. **Not present:** `docs/ui/`, `docs/DECISIONS.md`, `docs/PROMPTS.md`, `docs/DEMO.md`, `console/`, `recorded/`, `scripts/run_eval.py`, `flakeguard/bot_templates.py`. They live in the spec bundle at `../Flakeguard spec bundle/` or do not exist yet.
- Environment: Python 3.12.13 in `../.venv` (flakeguard installed editable), Node v24.19.0, git 2.54.0. **`gh` CLI is not installed.** Docker client is installed but the **daemon is not running** (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`).

## 3. Test suite (step 0.3)

Command: `../.venv/Scripts/python.exe -m pytest -q -rs -p no:cacheprovider` (random order, `pytest-randomly` 5.1.0 is installed)

```
311 passed, 1 skipped in 165.58s (0:02:45)
SKIPPED [1] tests\test_retrieval.py:97: chromadb and sentence-transformers are optional: pip install -e '.[rag]'
```

So 312 tests are collected on this branch. Reason for the one skip: the optional embedding retriever extra is not installed.
**V10 (221 vs 247):** I cannot reproduce either number. The only collection filter in `pyproject.toml` is `norecursedirs = ["tests/data"]`. I have no record of the earlier runs, so I cannot confirm the "ignored files" explanation. Today's count is 312.

## 4. Requirement table (step 0.4)

### Engine (BE)

| ID | Status | Evidence (file, command) | Gaps against the plan |
|---|---|---|---|
| BE-1 Perturbation runner | **works** (partial vs plan) | `flakeguard/runner/matrix.py` `PerturbationMatrix.run_matrix`; `pytest tests/test_runner.py` 12 passed; real scan of the demo repo (section 6) ran 11 slices | Baseline runs **once**, not 3 times. "Isolated" covers only failing or suspect tests, capped at 5 (`matrix.py:285`). The `repeated` slice uses `pytest-repeat --count=3`, which creates ids like `test_x[1-3]` that then show up as separate tests and separate findings. Ids come from JUnit (`tests.test_orders::test_x`), not pytest node ids |
| BE-2 Adaptive stopping | **exists, untested in the real path** | `flakeguard/stats/adaptive.py`; `pytest tests/test_statistics.py` 10 passed | Not called by `scan()`. `grep` finds no call site outside the package `__init__` and tests. A fixed-rerun comparison exists only as `simulate_adaptive_run` |
| BE-3 Polluter bisection | **works in isolation, not wired** | `flakeguard/evidence/bisection.py`; `pytest tests/test_evidence_engine.py` 9 passed (98 s) | `EvidenceEngine` / `bisect_polluter` are not called by `scan()`. The real scan output has no polluter |
| BE-4 Knowledge tree (AST + Jedi) | **works in tests, fails in the production path** | `navigator/ast_nav.py` (`import jedi`, `jedi.goto`, `jedi.infer`), `navigator/knowledge_tree.py`; `pytest tests/test_knowledge_tree.py` 26 passed, `tests/test_navigator.py` 30 passed | `scan()` passes the JUnit id (`tests.test_orders::test_initial_order_state`) to the navigator and gets **1 node, 0 edges**. With a pytest path id (`tests/test_orders.py::test_initial_order_state`) the same demo repo gives **3 nodes, 2 edges** (probe run in section 6). Output shape is `cases[].tree/rows`, not `TreeData`. I did not verify that writer and reader of a module-level name come out as separate typed links |
| BE-5 Retrieval for diagnosis and Ask | **partial** | `/api/ask` calls `RepoQAEngine` (`rag/qa.py`, lexical scoring over AST chunks); `pytest tests/test_rag.py` 2 passed, `tests/test_api.py` 16 passed | Retrieval does not feed the live diagnosis. Navigator context only enters prompts in `llm/prompt_v4.py` / `llm/ablation.py` (offline) |
| BE-6 Verdict, tier, rule of three | **partial, one part dishonest** | `runner/orchestrator.py::_export_scan_artifacts`; `pytest tests/test_llm_stage.py` 12 passed | Verdict is only `flaky` or `real`, never `unknown`. No rule-of-three bound. **`evidence_tier` is hard-coded `"confirmed_by_intervention"` for every flaky test, and the sentence says "Passes in isolation", but no intervention or isolation check runs in `scan()`.** That breaks honesty rule 4. "Flaky" is simply "passed and failed at least once across slices" |
| BE-7 Fix proposer | **partial (stub)** | `notest/fix.py::propose_teardown_fix`; `pytest tests/test_fix.py` 1 passed | Returns a text diff with a fixed hunk header `@@ -1,5 +1,12 @@` and a fixture that swallows errors (`except Exception: pass`). No validation under 20 shuffles. No PR creation anywhere (`GitHubClient` has no PR methods). `/api/fix` hard-codes `GLOBAL_ORDERS` and `REPO_ROOT/tests/test_orders.py`, which is FlakeGuard's own path, not the scanned repo |
| BE-8 No-tests flow | **exists, untested end to end** | `notest/{scanner,generator,validator,orchestrator}.py`; `pytest tests/test_notest_repo.py` 6 passed (51 s) | No endpoint for it in `api.py` routes. I did not check which LLM provider the generator uses |
| BE-9 Baselines B1/B2/B3 | **exists, untested against the CI budget** | `eval/baseline_rerun.py`, `baselines/b2_coverage.py`, `baselines/b3_feature_classifier.py`; `pytest tests/test_injector_and_baselines.py` 9 passed; `results/baseline_metrics.csv` exists | I did not verify that the baselines run under the same CI-minute budget on the same dataset |

### CI (CI)

| ID | Status | Evidence | Gaps against the plan |
|---|---|---|---|
| CI-1 Reusable `scan.yml` | **exists, never run** | `.github/workflows/scan.yml` has `workflow_call` and `workflow_dispatch` with `repo_url` | File is on `origin/develop` and `c/eval3-actions`, **not on the default branch**. The workflows API for `vidipt9090/FlakeGuard` lists 6 workflows and `scan.yml` is not one of them. Local demo caller (`../flakeguard-demo/.github/workflows/triage.yml`) passes `repo_path`, which is not an input, and pins `@main`, where `scan.yml` does not exist. `docs/eval3/flakeguard-demo-caller.yml` pins `@develop` and passes `repo_url` |
| CI-2 Step names = stage ids | **missing** | Steps are named "Parse and resolve target repository", "Execute FlakeGuard Matrix Scan" and so on | |
| CI-3 Per-PR concurrency | **exists, untested** | `scan.yml` `concurrency` with `cancel-in-progress: true` | The group key uses `inputs.repo_url` plus PR number or ref |
| CI-4 Comment upsert | **exists, untested for scan.yml** | `scripts/post_triage_comment.py` (`COMMENT_MARKER`, `find_existing_comment`, PATCH) | scan.yml feeds it `scan_artifacts/junit.xml`, which is a copy of the **baseline** run only |
| CI-5 Post-merge | **exists, never run** | `post-merge.yml`, `scripts/report_post_merge.py`; `pytest tests/test_post_merge.py` 5 passed | Only on `c/eval3-actions`. The scan step has `continue-on-error: true`, but its outcome is passed on as `SCAN_OUTCOME`, and the reporter says "did not complete" and never "no evidence" on failure, so the failure is not hidden. No `|| true` in this file |
| CI-6 Quarantine workflow | **partial** | `quarantine-approve.yml`, `scripts/approve_quarantine.py` (collaborator permission check, refusal for real bugs); `pytest tests/test_quarantine_approve.py` 4 passed | Registered on GitHub, **0 runs ever**. It commits `quarantine.json` to the PR branch. The plan says it opens a tracking issue |
| CI-7 Slash commands | **partial** | `quarantine-approve.yml` handles `/quarantine` and `/approve-quarantine` | No `/flakeguard fix` or `/flakeguard ask` |
| CI-8 Runs in 5 to 7 min | **unmeasured** | No `scan.yml` run has ever happened. Local scan of the demo repo took 38.9 s wall clock | |

### `|| true` and error masking in workflows (rule 10)

```
cicd.yml:287        cp -r artifacts/. results/ 2>/dev/null || true
collect.yml:27      pytest ... > out/log-N.txt 2>&1 || true
scan.yml:106-109    pip install -r requirements.txt || true   (and 3 more install lines)
triage.yml:34       pytest synthetic -q --junitxml=... || true
post-merge.yml:41   continue-on-error: true  (outcome is reported, see CI-5)
```

The four `scan.yml` lines mean a target repo whose dependencies fail to install still continues to the scan. `scan.yml` also interpolates `${{ inputs.repo_url }}` straight into a shell script (command injection risk for untrusted input). I have not changed any of this in M0.

## 5. Specific checks

- **0.5 LangChain (V7):** `langchain-core` is declared in `pyproject.toml`. It is imported in exactly one module, `flakeguard/rag/langchain_retriever.py`, where `ASTCodebaseRetriever` subclasses `BaseRetriever`. That class is exercised only by `tests/test_rag.py` and exported from `flakeguard/rag/__init__.py`. **The live Ask path (`/api/ask` → `RepoQAEngine`) does not use LangChain.** The docstring says "LCEL Q&A chain", but the module contains no LCEL pipeline (no `|` composition). So today LangChain is real but off the demo path.
- **0.6 Stale reads (V9): confirmed as a risk.** `api.py::_parse_run_events` looks for findings in `<events dir>/../artifacts/<run>/findings.json`, then **`scan_artifacts/findings.json` and `out/findings.json` relative to the current working directory**. Neither directory exists right now, but any earlier run that wrote there would be shown as the current run. The same function also hard-codes the commit sha `"3f2a9c1"`, stage durations (`"4 s"`, `"38 s"`, `"12 s"`), a fixed `actions_url`, and, when no real findings exist, three invented findings ("Fails in 60% of shuffled runs", "reports.py:45"). `list_runs` also returns an invented "run-1 / Running" when no event logs exist. These are flagged `is_demo`, but the stage durations and sha are not.
- **0.7 Actions history (V1 partial):** repo is public, so I read it without a token. `GET /repos/vidipt9090/FlakeGuard/actions/runs` returned 132 runs: ci.yml 8 failed / 44 succeeded, cicd.yml 6 failed / 5 succeeded, collect.yml 1 succeeded, test.yml 9 failed / 46 succeeded, triage.yml 1 failed / 12 succeeded, **scan.yml 0 runs, post-merge.yml 0 runs, quarantine-approve.yml 0 runs.** The repo `vidipt9090/flakeguard-demo` returns HTTP 404 to an unauthenticated request, so it is private or does not exist. I cannot see its run history.
- **V11 (D23, D11):** D11 exists (2026-11-14, canonical label `real_fail`). **There is no row for D23** in `docs/eval3/decision-log.md`; it is only referred to by D18 and D32, which say it was resolved (false quarantine rate 1.0 to 0.0). I did not re-verify that number. Also, D22 to D34 are dated **2026-11-20**, which is after today (2026-11-18), and D35 to D37 are dated 11-15. Those dates are wrong or pre-written.
- **Fabricated fallback in the LLM provider:** `llm/providers.py::CachedReplayProvider.generate` returns a fixed `"label": "flaky", "root_cause": "timing", "confidence": 0.85` verdict when the prompt is not in the cache. Any metric computed through that provider can include invented answers.
- **API collision with the plan:** `api.py` already serves `/api/runs`, `/api/runs/{run_id}` and `/api/results` with different response shapes than section 6 of the plan, and `fail()` returns `{"error": ...}` where the plan wants `{"detail": ...}`. `/api/health` returns `{"status": "ok", ...}`, not `{"ok": true, "mode", "docker"}`. Adopting the plan contract on these paths would change what the old `frontend/` and `tests/test_api*.py` receive (not checked which tests would fail).

## 6. Real scan used as evidence

Command (output went to the scratchpad, not into the repo):

```
flakeguard scan ../flakeguard-demo --shuffled-n 5 --output-events <scratch>/events.jsonl --output-artifacts <scratch>/art
```

Result: exit 0, 38.9 s, 11 slices, 32 unique test ids (the demo has 8 tests; the rest are `[i-3]` repeat copies), `Pinned SHA: unknown` (`../flakeguard-demo` is not a git repo). Findings written:

| test id | verdict | tier written | pass / fail runs |
|---|---|---|---|
| `tests.test_orders::test_initial_order_state` | flaky | `confirmed_by_intervention` (hard-coded, not measured) | 4 / 4 |
| `tests.test_reports::test_async_cache_retrieval` | real | observed | 0 / 8 |
| the three `[1-3]`, `[2-3]`, `[3-3]` copies of it | real | observed | 0 / 1 each |

`where_it_lives` is `tests.test_orders:1`, a made-up line 1. `tree.json` has one case for the flaky test with 1 node and 0 edges (see BE-4). The demo's own `.flakeguard/ground_truth.json` labels `test_async_cache_retrieval` as flaky (timing) and `test_report_generation_status` as flaky (time of day). In this run the first failed 8 of 8 times (the test sleeps 0.02 s for a 0.04 s worker, so it always fails), and the second never failed. So the ground truth and the observed behaviour disagree for those two tests. I did not investigate further.

## 7. Not verified in M0

- Docker mode end to end (V8): daemon is not running.
- V1 to V6 and the Mermaid question: left for M4 and M6 where they are used.
- Whether `git push` to `origin` works from this machine (no push attempted).
- The `frontend/` starter in the spec bundle: not built or opened yet (M1).
- Streamlit / `dashboard.py` pages: not run.
