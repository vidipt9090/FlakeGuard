# FlakeGuard Eval 3: Official Live Demo Script (2026-11-20)

This numbered, step-by-step script guides the live evaluation presentation for **FlakeGuard Eval 3**.

---

## 0. Demo Environment Setup & Verification

Before presenting, ensure the local environment is verified and operational:

```powershell
# Navigate to repository root
cd "C:\Users\khull\Desktop\4th Year\IDT Final\FlakeGuard"

# Activate Python 3.12 virtual environment
.\.venv\Scripts\Activate.ps1

# Run fast sanity check (ruff + pytest smoke)
ruff check .
pytest -q tests/test_server.py tests/test_quarantine_approve.py
```
*Expected: `All checks passed!` and `13 passed in < 2s`.*

---

## 1. Demo Flow Overview

| Step | Action | Feature Highlighted | Duration |
| :---: | :--- | :--- | :---: |
| **1** | Inspect incoming Pull Request | PR-native developer workflow | 1 min |
| **2** | GitHub Actions CI Triage Comment | Structured triage table & evidence tiers | 2 min |
| **3** | Human Maintainer Quarantine Approval | Zero auto-quarantine without review policy | 1.5 min |
| **4** | Quarantine Commit & CI Pass | Isolation via `quarantine.json` | 1 min |
| **5** | Deterministic Bug Refusal | Real code regression safety gate | 2 min |
| **6** | Live Perturbation Matrix Scan | CLI runner, dual sandbox, JSONL event log | 2 min |
| **7** | No-Test Repo Latent Flake Discovery | Static AST scan + test synthesis at HEAD | 2 min |
| **8** | Interactive Web Dashboard Walkthrough | 6-view responsive UI & event replay | 3.5 min |

---

## Step 1: Incoming Pull Request & Failure Symptoms

1. **Speaker narrative:**
   > *"When a developer opens a pull request, random test failures waste hours of investigation. Here we inspect PR #42 where `test_case_02` failed unexpectedly during CI."*
2. **Action:**
   Show the test source in `synthetic/tests/test_suite_01.py::test_case_02`.
   Explain that the failure only occurs when `test_case_01` runs earlier in the same test runner process because it leaves dirty global state.

---

## Step 2: Live CI Triage Comment Generation

1. **Speaker narrative:**
   > *"Instead of forcing developers to rerun CI repeatedly, FlakeGuard triggers an automated triage workflow. Let's run the exact triage script invoked by GitHub Actions."*
2. **Command:**
   ```powershell
   python scripts/post_triage_comment.py
   ```
3. **Observation:**
   The output generates a GitHub-flavored Markdown comment containing:
   - Test ID: `synthetic/tests/test_suite_01.py::test_case_02`
   - Verdict: `flaky` (Root cause: `order_dep`)
   - Evidence Tier: `Tier 2: Reproduced` (Setter/polluter: `test_case_01`)
   - Bayesian Credible Interval: `0.40 [0.22, 0.61]` (Fail rate bounded away from 1.0)
   - Call to Action: `quarantine:approve <test_id>`

---

## Step 3: Human Maintainer Quarantine Approval Gate

1. **Speaker narrative:**
   > *"A core architectural principle of FlakeGuard (frozen in our charter) is that FlakeGuard NEVER auto-quarantines tests on its own. A human maintainer must review the root cause and authorize quarantine."*
2. **Action:**
   Maintainer reviews the causal evidence and replies with:
   ```text
   quarantine:approve synthetic/tests/test_suite_01.py::test_case_02
   ```
   Or applies the GitHub label `quarantine:approve`.

---

## Step 4: Quarantine Commit & CI Pass

1. **Speaker narrative:**
   > *"Upon approval, FlakeGuard automatically commits `quarantine.json` to the branch. In subsequent runs, pytest ignores quarantined tests, turning CI green without blocking the PR."*
2. **Inspect quarantine state:**
   ```powershell
   cat data/quarantine.json
   ```
3. **Verify:**
   Show that the entry contains `test_id`, `reason`, `approved_by: "@maintainer"`, and commit SHA.

---

## Step 5: Refusal on Real Code Bugs (Critical Safety Gate)

1. **Speaker narrative:**
   > *"What happens if a real code regression breaks a test? Historical LLM prompts (v1–v3) suffered from a severe 1.0 false quarantine rate because they guessed 'flaky' on any failure. FlakeGuard Eval 3 resolves this completely."*
