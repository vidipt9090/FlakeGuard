# FlakeGuard: Software Requirements and Step-by-Step Build Plan

Version 1.0 · written 18 Nov 2026 · owner: Vidipt (role A: data, CI, baselines)
Repo: `vidipt9090/FlakeGuard` (same repo, reframed) · Course: Intelligent Developer Tools and AI DevOps Workflows (Eval 3)

> **How to use this file (read first, Claude Code).**
> This file is the single source of truth. Work through section 9 one milestone at a time.
> Do not start a milestone until the previous gate has passed. After each milestone, stop and report using the format in section 9.1.
> UI images are in `docs/ui/`. A working frontend starter is in `frontend/` (it builds and runs on mock data). **Do not redesign the UI. Match the images.**
> Anything marked **VERIFY** is believed but not confirmed. Check it against current docs or by running it, and record the result in `docs/DECISIONS.md`.

---

## Table of contents

1. Product statement
2. Rubric traceability (every checkbox mapped)
3. System overview and architecture
4. Honesty rules (apply everywhere)
5. UI specification (screen by screen, with images)
6. API contract
7. Backend and CI requirements
8. Non-functional requirements
9. Step-by-step implementation plan (milestones M0 to M9)
10. Demo script and fallback plan
11. Risks and items to VERIFY
12. Report and README outline
13. Appendix: frontend file map, definition of done

---

## 1. Product statement

**FlakeGuard is a PR reviewer that gates new tests for determinism. When it finds flakiness it diagnoses it and opens a validated fix PR.**

