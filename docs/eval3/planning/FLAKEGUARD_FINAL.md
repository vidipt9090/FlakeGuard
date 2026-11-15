# FlakeGuard Final: connected, verified, demo-ready

One document. Give it to Claude Code and say: "Execute the gates in order. Do not start a gate until the previous one has evidence. After each gate, paste the evidence and ask me before moving on."
Eval 3 demo: 2026-11-20. Anything marked VERIFY is unconfirmed: check it by running it or reading current docs.

## 0. Rules (apply everywhere)
1. Verify, don't invent: no invented functions, flags, action versions, citations or statistics.
2. Ask when unclear. Flag uncertainty. Investigate surprising numbers before using them.
3. Log every decision, big or small, in `docs/eval3/decision-log.md` in the same commit.
4. Never push. Commit per gate on a branch; the human reviews and pushes. Use co-author trailers so the contribution matrix is accurate.
5. Every number shown anywhere has provenance (command, git sha, time, data label planted/injected/natural). No constants in the UI.
6. A gate passes only with captured evidence in `docs/eval3/evidence/<gate>.md` (command, output or screenshot, run link).
7. Wording: a clean scan is "no evidence in N runs", never "stable".

## 0b. Decisions locked (log each in the decision log)
| # | Decision | Notes |
|---|---|---|
| L1 | The team picks the demo repos; they are pre-vetted and described honestly as "selected", not random | Lowers demo risk |
| L2 | Python only (pytest). Other languages report "unsupported" clearly | |
| L3 | Test generation uses our own LLM generator as a substitute for Codium AI / Codeium. Request written approval from the professor before Eval 3; if an official tool is accessible, show one example from it too | Handout names Codium AI / Codeium. Product names may have changed (VERIFY) |
| L4 | RAG framework: LlamaIndex OR LangChain, whichever is already in the code. Check with `grep -rniE "llama_index|langchain" flakeguard/rag pyproject.toml`. If neither, add one over the existing Chroma store (VERIFY the installed version's API before coding) | Rubric requires one of them |
| L5 | A live scan must finish in 5 to 7 minutes max; replay of a stored event log is the fallback | |
| L6 | GitHub Actions is primary; laptop run is the fallback | |

## 0c. Rubric traceability (every graded item must have a visible demo moment)
| Rubric item | Weight | Where it is shown | Gate |
|---|---|---|---|
| Retrieval and automation integration | 15% | Retrieved code context feeds the verdict inside the Actions run; the Q&A answers from the same index | G6, G9 |
| Multiple tools, coordinated flow | 10% | Pipeline tab shows pytest, Docker, AST/Jedi, vector store, RAG framework, LLM, GitHub Actions/API in one run | G8 |
| Custom prompt design, code search, evaluation | 5% | Prompt v1 to v4 results; navigator vs plain-embedding retrieval (H3) with confidence intervals | G13 |
| Functional completeness and innovation | 5% | Causal evidence (polluter bisection, interventions), adaptive stopping, abstain, risk-directed test generation | G4, G5, G10 |
| Presentation, contribution, usability | 5% | Triage UI, rehearsed demo, honest contribution matrix | Section 8, 9 |
| RAG Q&A with LangChain or LlamaIndex | 10% | Ask-about-this-failure drawer with file:line citations | G9 |
| GitHub Actions CI/CD automation | 10% | PR-triggered run, sticky comment, label-driven quarantine | G6, G7 |
| Test generation (Codium AI / Codeium named) | 5% | No-test repo flow; substitute approval on file | G10 |
| Integration quality and documentation | 5% | README, decision log, evidence files, report | Section 10 |

## 1. What the teacher must see
1. **Static results:** an ablation of baselines B1, B2, B3 vs LLM variants, with confidence intervals, planted / injected / natural shown separately.
2. **Dynamic, repo with tests:** enter a repo, it scans, finds tests, runs the perturbation matrix, and reports flaky tests with evidence, live.
3. **Dynamic, repo without tests:** it generates targeted tests, validates them, then detects flakiness.
4. **PR-native workflow on GitHub:** a PR triggers Actions, the bot comments, a human label drives quarantine, real bugs are refused, the dashboard shows the same run.

## 2. The connection map
```
PR opened in flakeguard-demo  ->  caller workflow  ->  FlakeGuard reusable workflow (scan.yml)
   -> flakeguard scan (runner: baseline, shuffled, reversed, isolated, repeated, parallel)
   -> event log (JSONL, uploaded as artifact)  ->  evidence engine (bisect, interventions, read/write map)
   -> stats (Bayesian, adaptive stop)  ->  LLM stage (hosted provider, schema, votes, abstain)
   -> sticky PR comment  ->  maintainer adds label  ->  quarantine commit on PR branch
Dashboard (React + one FastAPI app): reads GitHub runs/jobs/artifacts + event log. Tabs: Triage, Pipeline, Results.
"Scan any repo": dashboard button -> workflow_dispatch(repo_url) -> same pipeline -> report in your own repo.
No-tests repo: static risk scan -> targeted test generation -> validation -> same pipeline.
```

## 3. Gate 0: protect the work (do first)
- Secrets check: `git grep -iE "(api_key|token|secret|ghp_|sk-|aiza)"` and `git status --ignored` for `.env`. Rotate any key that was ever committed.
- Snapshot: commit everything to a WIP branch and push as a backup (not a PR).
- Evidence: branch name, grep output (values masked).

## 4. Gate 1: one canonical codebase
- Delete the shim modules; keep one of each: evidence (`bisection`, `read_write_map`), stats (`bayesian`, `hypothesis`), llm (`providers`, `calibration`, `self_consistency`, prompt v4), baselines (`b3_feature_classifier`), no-test (`notest` or `gen`, pick one), injector (`injector`), app (one FastAPI app), frontend (React only; delete `app/static/`).
- Pick ONE live LLM provider for the demo; other providers only if tested and explainable. Log it.
- `make check` green locally and on Linux CI. List the skipped tests and the reason for each.
- Evidence: import graph shows no duplicate pairs; decision-log entries; CI run link.

## 5. Gate 2: numbers you can defend
- **D23 (`false_quarantine_rate`):** explain in the decision log how the metric was defined before and after, show the `git log -p` of `eval/metrics.py`, and confirm the fix did not just redefine it.
- **Provenance:** `tests/test_provenance.py` must fail on any displayed value without provenance, and must cover what the UI shows.
- **Ablation realism:** every ablation row is computed from per-test predictions you can open. If any row uses cached or replayed verdicts, label it "replayed" and do not present it as a live result.
- **D11:** choose `real` or `real_fail` and use it everywhere (labels, code, tests, UI).
- Evidence: a script that regenerates `results/eval3/` from scratch, and the diff against the committed copy.

## 6. Gate 3: GitHub setup (VERIFY each against current docs)
1. Repos: `FlakeGuard` (tool), `flakeguard-demo` (public; tests, 3 seeded flakes, a branch with a deterministic bug), forks of one repo with tests and one without.
2. Secrets: set the one provider key in the demo repo and the FlakeGuard hub repo (`gh secret set <NAME>` or repo Settings). Pass only that key to the step that needs it. Fork PRs get no secrets: demo from same-repo branches.
3. Workflow permissions: `pull-requests: write`, `contents: write` for the quarantine step. A push made with `GITHUB_TOKEN` does not trigger other workflows: decide and log how required checks behave.
4. Reusable workflow: `on: workflow_call` in FlakeGuard; caller in the demo repo with `uses: vidipt9090/FlakeGuard/.github/workflows/scan.yml@<ref>`. Pin a tag or sha for the demo.
5. Labels: create `approve-quarantine` in the demo repo. Approval mechanism is label OR comment command: pick one, log it, and make tests and docs match.
6. Dashboard token: a fine-grained token with only the scopes it needs (read runs/artifacts; Actions write only if the dashboard dispatches scans), stored server-side.
- Evidence: screenshot of the repo settings (values hidden) and the workflow file at the pinned ref.

## 6b. Gate 3b: vet the demo repos (do before the integration gates)
Pick 6 to 8 candidates, keep 3 to 4: two with tests, one with no tests, one backup.
For each candidate, record in `docs/eval3/evidence/repos.md`:
- URL, pinned commit, licence, and your fork under your account (never open PRs or issues on repos you do not own)
- Pure-Python dependencies; install time; suite runtime (target: scan under 5 to 7 minutes end to end, including all perturbations)
- A full dry-run scan: what it found, how long it took, the stored event log for replay
- Whether it shows any real order, timing or randomness sensitivity; if not, plan an injected-fault case on the fork and label it "injected"
- Pre-warmed dependency cache or a documented fast install
Reject any repo that cannot build within the time budget; show "could not build" honestly in the demo only as a planned example.
Describe the repos to the professor as "selected", not random.

## 7. Integration gates (each: command, expected result, evidence)
| Gate | Proof | Expected |
|---|---|---|
| G4 | `flakeguard scan synthetic` locally | Event log has every stage; flaky tests found; real bugs flagged |
| G5 | Scan `https://github.com/vidipt9090/flakeguard-demo` and `owner/repo` shorthand | Both accepted; 3 seeded flakes found with evidence tiers |
| G6 | Open a PR in the demo repo | Bot comment appears and is edited in place on re-run; time push-to-comment recorded |
| G7 | Quarantine with a writer, a non-writer, and a real-bug test | Writer: commit on the PR branch. Non-writer: refused. Real bug: refused. Re-approve: no duplicate entry |
| G8 | Dashboard "Run scan" on a URL | `workflow_dispatch` starts a run; Pipeline tab follows it; Triage shows findings as events arrive |
| G9 | Ask "why does this fail?" | Answer cites file:line that matches the polluter; empty retrieval is refused; RAG uses LlamaIndex or LangChain (rubric) |
| G10 | Scan a repo with no tests | Risk scan lists risky sites; generated tests kept only after validation; report says how many were kept and that they record current behaviour |
| G11 | Scan a vetted repo you did not tune on, end to end on GitHub Actions | Finishes within 5 to 7 minutes; report produced, or a clear "could not build" with the reason |
| G12 | Fix PR bot on the demo repo | Bot-authored PR you review; fix validated under shuffle before proposing |
| G14 | PR lifecycle: open a fix PR on your fork, merge it, close another unmerged | Events `pr_closed` (merged true/false) and `post_merge_check` appear; dashboard timeline shows detected, fix PR, merged or closed, "no evidence of flakiness in N runs after this change"; schema fields `repo`, `pr_number`, `sha` logged as a decision; `concurrency` per PR works (VERIFY) |
| G13 | Results tab | Planted / Injected / Natural tabs; each number opens its provenance; D23 resolved |
Run each gate twice. If a gate fails once in two tries, it is not demo-ready.

## 8. Demo-day runbook
**An hour before:** fresh clone of both repos, venv, `make check`, provider key works (one cheap call), Docker running, internet and GitHub reachable, dashboard started, a PR pre-opened as backup, recording of the full flow ready, one pre-scanned unknown repo stored for replay.
**Flow (adjust to your slot):**
1. 1 min: problem (red builds that are not real bugs) and the question.
2. 2 min: architecture slide: GitHub is the stage, the dashboard observes.
3. 4 min: live PR: push, Actions run on the Pipeline tab, bot comment, label, quarantine commit, real bug refused.
4. 5 to 7 min: paste a selected repo URL; watch the scan live on the Pipeline and Triage tabs; open one finding's proof drawer; ask the Q&A; show the fork PR the bot opens (fix or generated tests). Talk through the pipeline while it runs; if it passes 7 minutes, switch to the stored replay and say so.
5. 2 min: repo without tests: risk scan, generated tests, validated result.
6. 2 min: Results tab: baselines vs LLM, three data types, the failure case, what is under review.
7. 1 min: limits and future work. 1 min: team and contributions.
**Final demo story (PRs are opened, merged and closed on YOUR fork only):**
- Act 1 (5 to 7 min, live): paste a selected repo link, Run scan; Pipeline tab shows the Actions run; Triage fills with findings as events arrive. If the repo has no natural flake, use the injected-fault fork and label it "injected".
- Act 2 (about 3 min): open a finding's proof, ask the Q&A, click Propose fix PR (bot opens it on the fork; checks re-run under shuffle), YOU merge it, the post-merge job re-runs the flagged tests, timeline ends "no evidence of flakiness in N runs after this change".
- Act 3 (1 min): try to quarantine a real bug and show the refusal; optionally scan a repo with no tests.
- Pre-stage Act 2: open the fix PR before the demo so you only merge it live. Keep the post-merge check short. Past 7 minutes in Act 1, switch to the stored replay and say so.

**Fallbacks:** GitHub slow: switch to the recording and say so. LLM provider down: switch to Ollama or the replay and label it "replayed". Scan fails to build: show the "could not build" outcome and the pre-scanned repo.
**Questions to rehearse (every teammate):** why not just rerun tests; what the evidence tiers mean; how bisection finds a polluter; what the Bayesian stop rule does; why planted results are circular; what generated tests do and do not prove; what the maintainer gate protects against; what "false quarantine" means and how it is computed.

## 9. Report (1 to 2 pages)
Problem and research question; architecture (one diagram); what was built per rubric item (RAG Q&A, GitHub Actions automation, test generation, integration and documentation); results with labels and confidence intervals; honest limits; revised timeline; contribution matrix. Every claim cites a command and a data label. Include written approval for any substitute tool.

## 10. Definition of "nothing left"
All of: Gates 0 to 3 and G4 to G13 have evidence files; `make check` green on CI; decision log current; no duplicate modules; no hard-coded numbers; the demo rehearsed twice end to end by the person presenting; each teammate can answer the rehearsal questions; the report draft exists.

## 11. If a gate fails: cut order
Calibration plots, mutation-based validation of generated tests, leave-one-out ablation, fix-PR bot, no-test generation (keep the risk scan), JavaScript or other languages. Never cut: the live PR loop, the unknown-repo scan, honest results with provenance.

## 12. Evidence tracker
| Gate | Done | Evidence file | Run link / commit |
|---|---|---|---|
| G0 to G3 | | | |
| G4 to G13 | | | |
| Rehearsal 1, 2 | | | |