2. **Action:**
   Trigger triage on `synthetic/tests/test_suite_03.py::test_case_22` (a genuine bug in `synthetic/src/shop.py`):
   ```powershell
   python -c "
   from flakeguard.llm.schema import VerdictOutput
   from flakeguard.stats.bayesian import BayesianFailureRate
   stats = BayesianFailureRate.from_counts(runs=10, failures=10)
   print('Bayesian Fail Rate:', stats.mean, stats.credible_interval_95)
   "
   ```
3. **Observation:**
   - 10 failures out of 10 runs yields `[0.72, 0.99]`, triggering the `deterministic_failure` rule.
   - LLM predicts `real_fail` with root cause `none`.
   - FlakeGuard displays: **"⛔ QUARANTINE REFUSED: Deterministic code regression detected. Maintainer cannot bypass CI."**

---

## Step 6: Live Perturbation Matrix Scan (CLI)

1. **Speaker narrative:**
   > *"Let's run the full CLI scanner on our synthetic suite across the perturbation matrix (baseline, shuffled N, reversed, isolated, repeated, parallel)."*
2. **Command:**
   ```powershell
   flakeguard scan synthetic --shuffled-n 2 --timeout 30
   ```
3. **Observation:**
   - Terminal displays run ID, pinned commit SHA, total slices (11), total unique tests (31).
   - Detected flaky tests are listed with failure rates.
   - Single-source-of-truth event log written to `data/events/<run_id>.jsonl`.

---

## Step 7: Latent Flakiness Discovery in No-Test Repos

1. **Speaker narrative:**
   > *"FlakeGuard can also audit repositories that have NO test suites. Our static AST scanner detects risky sites (time, sleep, random, shared state, network), generates targeted characterization tests recording current behaviour at HEAD, passes them through a 3-stage quality gate, and detects latent flakiness."*
2. **Command:**
   ```powershell
   python -c "
   from flakeguard.notest.orchestrator import run_notest_pipeline
   from pathlib import Path
   summary = run_notest_pipeline(Path('synthetic/src'))
   print('Scanned files:', summary.scanned_files)
   print('Risky sites detected:', len(summary.risky_sites))
   print('Synthesized tests generated:', len(summary.generated_tests))
   print('Validated tests passing gates:', len(summary.validated_tests))
   "
   ```
3. **Observation:**
   - 6+ risky sites detected across `sleep`, `random`, and `datetime.now()`.
   - Generated tests explicitly comment: `# Generated test by FlakeGuard: records current behaviour at HEAD`.
   - Tests pass HEAD validation, determinism validation, and kill mutation operators.

---

## Step 8: Web Dashboard & Replay Walkthrough

1. **Launch Dashboard Server:**
   ```powershell
   flakeguard serve --port 8000
   ```
2. **Open Browser:** `http://127.0.0.1:8000`
3. **Walk through the 6 views:**
   - **Tab 1: 🚀 Live Scan:** Highlight live stage timeline and streaming SSE logs.
   - **Tab 2: 🔍 Test Explorer:** Select `test_case_02`, show polluter bisection (`test_case_01`), select `test_case_19`, show clock freezing intervention flipping the failure.
   - **Tab 3: 🌳 Knowledge Tree:** Inspect AST call graph with failing nodes and tainted global accesses highlighted.
   - **Tab 4: 🛡️ PR & Quarantine:** Demonstrate the GitHub bot comment preview, test the maintainer approval button, and show refusal alert for `test_case_22`.
   - **Tab 5: 📊 Results & Ablations:** Review the leave-one-out evidence ablation table (Full v4 F1=1.00 vs Minimal Stats F1=0.83), calibration ECE diagram (0.042), and baseline comparisons.
   - **Tab 6: ⏪ Event Replay:** Pick a historical run from the dropdown, hit Play, adjust speed to 5x, and watch the timeline and test matrix replay deterministically.

---

## 2. Backup & Contingency Quick-Reference

If live network or external LLM APIs are unavailable:
- FlakeGuard's `CachedReplayProvider` automatically replays pre-recorded verdicts from `results/llm_raw/` with zero network calls.
- Pre-scanned event logs in `data/events/*.jsonl` allow 100% offline demonstration via the Replay tab.

