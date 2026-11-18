# Decisions and VERIFY results (Eval 3 console work)

Dated entries for the console build described in `FLAKEGUARD_SRS_AND_BUILD_PLAN.md`. The older team log is `docs/eval3/decision-log.md` (D11 to D39) and is not edited here.

## 2026-11-18

| ID | Item | Result |
|---|---|---|
| M0-1 | Working branch | Superseded by M0-2. |
| V7 | Is LangChain genuinely used? | Partly. `ASTCodebaseRetriever` subclasses `langchain_core.retrievers.BaseRetriever`, but only tests use it. The live Ask endpoint uses `RepoQAEngine` (no LangChain). See `docs/AUDIT.md` section 5. |
| V9 | Stale-file reads in progress parsing | Confirmed as a risk: `_parse_run_events` reads `scan_artifacts/findings.json` and `out/findings.json` relative to the working directory, and hard-codes a sha and stage durations. Not yet fixed. |
| V10 | Test counts 221 vs 247 | Not reproducible. Today: 311 passed, 1 skipped (312 collected) on `c/eval3-actions`. |
| V11 | D11 and D23 | D11 present. No D23 row exists in `docs/eval3/decision-log.md`. D22 to D34 carry the date 2026-11-20, which is later than today. Resolved by owner decision, see M0-3. |
| 0.7 | Has any Actions run succeeded? | Yes for `ci.yml`, `cicd.yml`, `test.yml`, `triage.yml`, `collect.yml` (public API, 132 runs read on this date). `scan.yml`, `post-merge.yml` and `quarantine-approve.yml` have 0 runs. `scan.yml` is not on the default branch. |
| V1 to V6, V8 | Not checked in M0 | Scheduled for M3 (V8) and M4 spike (V1 to V6). |
| M0-2 | Base branch (owner decision) | Owner asked to rebase onto `origin/main`. `c/eval3-console` was rebased onto `origin/main` (`a8f8308`) with `-X theirs`, because the one conflict (`flakeguard/app/server.py`) was historical: our history already had a later version of that file that includes main's demo-run fallback. Checked: the tree before and after the rebase differs only by main's two files `docs/eval2/decision-log.md` and `docs/eval2/quarantine-test-checklist.md`. The branch had not been pushed, so no force-push was involved. |
| M0-3 | Decision log (owner: fix) | In `docs/eval3/decision-log.md`, D22 to D34 were dated 2026-11-20. Each row was added in a commit dated 2026-11-15 (`git log -S`), so they now read 2026-11-15. A D23 row was added, dated 2026-11-18, marked `reconstructed`: it only restates D18 and D32, and the 1.0 to 0.0 figure is still not re-verified. |
| M0-4 | Demo repo (owner: check and fix) | Checked: `git ls-remote https://github.com/vidipt9090/flakeguard-demo` says repository not found. No `GITHUB_TOKEN` or `GH_TOKEN` is set; the stored git credential belongs to a different account (`priyalkhullar`). So the repo is private, missing, or not visible to these credentials. Fixed locally: `../flakeguard-demo/.github/workflows/triage.yml` passed `repo_path` (not an input of `scan.yml`); it now passes `repo_url`. Not fixed: that file still calls `scan.yml@main`, which does not exist on `main` until `scan.yml` is merged there (decide in M4). The local folder is not a git repo, so the change is not committed anywhere. |
| M0-5 | API paths (owner: replace) | In M2 the plan's section 6 contract replaces the existing `/api/runs`, `/api/runs/{id}` and `/api/results` handlers in `flakeguard/app/api.py`, and `fail()` will return `{"detail": ...}`. The old `frontend/` and the matching tests in `tests/test_api*.py` will be updated or retired in the same milestone. |
| M1-1 | Console scaffold | `console/` copied from the spec bundle `frontend/`; design images copied to `docs/ui/`. The old `frontend/` is untouched. `/console/node_modules/`, `/console/dist/` and `*.tsbuildinfo` are git-ignored. |
| M1-2 | CSS-only visual fix | `.header-in` and `.main` `max-width` changed from 1280px to 1344px in `console/src/styles/app.css`. With 32px padding this gives the 1280px content column the design images show (80px side margins at 1440px). No other file was changed. |
| M1-3 | CI | `.github/workflows/console-build.yml` runs `npm ci && npm run build` on pull requests that touch `console/`. Not yet run on GitHub. |
| M1-4 | Repo map default selection (owner) | `console/src/pages/RepoMap.tsx` now selects the first fault on load (when none is selected and a fault exists), so the blue ring and the Selected panel are not empty. When the tree has no faults, nothing is selected. |