It runs inside GitHub Actions on every pull request. A custom live console (this file's UI) shows the run as it happens, next to the real pull request on GitHub.

### 1.1 What it does

1. **Gate:** on a PR, run the test suite under perturbation (default order, shuffled order with several seeds, each flagged test alone). Decide per test: flaky, real failure, or unknown.
2. **Diagnose:** for order-dependent flakes, find the polluter test (bisection), find the shared state both tests touch (AST + Jedi), and explain it in plain language with file and line.
3. **Triage:** post one comment on the PR (updated in place). Never turn a flaky failure into a false red PR. Never hide a real bug.
4. **Fix:** on request, open a fix PR **on the user's fork**. It is validated under shuffle first. A person merges it.
5. **No tests?** Scan for risky spots (clock, randomness, global state, sleep), write targeted tests, and keep only those that give the same result every time.
6. **After merge:** re-run and say "no evidence of flakiness in N runs after this change". Never "fixed" or "stable".

### 1.2 Research questions

| ID | Question | Where answered |
|---|---|---|
| RQ1 | Does perturbation find more flaky tests than baselines B1 (plain rerun), B2 (coverage-based), B3 (classifier) within a 5 to 7 minute CI budget? | Results screen, baselines table |
| RQ2 | How many runs does a decision take, adaptive stopping vs fixed reruns? | Results screen, RQ2 card |
| RQ3 | Does PR-native triage avoid false-red PRs without hiding real bugs? | Results screen, RQ3 card |
| RQ4 | Does retrieval through the AST + Jedi knowledge tree improve diagnosis and validated-fix success? (supporting RQ) | Results screen, ablation table |

### 1.3 Out of scope

- Merging anything automatically.
- Fixes other than order dependence (the fix proposer only does an autouse teardown fixture for order dependence).
- Claiming a test is "fixed" or "stable".
- Any number shown that did not come from a real run (see section 4).

---

## 2. Rubric traceability

The course handout has **never been seen**. This table uses the rubric Vidipt pasted. When the handout is available, re-check every row.

### 2.1 Eval 3

| Rubric item | Weight | What satisfies it | Where it appears | Evidence artefact |
|---|---|---|---|---|
| Retrieval and automation integration | 15% | Retrieval from the AST + Jedi tree feeds diagnosis and Ask. Automation = reusable `scan.yml`, post-merge workflow, quarantine workflow, slash commands. | Live (pipeline stages), Findings (Ask), Repo map | Workflow files, one real Actions run URL, retrieval ablation table |
| Multiple tools | 10% | GitHub Actions, pytest (shuffled), Docker isolation, AST + Jedi, LangChain (VERIFY real use), LLM, GitHub API. Each shown as a tool chip on its pipeline stage. | Live | Tool chips on screen |
| Prompt design, code search, evaluation | 5% | Documented prompts, code search over the tree, RQ4 ablation with provenance. | Results, `docs/PROMPTS.md` | Ablation table |
| Completeness and innovation | 5% | Full PR loop, no-tests flow, polluter bisection, repro command, evidence tiers. | All | Demo |
| Presentation, team contribution, usability | 5% | Console usability, states, accessibility. Team contribution lives in the report/README (section 12), not in the UI. | Console, report | README table |

### 2.2 Eval 2 (carried over, must still be true)

| Rubric item | Weight | Satisfied by |
|---|---|---|
| RAG Q&A with LangChain or LlamaIndex | 10% | Ask box on Findings (answers cite file:line, says so when nothing is found). VERIFY LangChain is genuinely used, not only declared. |
| GitHub Actions | 10% | `scan.yml`, post-merge, quarantine |
| Test generation | 5% | No-tests flow |
| Integration and documentation | 5% | This file, README, `docs/DECISIONS.md` |

### 2.3 Teacher's stated wishes (from notes)

- Live GitHub demo **and** live dashboard, side by side.
- Static RAG ablation results **plus** the dynamic demo.
- The knowledge tree is a main feature (interpretation confirmed with the professor). It must be navigable. That is the Repo map screen.

---

## 3. System overview and architecture

```
 GitHub (pull request, Actions run, bot comment)
        ^                      |
        | comment, check,      | webhook / workflow_run
        | fork PR              v
 +--------------+     +---------------------+     +------------------------+
 | scan.yml     |<----| FlakeGuard backend  |<----| Console (this frontend)|
 | (reusable)   |---->| HTTP API, polling,  |---->| React, polls /api      |
 | pytest runs  |     | engine, LLM calls   |     +------------------------+
 +--------------+     +---------------------+
                              |
                  +-----------+-------------+
                  | engine: perturbation,   |
                  | bisection, AST + Jedi   |
                  | tree, evidence tiers,   |
                  | fix proposer, no-tests  |
                  +-------------------------+
```

### 3.1 Two run modes

| Mode | When | How the console gets live data |
|---|---|---|
| `actions` | Real PR on GitHub | Backend polls the GitHub jobs/steps API for the run and maps steps to pipeline stages. VERIFY the exact endpoint and fields in current docs. |
| `local` | Actions unreachable, or a pasted repo | Backend runs the scan as a subprocess that writes a progress file; backend serves it. |
| `recorded` | Fallback during the demo | Backend replays a saved real run. **The UI shows the "recorded run" banner.** |

### 3.2 Live data design (decide in M4 with a spike)

The Live screen needs one mark per run in real time. ~~Artifacts are believed to be readable only after a job ends (VERIFY), so a single long job cannot stream per-run results.~~

**Spike result, 2026-11-21 (observed in `vidipt9090/flakeguard-demo`, evidence in `docs/spikes/m4/`, details in `docs/DECISIONS.md` M4-1 to M4-9):** the belief above was **wrong**. An artifact uploaded by a step was listed by the API and downloadable (157 bytes, `{"runsDone":3}`) while the run and the job were still `in_progress`. Job and step status were visible 0.4 to 8.7 s after GitHub's own timestamp (median 2.5 s). A matrix job per seed gives one live job per seed, but a job's conclusion is whole-suite pass or fail for that seed, so the per-test mark comes from a per-seed JUnit artifact read mid-run.

**Proposed design:** make each shuffled seed its own matrix job in `scan.yml`. Each job's pass/fail conclusion becomes one dot in the matrix. Stage progress comes from step status. Run the seeds in parallel to stay inside the 5 to 7 minute budget.
**Fallback:** one job, stage-level progress only, and the dot matrix fills after the job. Record which one you used in `docs/DECISIONS.md`.

**Chosen (2026-11-21): the proposed design**, with each seed job also uploading its JUnit file as an artifact (`junit-shuffled-N`) that the backend reads mid-run to fill the dot matrix for the followed test. The fallback is not needed.

### 3.3 Hosting during the demo (unresolved, decide in M9)

Options: (a) backend on the laptop plus a tunnel so the GitHub side can call back, (b) a hosted backend. Choose the one that survives a bad network. Always have the `recorded` fallback ready.

---

## 4. Honesty rules (apply to UI, backend, PR text, report)

1. **Every value on screen comes from a real run.** Anything else must carry a visible "Demo data" badge. (`frontend/src/api/client.ts` exports `USE_MOCK`, and the header shows the badge.)
2. **Missing is `null`, rendered as a dash.** Never a placeholder number.
3. **Words:** say "no evidence of flakiness in N runs". Never "fixed", "stable", "safe".
4. **Evidence tiers:** `observed` (seen failing), `reproduced` (reproduced by a targeted run or repro command), `intervention-confirmed` (a change removed it). Show the tier on each finding.
5. **Rule of three:** with 0 failures in n runs, the failure rate could still be up to about 3/n. Use this wording on "no findings" and "unknown".
6. **Generated tests record current behaviour.** They do not prove correctness. Say so on the no-tests screen and in the PR.
7. **Labels:** report results separately for injected, natural and planted flakes. Planted-only results are circular and must be labelled so.
8. **Never silently mask failure.** No `|| true` around a step whose failure matters. A scan that did not finish shows "The scan stopped early" and **no verdict**.
9. **Quarantine** is refused for real failures (fails ~every run) and for requesters without write permission.
10. **Fixes** are opened on the fork. A person merges. FlakeGuard never merges.

---

## 5. UI specification

**Stack:** React 18, Vite, TypeScript, React Router. No UI library. Styles in `frontend/src/styles/`. Tokens in `tokens.css`.
**Do not use emoji.** All interactive things are real `button`, `a`, `label`, `input`. Every status has text and an icon, never colour alone.

**Design tokens**

| Token | Value | Use |
|---|---|---|
| ground | `#F6F6F3` | page background |
| ink | `#15171A` | text |
| blue | `#1D4ED8` | primary action, selection |
| flaky | text `#8A3A0B` on `#FFF1E6`, line `#B54708` | flaky |
| real | text `#8F1D14` on `#FEECEA`, line `#B42318` | real failure |
| unknown | text `#3B4048` on `#EEF0F3`, dashed line `#6B7078` | unknown |
| pass | `#175CD3` | passed run mark |
| font | Inter; mono = ui-monospace stack | |

**Screens and routes**

| Route | Screen | Image |
|---|---|---|
| `/` | Live | `docs/ui/01-live.png` |
| `/findings` | Findings | `docs/ui/02-findings.png` |
| `/repo-map` | Repo map | `docs/ui/03-repo-map.png` |
| `/results` | Results | `docs/ui/04-results.png` |
| `/no-tests` | Repo with no tests | `docs/ui/05-no-tests.png` |
| `/states` | Reference: screen states | `docs/ui/06-states.png` |
| `/bot-text` | Reference: text posted on GitHub | `docs/ui/07-bot-text.png` |

The images show **example data for design review**. They are not real results.

---

### 5.1 Live (`/`)

![Live](docs/ui/01-live.png)

**Purpose.** Show the run progressing while the real PR sits next to it.

**Elements, top to bottom**
1. **Scan target form:** Repository or pull request (text), Source (Pull request / Paste a repo / Sample repo), Shuffled runs (number, default 10), "Isolate in Docker" checkbox with the note "(runs on this machine)", **Run scan** button.
2. **Links line:** "Repo has no tests? See how FlakeGuard handles it", "Screen states", "Text the bot posts on GitHub".
3. **Banner area:** shows one state from section 5.6 when relevant.
4. **PR status strip:** `PR #N · title`, state chip, "FlakeGuard check: <state>", "Post-merge check: <state>", links "Open PR on GitHub" and "Open Actions run" (only when URLs exist).
5. **Pipeline card (left):** nine stages: Checkout, Install, Baseline, Shuffled runs, Isolated runs, Bisection, Retrieval, Verdict, PR comment. Each has a state dot (done, running, pending, failed), a **tool chip**, a detail line, and a time or "running"/"waiting".
6. **Right now card:** test under perturbation, condition (for example "Shuffled order · seed 1042"), three counters: Runs done, Failures, Tests flagged.
7. **Outcome by condition card:** dot matrix, one mark per run, rows Baseline / Shuffled / Isolated. Filled = passed, crossed ring = failed, empty ring = not run yet.

**Data:** `GET /api/runs/{id}` (poll every 2 s while status is `running`).
**Behaviour:** pressing Run scan calls `POST /api/runs`, stores the run id, and starts polling. Stop polling when `status` is `complete` or `failed`.

**Acceptance criteria**
- AC-L1: Pressing Run scan on a real PR shows stage changes within 5 s of the real GitHub step changing.
- AC-L2: Every tool chip names a tool actually used in that stage.
- AC-L3: Counters and matrix equal the numbers in the PR comment once the run completes.
- AC-L4: Backend unreachable → banner `actions-unavailable` with the reason, no spinner forever.
- AC-L5: Run failed or incomplete → banner `scan-incomplete`, **no verdict shown anywhere**.
- AC-L6: In mock mode the "Demo data" badge is visible.

---

### 5.2 Findings (`/findings`)

![Findings](docs/ui/02-findings.png)

**Purpose.** The diagnosis, in plain language, with proof and actions.

**Elements**
1. **Left list**, grouped: *Real failures*, *Flaky*, *Needs more evidence*. Each item: severity chip (Blocking / Suggestion · fix ready / Unknown), test name (mono), one-line summary. Selected item has a 2 px blue border.
2. **Finding card:** test name, verdict chip (for example "Flaky · order-dependent"), evidence tier chip, file:line. Rows:
   - **Why:** plain sentence with file:line links.
   - **Evidence:** bullets (counts per condition, bisection result, whether the failing path is outside the PR's changed lines).
   - **Where it lives:** breadcrumb chips `tests/ › test_report.py › test_report_total › reads CACHE ← written by test_cache_warm`. Link "Open in Repo map".
   - **Did:** what FlakeGuard did on GitHub (for example "Posted this finding on PR #7. Nothing else has been changed.").
   - **Limits:** what is not ruled out.
3. **Two code panes:** polluter (writer) and victim (reader), line numbers, the key line tinted (red for writer, amber for reader) with a one-line note under it.
4. **Reproduce it on your machine:** dark code box with the exact two-test pytest command, and **Copy command**.
5. **What do you want to do?** buttons **Propose fix PR** (primary), **Re-verify, 5 runs**, **Quarantine this test**, plus the one-line rules note.
6. **Fix preview:** one-sentence summary, file name, diff (lines starting with `+`), "Checked before opening: …", "Does not prove: …".
7. **Ask about this finding:** question box, **Ask**, answer with file:line citations and "Answered from N retrieved code chunks. If nothing relevant is found, the answer says so."

**Data:** `GET /api/runs/{id}/findings`; actions call `POST /api/findings/{id}/fix | reverify | quarantine | ask`.

**Acceptance criteria**
- AC-F1: Every claim in Why/Evidence is backed by a number the engine produced (no LLM-invented counts).
- AC-F2: Repro command, run locally on the demo repo, fails when the polluter runs first. (This is checked in M5.)
- AC-F3: Quarantine on a real failure shows the `quarantine-refused` banner and calls nothing on GitHub.
- AC-F4: Ask with nothing relevant shows `ask-nothing`, not an invented answer.
- AC-F5: Propose fix PR is disabled when `fix` is null.
- AC-F6: "Unknown" findings say "Too few to call it flaky" and show the rule-of-three bound.

---

### 5.3 Repo map (`/repo-map`) , the AST + Jedi tree (main USP)

![Repo map](docs/ui/03-repo-map.png)

**Purpose.** Let someone see the repository as a **tree**, find the faults at a glance, and see the shared value that links two tests.

**Layout (left to right):** Repository → Files → Tests → Shared state.
- Root card is dark and shows `N tests · M faults`.
- File cards show a roll-up ("1 flaky", "1 polluter", "1 real failure", "1 unknown").
- Test cards: **faults have a thick coloured outline, an icon, and a text label.** Clean tests are flat and quiet with "Passes in every run".
- **Shared state node** (for example `CACHE`, with `file:line`) sits on the right. A red **writes** arrow goes from each writer test into it. An amber **reads** arrow goes from it to each reader test.
- Elbow connector lines join root → files → tests.
- The selected test has a blue ring.

**Controls:** Find a test or file (dims non-matches), Show faults only, Next fault (cycles through faults top to bottom), Collapse all / Expand all. Clicking a file folds its tests. Clicking a test selects it. The Selected panel shows name, path, label, and "Open the full finding".

**Implementation note.** The starter already does this: `components/treeLayout.ts` computes positions from data, `components/RepoTree.tsx` draws cards (absolute positioned) and one SVG for lines and arrows. **Keep the fixed column geometry** (repo x=24, file x=290, test x=570, state x=910; card heights 56/56/64/120; row pitch 88).

**Data:** `GET /api/runs/{id}/tree` (see `TreeData` in `types.ts`).

**Acceptance criteria**
- AC-R1: The tree is built from the scanned repo (AST for structure, Jedi for the name resolution that finds readers and writers of shared state). No hard-coded node.
- AC-R2: Every shared-state link is backed by a real AST/Jedi reference at a real file:line.
- AC-R3: On a repo with 200 tests, "Show faults only" and "Collapse all" keep the screen usable (no horizontal scroll for the default view).
- AC-R4: Keyboard: every test and file is reachable by Tab and operable with Enter.
- AC-R5: Fault state is never colour only (icon and text present).

---

### 5.4 Results (`/results`)

![Results](docs/ui/04-results.png)

**Purpose.** Static, recorded results for the report: RQ4 ablation, RQ1 baselines, RQ2, RQ3.
- Toggle **Injected / Natural / Planted** (changes which label type is shown). Note on screen: planted-only would be circular.
- **RQ4 table:** rows = context given to the model (for example: none, file only, AST tree only, AST + Jedi tree). Columns: diagnosis matches the known cause, fix passes validation under shuffle, code sent to the model.
- **RQ1 table:** rows = Perturbation, B1 rerun, B2 coverage, B3 classifier. Columns: flaky tests found, wrongly flagged, CI minutes used.
- **RQ2 / RQ3 cards:** two numbers each.
- Each table ends with a **provenance footer**: Dataset, Label type, N, Command, Date, Commit.

**Data:** `GET /api/results?label=injected|natural|planted`. Backend serves files produced by `scripts/run_eval.py` (you create it in M8).

**Acceptance criteria**
- AC-S1: Cells with no run show a dash. Footer shows "[filled by the run]" until a run exists.
- AC-S2: Every number can be regenerated from the Command in its footer.
- AC-S3: No table mixes label types.

---

### 5.5 Repo with no tests (`/no-tests`)

![No tests](docs/ui/05-no-tests.png)

**Flow:** (1) Find risky spots, (2) Write tests, (3) Check them, (4) Open PR on your fork. Shows: risky spots table (Where, What the code does, Why it is risky, Test), a before/after code pair, three checks (Runs without errors, Passes on the current commit, Same result in 10 shuffled runs), the notice "These tests record what the code does today. They do not prove it is correct.", buttons **Open PR on your fork** and **Drop this test**.

**Data:** `GET /api/runs/{id}/no-tests`.

**Acceptance criteria**
- AC-N1: A test is kept only if it runs, passes at HEAD, and is identical over k shuffled runs.
- AC-N2: Dropped tests are listed with the reason, never silently removed.

---

### 5.6 Screen states (`/states`)

![States](docs/ui/06-states.png)

Nine states. Wording lives in `frontend/src/copy.ts` and **must not be reworded in components**.

| State | Shown on | Meaning |
|---|---|---|
| first-run | Live | Nothing scanned yet |
| actions-unavailable | Live | Cannot reach GitHub Actions, fell back to local |
| docker-not-running | Live | Docker requested but not running; nothing was run |
| scan-incomplete | Live, post-merge | Run did not finish; no verdict |
| recorded-run | All | Replay of a saved real run |
| no-findings | Findings | "No evidence of flakiness in N runs" + rule-of-three note |
| quarantine-refused | Findings | Real failure or no write access |
| post-merge | Live | "No evidence of flakiness in N runs after this change" |
| ask-nothing | Findings | Retrieval found nothing |

### 5.7 Bot text (`/bot-text`)

![Bot text](docs/ui/07-bot-text.png)

The exact wording the bot posts on GitHub: PR comment (table, why/where/limits, slash commands, "updated in place on every push"), fix PR description (What this changes / How it was checked / What it does not prove / How to undo / Who merges), post-merge note, quarantine refusal. **Backend templates must reproduce this wording** (put them in `flakeguard/bot_templates.py` or the repo's equivalent, with a test that snapshots them).

---

## 6. API contract

The TypeScript source of truth is `frontend/src/types.ts`. Mirror it in the backend with Pydantic models (or the repo's equivalent) and add a contract test (M2).

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/health` | | `{ "ok": true, "mode": "actions"|"local", "docker": true|false }` |
| POST | `/api/runs` | `StartRunRequest` | `{ "id": string }` |
| GET | `/api/runs/{id}` | | `RunStatus` |
| GET | `/api/runs/{id}/findings` | | `Finding[]` |
| GET | `/api/runs/{id}/tree` | | `TreeData` |
| GET | `/api/runs/{id}/no-tests` | | `NoTestsPlan` |
| POST | `/api/findings/{id}/ask` | `{ "question": string }` | `AskAnswer` |
| POST | `/api/findings/{id}/fix` | | `{ "prUrl": string }` |
| POST | `/api/findings/{id}/reverify` | `{ "runs": number }` | `{ "started": true }` |
| POST | `/api/findings/{id}/quarantine` | | `{ "issueUrl": string }` or HTTP 409 with `detail` when refused |
| GET | `/api/results?label=` | | `ResultsData` |

**Errors:** non-2xx returns `{ "detail": string }`. The UI shows `detail` verbatim, so it must be human-readable.
**Polling cost:** the console polls the backend every 2 s. The backend must **not** forward every poll to GitHub. Cache GitHub responses for about 3 s (VERIFY rate limits for the token type used).
**Example `RunStatus` (shortened):**

```json
{
  "id": "run-2026-11-20-001",
  "target": "demo/inventory#7",
  "mode": "actions",
  "status": "running",
  "pr": { "number": 7, "title": "Add stock cache", "state": "open",
          "checkState": "in progress", "postMergeState": "waiting for merge",
          "prUrl": "https://github.com/...", "runUrl": "https://github.com/..." },
  "stages": [{ "id": "checkout", "name": "Checkout", "detail": "…", "tool": "GitHub Actions", "time": "6 s", "state": "done" }],
  "current": { "test": "tests/test_report.py::test_report_total", "condition": "Shuffled order · seed 1042" },
  "counters": { "runsDone": 6, "runsTotal": 10, "failures": 3, "flagged": 1 },
  "matrix": [{ "label": "Shuffled", "summary": "6 runs done: 3 passed, 3 failed", "cells": ["pass","fail","pass","fail","fail","pass","none","none","none","none"] }],
  "notice": null
}
```

---

## 7. Backend and CI requirements

IDs are used in the build plan.

### 7.1 Engine (reuse; do not rewrite)

| ID | Requirement |
|---|---|
| BE-1 | Perturbation runner: default order ×3, shuffled with N seeds, isolated per flagged test. Records every run's outcome per test. |
| BE-2 | Adaptive stopping: stop early when evidence is clear (RQ2). Fixed-rerun mode for comparison. |
| BE-3 | Polluter bisection, reports steps taken and the polluter test id. |
| BE-4 | Knowledge tree: AST for structure, Jedi for name resolution. Detect writers and readers of module-level shared state. Output `TreeData`. |
| BE-5 | Retrieval over the tree for diagnosis and Ask. Answers cite file:line or say nothing was found. |
| BE-6 | Verdict: flaky (with subtype), real, unknown. Evidence tier. Rule-of-three bound for unknown. |
| BE-7 | Fix proposer: autouse teardown fixture for order dependence only. Validated under shuffle (default 20 runs) before a PR is opened. |
| BE-8 | No-tests flow: risky-spot scan, LLM-written targeted tests, validation (runs, passes at HEAD, deterministic over k shuffles). |
| BE-9 | Baselines B1, B2, B3 implemented against the same dataset and CI budget. |

### 7.2 GitHub Actions

| ID | Requirement |
|---|---|
| CI-1 | Reusable workflow `scan.yml` (`workflow_call` plus `workflow_dispatch` with a `repo_url` input). |
| CI-2 | Step names equal stage ids so the backend can map steps to stages. |
| CI-3 | Per-PR `concurrency` group so a new push cancels the old scan. |
| CI-4 | PR comment **upserted** (one comment, edited in place). |
| CI-5 | Post-merge workflow posts "No evidence of flakiness in N runs after this change". On failure it says the scan did not finish. **No `|| true` masking.** |
| CI-6 | Quarantine workflow: checks the requester has write permission, refuses real failures, opens a tracking issue. |
| CI-7 | Slash commands `/flakeguard fix | ask … | quarantine <test>` handled via `issue_comment`. |
| CI-8 | Runs inside the 5 to 7 minute budget on the demo repo. |

**VERIFY before relying on these (record results in `docs/DECISIONS.md`):**
- `workflow_dispatch` and `issue_comment` workflows only run if the file is on the **default branch**.
- Pushes made with `GITHUB_TOKEN` do **not** trigger other workflows.
- Pull requests from forks do **not** get repository secrets.
- Artifacts are readable only after the job ends (affects live granularity, section 3.2).
- Whether Mermaid renders inside PR comments (not required; do not depend on it).

### 7.3 Bot behaviour

| ID | Requirement |
|---|---|
| BOT-1 | Wording equals section 5.7. |
| BOT-2 | Fix PR targets the user's fork, never the upstream default branch. |
| BOT-3 | A scan that did not finish posts "did not finish" and no verdict. |

---

## 8. Non-functional requirements

| ID | Requirement |
|---|---|
| NF-1 | **Accessibility:** WCAG 2.1 AA contrast, visible focus, all controls keyboard operable, status never colour only, `prefers-reduced-motion` respected. |
| NF-2 | **Performance:** Live screen updates within 5 s of the real change; Repo map renders 500 tests without freezing (use "faults only" default above 200 tests). |
| NF-3 | **Security:** tokens only in backend env, never sent to the browser. Docker isolation when requested; if Docker is not running, **do not** silently run unisolated. Treat repo code as untrusted. |
| NF-4 | **Reliability:** demo fallback `recorded` mode works with no network. |
| NF-5 | **Reproducibility:** every Results number has a command that regenerates it. |
| NF-6 | **Browser support:** current Chrome and Firefox, 1280 px and 1440 px wide (laptop on the demo screen). |

---

## 9. Step-by-step implementation plan

### 9.0 Time reality (read this)

Today is **18 Nov 2026**. The Eval 3 live demo was noted as **20 Nov 2026**. If that date still stands, there are about two days. Build in **priority tiers** and stop at the end of each:

| Tier | Contents | Needed for the demo? |
|---|---|---|
| **P0** | M0, M1, M2, M3, M5 (tree + findings from real data), one real Actions run (part of M4), M9 recorded fallback | Yes |
| **P1** | M4 full (matrix-per-seed), M6 (fix PR, quarantine, slash commands) | Strongly wanted |
| **P2** | M7 (no-tests), M8 (Results from real runs) | If time; the screens exist and show dashes honestly |

If the date has moved (earlier notes mention a week), do M0 to M9 in order.

### 9.1 Session protocol (every milestone)

1. Work on branch `c/eval3-console`. Small commits. Never force-push.
2. Do the steps in order. Do not start the next milestone before the **Gate** passes.
3. Run the gate commands yourself. **Never claim a gate passed without running it.** Paste the real output.
4. **Report format after each milestone:**
   - What changed (files).
   - Gate results (commands + real output, trimmed).
   - What you did **not** verify.
   - Decisions made (also appended to `docs/DECISIONS.md` with today's real date).
5. If something is unclear, stop and ask. Do not fill gaps with assumptions.
6. Never invent function names, library methods or API fields. If unsure, read the installed package or the current docs.

---

### M0. Audit (no feature code)

**Goal:** know exactly what exists before changing anything.

| Step | Do | Output |
|---|---|---|
| 0.1 | `git fetch --all`, list branches, note the head of `main`, `develop`, `c/eval3-actions`. | notes |
| 0.2 | Inventory the repo: engine modules, `api.py` (framework?), workflows in `.github/workflows/`, existing frontend folder, `scripts/`, tests. | `docs/AUDIT.md` |
| 0.3 | Run the existing test suite. Record pass/skip counts and the reason for skips. | in AUDIT.md |
| 0.4 | For each requirement BE-1 … BE-9 and CI-1 … CI-8, mark: exists and works / exists untested / missing. Cite file and function. | table in AUDIT.md |
| 0.5 | Check whether LangChain is genuinely used by the retrieval/Ask path (imports and call sites), not only declared in dependencies. | line in AUDIT.md |
| 0.6 | Check whether `_parse_run_events` or similar reads stale files from `out/` or `scan_artifacts/`. | line in AUDIT.md |
| 0.7 | Confirm whether any GitHub Actions run has ever succeeded (look at run history if you have access; otherwise say you cannot see it). | line in AUDIT.md |

**Gate:** `docs/AUDIT.md` exists, every BE/CI row is filled, nothing is marked "works" without a command that proves it.

---

### M1. Scaffold the console from the starter (frontend only)

**Goal:** the approved UI running on mock data inside the repo.

| Step | Do |
|---|---|
| 1.1 | Copy `frontend/` from this bundle to `console/` at the repo root. Leave any existing frontend untouched for now. |
| 1.2 | `cd console && npm install && cp .env.example .env && npm run build`. |
| 1.3 | `npm run dev`, open each route, compare against `docs/ui/*.png` at 1440 px. Fix visible differences in CSS only. |
| 1.4 | Add `console/README.md` run instructions (already provided). |
| 1.5 | Add a CI job `console-build` that runs `npm ci && npm run build` on pull requests touching `console/`. |

**Gate**
```bash
cd console && npm ci && npm run build        # exits 0
```
Then take screenshots of all 7 routes and save as `docs/ui-built/*.png`. State honestly which differ from the design and why.

---

### M2. Backend contract layer with recorded data

**Goal:** the console talks to a real backend, before any live logic exists.

| Step | Do |
|---|---|
| 2.1 | Create Pydantic models mirroring `console/src/types.ts` exactly (same field names, camelCase in JSON). |
| 2.2 | Implement all endpoints in section 6. Initially they read from a **recorded run** directory `recorded/<run-id>/*.json`. |
| 2.3 | Produce the first recorded run **from a real scan** of the demo repo (not hand-written). Save command and commit hash next to it (`recorded/<run-id>/PROVENANCE.txt`). |
| 2.4 | Add contract tests: every endpoint's JSON validates against the models; a snapshot test fails if a field is renamed. |
| 2.5 | CORS: allow the console origin in dev. In dev the Vite proxy forwards `/api`, so no CORS is needed. |
| 2.6 | Set `VITE_USE_MOCK=0`, run the console against the backend. |

**Gate**
```bash
pytest -q tests/test_api_contract.py          # passes
curl -s localhost:8000/api/health
curl -s localhost:8000/api/runs/<run-id> | python -m json.tool | head
```
And: all 4 main screens render from the recorded run with **no** "Demo data" badge and a visible "recorded run" banner.

---

### M3. Live local run

**Goal:** pressing Run scan starts a real scan and the Live screen updates.

| Step | Do |
|---|---|
| 3.1 | `POST /api/runs` spawns the scan as a subprocess (one run at a time; return 409 if one is active). |
| 3.2 | The engine writes `progress.json` atomically (write temp file, then rename) after each stage and after each individual run. Fields as in `RunStatus`. |
| 3.3 | `GET /api/runs/{id}` serves that file. A run directory is created fresh for each run so stale files can never be read. |
| 3.4 | Docker mode: if requested and Docker is not running, set `notice.kind = "docker-not-running"` and **do not run**. |
| 3.5 | If the subprocess dies, set status `failed` and `notice.kind = "scan-incomplete"`. |

**Gate**
1. Start the backend and console. Press Run scan on the demo repo. Screen-record 30 s showing the stages and the dot matrix filling.
2. Kill the subprocess mid-run: the console shows "The scan stopped early" and no verdict.
3. Stop Docker, tick Isolate in Docker, press Run: the console shows "Docker is not running" and nothing runs.

---

### M4. GitHub Actions mode

**Goal:** the same live screen, driven by a real GitHub run.

| Step | Do |
|---|---|
| 4.1 | **Spike (time-box 2 h):** confirm with a throwaway workflow (a) job and step status are readable through the API while running, (b) whether matrix jobs per seed give one live result each, (c) whether artifacts are readable mid-run. Record results in `docs/DECISIONS.md`. Choose the design in section 3.2. |
| 4.2 | Make `scan.yml` reusable and dispatchable (CI-1). Step names equal stage ids (CI-2). |
| 4.3 | Backend `ActionsRunSource`: given a run id, fetch jobs/steps, map to `Stage[]` and `matrix`. Cache for about 3 s. |
| 4.4 | PR comment upsert (CI-4). One comment per PR, edited on every push. |
| 4.5 | Per-PR `concurrency` (CI-3). |
| 4.6 | Post-merge workflow (CI-5). Fix any `|| true`. |
| 4.7 | Add `mode: "actions"` and the two GitHub links to `RunStatus.pr`. |

**Gate**
- One **real** run on the demo repo triggered by opening a PR. Paste the Actions run URL, the PR URL, and a screenshot of the console next to the PR.
- Push a second commit to the PR: the **same** comment is edited, not duplicated.
- Wall-clock of the scan, from PR open to comment posted, is stated (target within the 5 to 7 minute budget).

---

### M5. Real findings and the Repo map

**Goal:** the knowledge-tree screen runs on real data. This is the main USP.

| Step | Do |
|---|---|
| 5.1 | Implement `build_tree(repo) -> TreeData` using AST for the file/test structure and Jedi to resolve references to module-level state (BE-4). |
| 5.2 | Detect writers and readers of shared state: a test that assigns or mutates a module-level name is a writer; one that reads it is a reader. Record file:line for each. |
| 5.3 | Merge verdicts into the tree (status, label, finding id, roll-up `faults`). |
| 5.4 | Implement `findings` with `why`, `evidence`, `lives`, `writer`/`reader` snippets, `repro` command, `quarantine` rule (BE-6). |
| 5.5 | Counts in `evidence` must come from the recorded per-run outcomes, never typed text. |
| 5.6 | Console: `Show faults only` is the default view when the tree has more than 200 tests. |

**Gate**
- On the demo repo, the Repo map shows the polluter, the victim and the shared state with `file:line` that match the source.
- Run the repro command on a clean checkout: it fails with the polluter first (AC-F2). Paste the output.
- Click each fault: Selected panel and Findings agree.
- `pytest -q tests/test_tree.py` passes with a fixture repo containing one shared-state polluter, one real failure, one unknown.

---

### M6. Fix PR, re-verify, quarantine, slash commands

| Step | Do |
|---|---|
| 6.1 | `POST /api/findings/{id}/fix`: generate the autouse teardown fixture (BE-7), validate under 20 shuffled runs, and only then open a PR **on the user's fork** (BOT-2). |
| 6.2 | `POST /api/findings/{id}/reverify`: re-run 5 shuffled runs, update counters, keep old evidence visible. |
| 6.3 | `POST /api/findings/{id}/quarantine`: return HTTP 409 with `detail` for real failures or missing write permission (CI-6). |
| 6.4 | `issue_comment` workflow for `/flakeguard fix | ask … | quarantine …` (CI-7). Check the requester's permission before acting. |
| 6.5 | Fix PR description uses the template in section 5.7. |

**Gate**
- Fix PR opened on a **fork**, with a validation log attached. Paste the PR URL.
- `quarantine` of the real failure returns 409 and the console shows `quarantine-refused`.
- A comment from an account without write access is declined.
- Merge the fix PR, and the post-merge note appears with the real run count.

---

### M7. No-tests flow (P2)

| Step | Do |
|---|---|
| 7.1 | Risky-spot scanner: `time.sleep`, `random`, `datetime.now`/`date.today`, module-level mutable state, network calls. Output rows for the table. |
| 7.2 | LLM writes one targeted test per spot. Prompt and model are recorded in `docs/PROMPTS.md`. |
| 7.3 | Validation (BE-8): runs, passes at HEAD, identical over k shuffled runs. Failing tests are listed as dropped with the reason (AC-N2). |
| 7.4 | Endpoint `GET /api/runs/{id}/no-tests` and the "Open PR on your fork" action. |

**Gate:** on a small repo with no tests, run the flow end to end. At least one test is kept, and one dropped test shows its reason on screen.

---

### M8. Results from real runs (P2)

| Step | Do |
|---|---|
| 8.1 | Build or reuse the labelled dataset. Keep **injected**, **natural** and **planted** flakes separate (section 4, rule 7). |
| 8.2 | `scripts/run_eval.py` runs perturbation, B1, B2, B3 under the same CI-minute budget and writes `results/<label>/*.json` including provenance (dataset, N, command, date, commit). |
| 8.3 | RQ4 ablation: same flaky tests, four context settings. Count diagnosis matches (against the known cause) and fixes that pass validation under shuffle. Record tokens/code sent. |
| 8.4 | RQ2: adaptive vs fixed runs-to-decision. RQ3: false-red PRs avoided and real failures wrongly quarantined. |
| 8.5 | Endpoint `GET /api/results?label=` serves these files. |

**Gate:** each table's `Command` re-run on a clean checkout regenerates the same numbers (state any tolerance). If a number cannot be produced yet, the cell stays a dash. Do not estimate.

---

### M9. Demo hardening, README, report

| Step | Do |
|---|---|
| 9.1 | Decide hosting (section 3.3) and write the exact start-up commands in `docs/DEMO.md`. |
| 9.2 | Record a **real** run as the `recorded` fallback (replay in the console with the banner). |
| 9.3 | Split-screen rehearsal: console left, GitHub right, three times with a timer. Fix anything that breaks. |
| 9.4 | Remove the old static frontend only after the new console is the one used in the rehearsal. |
| 9.5 | Write README sections and the report outline (section 12). |
| 9.6 | Final screenshots of all screens with real data. |

**Gate:** rehearsal log with three timed runs, one including a deliberate network failure that switches to the recorded fallback.

---

## 10. Demo script (about 10 minutes) and fallback

Layout: console on one half, the real GitHub PR on the other.

| Act | Time | What happens | What the audience sees |
|---|---|---|---|
| 1. Clean gate | 2 min | Open a PR with a deterministic new test. Run scan. | Pipeline advances, dot matrix all passes, PR comment: "No evidence of flakiness in N runs". |
| 2. Catch and diagnose | 5 min | Open the PR that adds the order-dependent test. | Matrix shows failures under shuffle, Bisection names the polluter, **Repo map** shows the tree with the writes/reads arrows, Findings explains why with file:line, Repro command copied and run live. PR comment appears on GitHub. Click **Propose fix PR**: fork PR opens. Real failure test shows "Quarantine refused". |
| 3. No tests | 2 min | Point at a repo with no tests. | Risky spots table, generated tests, three checks, honest "does not prove correct" notice. |
| Close | 1 min | Results tab. | Ablation and baselines with provenance footers, and RQ answers (dashes where a run is not done). |

**Fallback ladder:** (1) Actions slow → switch to `local` mode, banner explains. (2) Backend down → `recorded` run, banner says so. (3) Everything down → screenshots in `docs/ui-built/` with the recorded run clearly labelled. Never present a recording as live.

---

## 11. Risks and items to VERIFY

| # | Item | Status |
|---|---|---|
| V1 | `workflow_dispatch` / `issue_comment` need the workflow on the default branch | believed, VERIFY |
| V2 | `GITHUB_TOKEN` pushes do not trigger workflows | believed, VERIFY |
| V3 | Fork PRs get no secrets | believed, VERIFY |
| V4 | Artifacts readable only after job end | **Disproved 2026-11-21 (observed).** An artifact was listed and downloaded while its run was `in_progress`. Drove the choice in section 3.2 (matrix job per seed plus per-seed JUnit artifacts). See `docs/DECISIONS.md` M4-4. |
| V5 | Jobs/steps API gives live step status | believed, VERIFY (spike in M4) |
| V6 | GitHub API rate limits for the token type | unknown, VERIFY |
| V7 | LangChain genuinely used (only `langchain-core` known to be declared) | VERIFY in M0 |
| V8 | Docker mode has never been run end to end | VERIFY in M3 |
| V9 | Stale-file reads in progress parsing (`out/`, `scan_artifacts/`) | flagged, not confirmed fixed |
| V10 | Earlier test counts differed (221 vs 247; explained as ignored files) | re-check in M0 |
| V11 | D23 and D11 decision-log items unresolved | resolve in M0 |
| V12 | The course handout was never seen | re-check section 2 when available |
| V13 | Market overlap: tools such as Trunk, Mergify, BuildPulse and AI CI-failure analysers exist. Claims about them come from search snippets only | VERIFY before citing in the report |

Do not cite papers or tools in the report unless you have opened and read them.

---

## 12. Report and README outline

Team contribution and related work live here, not in the console.

1. Problem and motivation. 2. Research questions. 3. System design (use the section 3 diagram). 4. Tools used and why (table: tool, stage, purpose). 5. Prompt design (`docs/PROMPTS.md`). 6. Evaluation: datasets and label types, RQ1 to RQ4 tables with provenance. 7. Limitations (use the "Limits" wording in section 4). 8. Related work (only sources you have read). 9. **Team contribution table**: member, role, files/modules, evidence (commit ranges). Role A = data, CI, baselines. 10. How to run (commands from `docs/DEMO.md`).

---

## 13. Appendix

### 13.1 Frontend file map (already in `frontend/`)

```
src/
  main.tsx, App.tsx, RunContext.tsx
  types.ts                  API contract
  copy.ts                   exact wording for every state
  api/client.ts, api/mock.ts
  hooks/usePolling.ts
  styles/tokens.css, app.css
  components/
    Header, Banner, StatusChip, CodePane, Pipeline (PipelineList + DotMatrix),
    Icons, RepoTree, treeLayout.ts
  pages/
    Live, Findings, RepoMap, Results, NoTests, States, BotText
```

### 13.2 Definition of done

- [ ] `npm run build` passes; all 7 routes match `docs/ui/*.png`.
- [ ] No value on screen comes from outside a real run (or it carries "Demo data").
- [ ] One real Actions run, one real PR comment, one real fork fix PR (URLs recorded).
- [ ] Repo map is generated from the scanned repo and every link has a real file:line.
- [ ] Every Results number has a provenance footer and a regeneration command.
- [ ] Quarantine refuses a real failure.
- [ ] Recorded fallback works with the network off.
- [ ] `docs/DECISIONS.md` has dated entries for every VERIFY item.
- [ ] README and report outline complete; team contribution table filled.
