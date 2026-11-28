# FlakeGuard frontend brief (replace the current single-page console)

Design reference: the "FlakeGuard: clean triage UI (proposal)" canvas (Triage, finding drawer, Results). Build exactly this structure.

## Principles
1. Two tabs only: **Triage** and **Results**. Nothing evaluative on Triage.
2. Triage answers one question: "what did this scan find, and what can I do about it?"
3. No number is hard-coded. Every value comes from the event log or an API response. Results rows show provenance (command, git sha, time, data label).
4. No ground-truth labels or test-name hints in live views. The test list comes only from the scan.
5. Plain language in the UI ("Fails in 60% of shuffled runs", not "fail_rate 0.60 [0.22, 0.61]"). Raw numbers go in the drawer or Results.

## Decisions (log in `docs/eval3/decision-log.md`)
- Framework: keep the React `frontend/`. Delete `flakeguard/app/static/` and fold `app/server.py` into one FastAPI app (confirm which of `api.py` / `server.py` is kept).
- Three tabs: Triage, Pipeline, Results.

## Pipeline tab
- Left: recent runs (trigger, repo @ sha, status chip: Running, Done, Could not build), from the GitHub API (workflow runs) plus local scans.
- Right, for the selected run: stage bars with durations (Clone, Run matrix, Evidence, Verdict, PR comment) from the event log; a "Human steps" checklist (bot comment posted, waiting for maintainer approval, quarantine commit added); latest event-log lines; "Open in GitHub Actions" link.
- Read-only. Durations are computed from event timestamps, never typed in.

## Triage tab
- **Repo bar:** one input accepting a full GitHub URL, `owner/repo`, or a local path, plus Run scan. (Fix: accept the `owner/repo` shorthand; it currently errors.) No N-runs box or Docker toggle on the main screen; move them to an "Options" disclosure.
- **Progress strip:** Clone, Run matrix, Evidence, Verdict, Report. Each stage reads its state from the JSONL event log (`stage`, `type`). Link "Open GitHub Actions run" appears when a run URL exists.
- **Findings feed:** cards, one per finding, newest first, filter chips All / Flaky / Real bugs. Card fields: badge (Flaky, Real bug), root-cause label, test name, one plain-language sentence, evidence summary, evidence tier.
- **Actions per card:** Propose fix PR (only when a polluter exists), Quarantine, See the proof. Quarantine is disabled for real bugs and shows "Quarantine unavailable".
- Empty state: "No flaky tests found in N runs." Never say "stable".

## Finding drawer (opens from "See the proof")
Sections: How we know (observed, reproduced, confirmed by intervention), The polluter (file:line and snippet), Ask about this failure (RAG answer with file:line citations; refuse when nothing is retrieved), footer actions.

## Results tab
Segmented control Planted / Injected / Natural. One table: method, F1 with 95% CI, root-cause accuracy, false quarantine, source. Each source chip opens the command, sha and time. Rows with missing provenance are not rendered. Show "under review" on any metric with an open decision (D23).

## Data contracts
- `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events` (SSE). Event: `ts, run_id, stage, type, test_id?, data`.
- `POST /api/scan {repo}` starts a scan (dispatches the GitHub workflow or a local run).
- `POST /api/quarantine {test_id}` must apply the same write-permission and real-bug checks as `scripts/approve_quarantine.py`.
- `POST /api/ask {test_id, question}`.

## Remove or move
KPI stat cards, the terminal log pane, the causal-intervention table, the ablation table, the risk-coverage slider (move the last two to Results), the test-picker buttons labelled with root causes, and the static `app/static/` UI if the React app is the chosen one (ask me which).

## Done when
`make check` passes, the frontend has tests for empty, running, finding and real-bug states, a provenance test rejects constants, and every decision is in `docs/eval3/decision-log.md`.
