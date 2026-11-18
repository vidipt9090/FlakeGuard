# Decisions and VERIFY results (Eval 3 console work)

Dated entries for the console build described in `FLAKEGUARD_SRS_AND_BUILD_PLAN.md`. The older team log is `docs/eval3/decision-log.md` (D11 to D39) and is not edited here.

## 2026-11-18

| ID | Item | Result |
|---|---|---|
| M0-1 | Working branch | `c/eval3-console` created from `c/eval3-actions` (`146d4d3`), not from `origin/main`, because that branch holds the latest Actions work (`post-merge.yml`, `scan.yml` fixes). `origin/main` has 12 commits it lacks. Open question to the owner. |
| V7 | Is LangChain genuinely used? | Partly. `ASTCodebaseRetriever` subclasses `langchain_core.retrievers.BaseRetriever`, but only tests use it. The live Ask endpoint uses `RepoQAEngine` (no LangChain). See `docs/AUDIT.md` section 5. |
| V9 | Stale-file reads in progress parsing | Confirmed as a risk: `_parse_run_events` reads `scan_artifacts/findings.json` and `out/findings.json` relative to the working directory, and hard-codes a sha and stage durations. Not yet fixed. |
| V10 | Test counts 221 vs 247 | Not reproducible. Today: 311 passed, 1 skipped (312 collected) on `c/eval3-actions`. |
| V11 | D11 and D23 | D11 present. No D23 row exists in `docs/eval3/decision-log.md`. D22 to D34 carry the date 2026-11-20, which is later than today. Resolved by owner decision, see M0-3. |
| 0.7 | Has any Actions run succeeded? | Yes for `ci.yml`, `cicd.yml`, `test.yml`, `triage.yml`, `collect.yml` (public API, 132 runs read on this date). `scan.yml`, `post-merge.yml` and `quarantine-approve.yml` have 0 runs. `scan.yml` is not on the default branch. |
| V1 to V6, V8 | Not checked in M0 | Scheduled for M3 (V8) and M4 spike (V1 to V6). |
