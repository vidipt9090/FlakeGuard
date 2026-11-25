# Demo guide

Local demo on one machine, with live GitHub Actions. Every command and number below was run or measured on 2026-11-25 (rehearsals 1 and 2, `docs/DECISIONS.md` M9-1). Anything not rehearsed says so.

## 1. Start (two terminals, then Chrome)

From the repository root, `C:\Users\khull\Desktop\4th Year\IDT Final\FlakeGuard`.

Terminal 1, the API (port 8000):

```powershell
.venv\Scripts\python -m flakeguard.app.api
```

It prints `FlakeGuard API + UI running on http://127.0.0.1:8000`. **Do not open port 8000 in the browser.** It serves the older dashboard (`frontend/dist`); the console is on 5173.

Terminal 2, the console (Vite dev server, port 5173; run `npm ci` once first):

```powershell
cd console
npm ci
npm run dev -- --host 127.0.0.1
```

Open **http://127.0.0.1:5173** in Chrome only.

Pre-flight (all three verified):

```powershell
gh auth status                              # the active account must be vidipt9090
curl http://127.0.0.1:8000/api/health       # {"ok":true,"mode":"actions","docker":false,"recorded":"run-2026-11-25-001"}
ollama ps                                   # empty is fine: the console makes no model call
```

* `mode: actions` means the API found a GitHub token (the `gh` login). `docker: false` is expected; leave **Isolate in Docker** unticked for local scans. Ticking it shows the "Docker is not running" notice by design.
* The console never calls Ollama (Ask is code search, the verdict is rules). Ollama is used only by `scripts/run_no_tests.py` and the RQ4 scripts, offline.
* **Fork PR (Propose fix PR):** set `$env:FLAKEGUARD_FORK_OWNER = "priyalkhullar"` before starting the API. The credential for her fork is read with `gh auth token --user priyalkhullar` and is used only on `priyalkhullar/flakeguard-demo`. **Not rehearsed** (it is a GitHub write that needed separate approval). A fix PR from an earlier run already exists, `priyalkhullar/flakeguard-demo#1`; show that instead of opening another.

## 2. Script (about 10 minutes)

Layout: console on one half of the screen, the GitHub page on the other.

| Act | Do | Say | Expect | Needs network |
|---|---|---|---|---|
| **1. Clean gate** (2 min) | Live tab. Type `vidipt9090/flakeguard-demo#3`, Source **Pull request**, **Run scan**. Open the PR on GitHub from the link. | "A new test goes in. FlakeGuard shuffles the suite and finds nothing." | Attaches in about 11 s (read-only API calls). Pipeline all done, **Failures 0, Tests flagged 0**, all dots filled. PR comment: "FlakeGuard · No evidence of flakiness in 10 shuffled runs", with the rule-of-three line. | Yes |
| **2. Catch and diagnose** (5 min) | Type `vidipt9090/flakeguard-demo#4`, Run scan. Then **Findings** → `test_report_total`, **Repo map**, **Copy command** and run it in a terminal. | "Same suite, a test that depends on order. Bisection names the polluter, the tree shows who writes and who reads CACHE." | Failures **5**, flagged **3** (one flaky, one real, one unknown). Findings: the evidence lines, the polluter `test_cache_warm`, the reproduce command, the **Fix preview** with "failed in 0 of 20". The PR comment is on GitHub. | Yes |
| 2b. Slash commands | In the PR's comment box on GitHub post, one at a time: `/flakeguard ask why does test_report_total fail?`, `/flakeguard fix`, `/flakeguard quarantine test_reserve_negative`. | "Ask is code search with file and line. Fix is validated before it is shown. A real failure cannot be quarantined." | Replies in **36 s**, **59 s** and **36 s** (rehearsal 1). Ask: code locations plus the finding text. Fix: "A fix for test_report_total passed validation", 0 failures in 20 runs, the diff. Quarantine: "Not quarantined: test_reserve_negative. Fails in every run." No issue is opened. | Yes |
| 2c. Fix PR (optional) | Findings → **Propose fix PR**. | "The fix goes to a fork, and a person merges it." | **Not rehearsed.** Needs `FLAKEGUARD_FORK_OWNER` (section 1). Fallback: open `priyalkhullar/flakeguard-demo#1`. | Yes |
| **3. No tests** (2 min) | Live tab → **See how FlakeGuard handles it**. | "No tests, so it finds risky spots, asks the model for one test each, and keeps only tests that pass validation." | `/no-tests?plan=latest`: scan `notests-2026-11-25-002`, 5 spots, **3 kept, 2 dropped with reasons**, the notice "Kept means the test passed validation, not that it is a strong test", **Open PR on your fork** disabled "not enabled in this build". | No |
| **Close** (1 min) | **Results** tab. | "Every figure has its sample size, interval and provenance. Read the notes first." | RQ4 table with the masked rows and the limitation notes at the bottom. | No |

