# FlakeGuard handoff V5 (22 Nov 2026)

Read this file first in any new chat. It replaces the earlier handoff files (V4 is out of date).
The full requirements are in the repo: `docs/FLAKEGUARD_SRS_AND_BUILD_PLAN.md`.

## 1. Who and what

- Vidipt, 4th-year CS, BMU, team of three. He is role A (data, CI, baselines).
- Project: **FlakeGuard**, a PR reviewer that gates new tests for determinism and, when it finds flakiness, diagnoses it and opens a validated fix PR.
- Course: Intelligent Developer Tools and AI DevOps Workflows (Eval 3 live demo).
- Repos: `vidipt9090/FlakeGuard` (branch `c/eval3-console`) and `vidipt9090/flakeguard-demo` (public, clean `main`).
- Roles of the chats: the **build is done in Claude Code** (it keeps its own session). A chat like this one **reviews each milestone report** and writes the next message to paste into Claude Code.
- The evaluation date is unknown. The planned date of 20 Nov has passed. The decision is to keep building. The course handout has never been seen, so re-check the rubric table in the plan when it is available.

## 2. Rules that never change

1. Every value on screen comes from a real run. Anything else carries the "Demo data" badge. Missing data is `null`, shown as a dash.
2. Say "no evidence of flakiness in N runs". Never "fixed" or "stable".
3. One milestone at a time. Each ends with a gate. Real command output is pasted. Never claim a gate passed without running it.
4. Report format after every milestone: what changed (files), gate results (real output), what was not verified, decisions made.
5. Never invent function names, library methods, API fields or URLs. If unsure, read the installed package or the current docs.
6. No `|| true`, and no pipes that hide failures. Use `set -o pipefail` and check real exit codes.
7. Never force-push. Never merge into `main` of either repo without Vidipt's explicit go-ahead.
8. Stop only the process IDs you started. Never run `taskkill /IM node.exe`.
9. Do not rewrite the UI. Match `docs/ui/*.png`.

## 3. Credentials rule (current)

- Default: use only the `gh` login for `vidipt9090`.
- Exception for M6: the `priyalkhullar` credential may be used **only** to operate on her fork of `vidipt9090/flakeguard-demo` (push the fix branch and open the fix PR). Priyal must have agreed to that scope. Use it for nothing else. Record this in `docs/DECISIONS.md` with the date.
- Never print or commit a token.

## 4. State

| Milestone | Status | Evidence |
|---|---|---|
| M0 audit | accepted | `docs/AUDIT.md` (section 8 corrects an earlier mistake) |
| M1 console scaffold | accepted | `console/`, `docs/ui-built/` |
| M2 backend contract, recorded run | accepted | `flakeguard/console/`, `recorded/run-2026-11-18-001` |
| M3 live local scans, `seed_start` | accepted | `docs/ui-built/m3/`, 387 tests passing at M4 |
| M4 GitHub Actions mode | accepted | PR #3 (act 1) run 44877437008, PR #4 (act 2) run 44877769478, one comment edited in place, 76 to 77 s |
| M5 leftovers | **not started** | see section 6 |
| M6 fix PR, quarantine, slash commands, post-merge | **not started** | see section 6 |
| M8 results (ablation, baselines) | pending | Results screen currently shows dashes |
| M7 no-tests flow | pending | |
| M9 demo hardening, README, report | pending | |

Other facts:
- FlakeGuard's own `test` workflow is green on `c7a4fcb` (checked 22 Nov): ruff, pytest, baselines and navigator eval all succeeded.
- Keep demo PRs #3 and #4 **open and untouched**. They are the demo fixtures. Test the post-merge workflow on a throwaway PR instead.
- Demo seeds: scans use `FLAKEGUARD_SEED_START=1`. Seeds 1 to 10 give exactly 1 failure of `test_sync_timeout` (seed 4). The seeds are shown on the Live screen and stated in the demo README.
- Pinning: the demo's caller workflows name a FlakeGuard ref twice (`uses:` and `flakeguard_ref`). Before the demo, pin both to one commit SHA, after M6 and approval. A SHA ref was confirmed with a real run.
- Authorship: this session's M0 to M3 commits were re-authored to `vidipt9090` (diff against the backup branch was empty). Older commits by teammates are untouched. The team-contribution table in the report must say who did what, including that Claude Code did much of the implementation. Check the handout for any AI-use disclosure rule.
- Spike findings (docs/spikes/m4): artifacts are readable mid-run, job and step status is live within seconds, matrix job per seed gives one live result each, `workflow_dispatch` and `issue_comment` need the workflow on the default branch, `GITHUB_TOKEN` pushes do not trigger workflows, `job_workflow_sha` is empty across repos.

## 5. Not yet verified

- Post-merge workflow has never run.
- Fork PR behaviour (V3), Docker with a running daemon (V8), private repo reusable workflows.
- Browsers other than Chrome at 1440 px; keyboard and accessibility checks.
- Whether the 950 requests per hour budget holds over a real hour.
- CI minutes (76 s) versus the plan's 5 to 7 minute budget is fine, but the baseline runs once, not 3 times.

## 6. Next message to paste into Claude Code

After the usage limit resets (3:20 pm IST on 22 Nov), send:

```text
Limit reset. Continue where you stopped: M5 leftovers, then M6, as in my last message. Also, one update to the credential rule: you may use the priyalkhullar credential only to operate on her fork of vidipt9090/flakeguard-demo (push the fix branch and open the fix PR). She has agreed to that scope. Do not use it for anything else. Record this in DECISIONS.md.

Reminder of the work, in order, one gate at a time:

M5 leftovers:
- Fix the tall CACHE card on the Repo map: keep a fixed height next to the reader and draw the writer's arrow with an elbow line.
- Make file:line references in Findings links.
- Verify the repro command on a clean checkout of the demo repo (Act 2 branch) and paste the output.

M6:
- Fork decision (a): the fork owner is priyalkhullar. Record that in DECISIONS.md and test that fork PRs behave as expected (V3: secrets, workflow triggering).
- Fix PR with validation, re-verify, quarantine (409 for real failures and unknown, refused for no write access), and slash commands via issue_comment on the demo repo's main.
- Add the "Reply with /flakeguard ..." block back to the bot comment once the commands work, matching the wording in docs/ui/07-bot-text.png.
- Run the post-merge workflow once on a throwaway PR and paste the result. The comment must say "No evidence of flakiness in N runs after this change", or say the scan did not finish and show no verdict.

Then stop and report before M8. Same rules and report format as before.
```

## 7. What comes after M6 (for the reviewing chat)

1. **M8 Results.** Real ablation (four context settings) and baselines (B1 rerun, B2 coverage, B3 classifier) with provenance footers. Keep injected, natural and planted flakes separate. A number that cannot be reproduced stays a dash. This matters because the teacher wants static ablation results plus the dynamic demo.
2. **M7 No-tests flow** (test generation, Eval 2 rubric).
3. **M9 Demo hardening.** Hosting decision, recorded fallback run replayed with its banner, three timed rehearsals including a deliberate network failure, README, report, final screenshots, remove the old static frontend, pin the demo ref.

## 8. How to review a report (instructions for the reviewing chat)

- Check each claim against a real command output in the report. Flag anything stated without one.
- Check the report against the plan: gates met, honesty rules kept, deviations disclosed.
- Look for: values not from a real run, masked failures, wording like "fixed" or "stable", changes to the demo repo to make results fit, history rewrites, unrequested merges.
- Answer the questions Claude Code asks. Give Vidipt the exact message to paste next, in a code block.
- Be honest about uncertainty. Mark anything unverified. Do not invent sources or numbers.