Do not click **Drop this test** during the demo: it rewrites `recorded_no_tests/notests-2026-11-25-002/` (a tracked file). If you did, run `git checkout -- recorded_no_tests` afterwards.

## 3. What works with no network

Verified with the network cut for the API and Chrome (a dead proxy, localhost exempt; see M9-1 for why this is not literally Wi-Fi off). Endpoint times: run, findings, tree 6 to 8 ms; results 17 ms; no-tests 23 ms; Ask 17 ms.

| Works offline | How |
|---|---|
| Recorded replay | Live tab → **Replay the recorded run** (run `run-2026-11-25-001`: 5 of 10 shuffled runs fail, 1 flaky, 1 real, 1 unknown, with the **fix preview**). The blue banner reads "This is a recorded run, not live". |
| Findings, Repo map, Ask | On the recorded run. |
| Local scan | Source **Sample repo**, Isolate in Docker unticked, **Run scan**: 10 shuffled runs done after about 50 s, complete after **148 s**. No model call. |
| No-tests plan | `/no-tests?plan=latest`. |
| Results | The Results tab. |

| Needs network | Why |
|---|---|
| Attaching to a pull request (Acts 1 and 2) | Reads the GitHub API. With the network down the console shows "GitHub did not answer as expected" (HTTP 502 after about 2 s) and nothing else breaks. |
| Slash commands, fork PR | They run on GitHub. |

## 4. Fallback per act

Say it out loud when you switch: never present a recording as live.

| Act | If the network or Actions fails | If the console or API fails |
|---|---|---|
| 1 | Replay the recorded run (its dots differ: it is the order-dependence run). Or show the PR #3 comment page from the browser cache. | Screenshots in `docs/ui-built/`. |
| 2 | **Replay the recorded run**: same screens (Findings, Repo map, Fix preview, Reproduce). Slash commands: show the replies on PR #4, or the screenshots `docs/ui-built/m9/rehearsal1-*.png`. | Screenshots: `docs/ui-built/m9/replay-fix-preview.png`, `rehearsal1-findings.png`. |
| 3 | Nothing needed, it is offline. | `docs/ui-built/m7/no-tests-clean-scan.png`. |
| Close | Nothing needed. | `docs/ui-built/m8/results-Injected-rq4.png`. |

Local mode as a middle step when Actions is slow: Source **Sample repo** (148 s, shows the pipeline filling live, banner says it is a local scan, not a pull request).

## 5. Known limits found in the rehearsal

* **Act 2 run link.** Attaching to a PR picks the newest run at the PR's head commit. PR #4 and the throwaway PR #13 shared that commit, so attaching to #4 now selects the run that belongs to #13 (`actions-45665294747`). The numbers are identical (same commit); the **Open Actions run** link goes to the #13 run. The older run for #4 is `44877934601`. Removing the #13 run needs a GitHub write that was not approved.
* **A fresh PR, not an old commit.** A new commit has no earlier run, so attach waits correctly ("starts when the pull request is opened or updated"). The first Actions run takes about 100 s (rehearsal 1: 17:29:28 to 17:31:10).
* **Generated tests vary.** The no-tests scan is a recording; running `scripts/run_no_tests.py` again can keep or drop different tests at the same settings (M7-7).
* **Do not push to `c/eval3-console` before the demo.** The demo repository's workflows call FlakeGuard at that branch (`@c/eval3-console`), so any new push changes what Actions runs.
