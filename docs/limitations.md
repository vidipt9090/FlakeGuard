# FlakeGuard System Limitations & Threats to Validity

This document outlines known architectural limitations, methodological trade-offs, and threats to validity in FlakeGuard's current evaluation. Factual statements are strictly derived from empirical outputs in `results/`; items requiring further human confirmation or future expansion are explicitly marked with `TODO`.

---

## 1. Synthetic Data Optimism

- **Factual Results**:
  - The evaluation suite (`synthetic/`) contains 31 synthetic test cases across 3 files (`test_suite_01.py`, `test_suite_02.py`, `test_suite_03.py`) and a single module under test (`synthetic/src/shop.py`).
  - Code contexts presented in evidence bundles are small (~10 to 40 lines of code per test case), making AST navigation and function context extraction trivial.
- **Limitation**:
  - Production software repositories (e.g. `cachetools` or large enterprise monorepos) feature deep inheritance hierarchies, dynamic imports, complex fixture setup/teardown hooks, and background worker threads. Performance on small synthetic functions overestimates LLM reasoning accuracy.
- **Action Item / Verification**:
  - TODO: Validate triage precision and recall on full real-world repositories (`cachetools` SHA `3c082c6`).

---

## 2. Small Sample Size ($N=31$ Cases)

- **Factual Results**:
  - Total cases evaluated: 31 test cases (15 flaky, 6 real failures, 10 stable tests).
  - 20 shuffled execution runs were captured per test case, generating 620 total test outcome instances recorded in `results/runs.csv`.
- **Limitation**:
  - Small sample size $N=31$ results in wide 95% bootstrap confidence interval bounds for classification metrics. For example, LLM `v3` F1 score point estimate is `0.8333` with a 95% bootstrap CI spanning `[0.6857, 0.9474]`.
- **Action Item / Verification**:
  - TODO: Expand benchmark size to $N \ge 100$ cases in Eval 2 to narrow confidence interval ranges.

---

## 3. Small Local Model (`llama3.2:3b`)

- **Factual Results**:
  - Evaluated using Ollama's local 3.2 billion parameter model (`llama3.2:3b`).
  - On zero-shot prompt `v1`, the model misclassified real failure bugs as flaky (`false_quarantine_rate = 1.0`), yielding an F1 score of `0.6190` and root-cause accuracy of `0.3226`.
  - Adding structured JSON taxonomy and few-shot examples (`v3`) improved F1 score to `0.8333` and root-cause accuracy to `0.6129`, but false quarantine rate remained at `1.0` due to a bias toward predicting `flaky`.
- **Limitation**:
  - 3B parameter models struggle to distinguish subtle logic bugs (e.g. truncation vs rounding in `total_rounded`) from execution non-determinism without rich few-shot context or larger parameter models (e.g. 7B or 70B models).
- **Action Item / Verification**:
  - TODO: Benchmark larger local models (`codellama:latest` 7B and `llama3.3` 70B) to measure reduction in false quarantine rate.

---

## 4. Nondeterminism & Thread Scheduling Variance

- **Factual Results**:
  - In `results/runs.csv`, order-dependent tests (`test_case_02`, `test_case_04`, `test_case_06`) exhibit failure rates between `40.0%` and `60.0%` depending on shuffled seed order.
  - LLM self-consistency agreement rate across 3 identical calls at `temperature: 0.0` was `100.0%` (0 parse errors in `v2` and `v3`).
- **Limitation**:
  - While LLM generation at `temperature: 0.0` is deterministic, physical timing and thread schedule races (e.g. `test_case_13` to `test_case_15`) are inherently dependent on host machine CPU load, operating system scheduler, and Python GIL behavior.
- **Action Item / Verification**:
  - TODO: Measure thread-timing failure rate variance across different host hardware architectures (e.g. Laptop 1 AMD Ryzen vs Laptop 2 Intel Arc).

---

## 5. Label Construction & Taxonomy Boundaries

- **Factual Results**:
  - Ground truth labels in `labels/labels.json` classify cases into 3 labels (`flaky`, `real`, `stable`) and 6 root-cause categories (`order_dep`, `shared_state`, `timing`, `randomness`, `time_tz`, `none`).
  - Baseline rerun classifier labels tests with both `PASS` and `FAIL` outcomes as `flaky`.
- **Limitation**:
  - Tests that fail 100% of the time due to environmental misconfiguration or missing fixtures could be mislabeled as `real` bugs or `flaky` depending on collection execution conditions.
- **Action Item / Verification**:
  - TODO: Confirm whether human triage guidelines require adding an `uncertain` label category for ambiguous real-world test logs.

---

## 6. Forced-Clock Cases (`freezegun`)

- **Factual Results**:
  - Time/timezone test cases (`test_case_19`, `test_case_20`, `test_case_21`) use `freezegun` (`@freeze_time`) to set fixed mock times to off-hours/night time (`23:30:00`, `02:00:00`) forcing deterministic assertion failures (`greeting` returning `"Good night"` instead of `"Good day"`).
- **Limitation**:
  - Freezing the system clock forces failures during benchmark collection, but does not capture true real-time clock drift, leap years, or DST transitions occurring naturally during un-frozen CI execution.
- **Action Item / Verification**:
  - TODO: Verify time-dependent test behaviors under live system clock execution during off-hours CI runs.

---

## 7. RQ4 on the injected set: what the numbers can and cannot say

Every figure below is copied from `results/injected/rq4.json`, `rq4_integrity.json` and `rq4_leakage_split.json` (written by `scripts/run_rq4.py`, `scripts/rq4_integrity.py`, `scripts/rq4_leakage_split.py`). Nothing was rescored.

- **Injector-named identifiers are in the context.** Names that only the injector writes (`_FLAKEGUARD_ORDER_READY`, `_FLAKEGUARD_SHARED_CACHE`, `_bg_job`, `_fg_random`, `_hour`, `_race_flag`, `_th`) are present for 21 of 26 tests in the AST setting, 21 in AST + Jedi and 23 in the whole-file setting. Real code would not have them. Natural cues (sleep, random, datetime, now, Thread, threading, global) were added by the injection in 21 of 26 AST contexts; 6 AST contexts also hold such a cue from cachetools' own code. Per-test table: `results/injected/rq4_leakage_split.json`. A word in the context is not proof the model used it. A masked re-run has been planned and not run.
- **Exact match is strict.** The reply must be the listed word. `random` instead of `randomness` counts as a miss; AST tree only: 4 replies, 13 correct if accepted; AST + Jedi tree: 1 replies, 14 correct if accepted. That is a sensitivity, not the result.
- **Zero correct on shared_state and randomness.** shared_state: 6 tests, 0 correct across all four settings; randomness: 5 tests, 0 correct across all four settings. Part of this is the taxonomy: the injected shared-state fault is a global that an earlier test leaves changed, and an answer of `order_dependence` for it is a reasonable confusion (see the matrices). Part may be the model and the prompt.
- **One 3B model** (`llama3.2:3b`, 4-bit), one prompt, one decoding setting. A different model or prompt could move every number.
- **The fix column is not the product's fixer.** It measures a replacement test written by the model for the 5 order-dependent tests. The template fixer applies to 0 of them (DECISIONS M8-21).
- **Multiple comparisons.** 3 comparisons were planned; the Bonferroni threshold is 0.0167. Two more were looked at afterwards and are marked exploratory.

**Chance baseline.** The best constant guess is `shared_state`: 6 of 26. Class counts: order_dependence 5, randomness 5, time_or_timezone 5, timing 5, shared_state 6.

**Wilson 95% intervals and paired exact tests (same 26 tests).**

| Setting | Correct | 95% interval |
|---|---|---|
| No code | 5 of 26 | 0.085 to 0.379 |
| Whole file | 5 of 26 | 0.085 to 0.379 |
| AST tree only | 10 of 26 | 0.224 to 0.575 |
| AST + Jedi tree | 13 of 26 | 0.321 to 0.679 |

| Pair | Kind | Right only in first | Right only in second | p (two-sided) |
|---|---|---|---|---|
| No code vs AST tree only | planned | 0 | 5 | 0.0625 |
| No code vs AST + Jedi tree | planned | 0 | 8 | 0.0078 |
| AST tree only vs AST + Jedi tree | planned | 0 | 3 | 0.2500 |
| No code vs Whole file | exploratory | 0 | 0 | 1.0000 |
| Whole file vs AST + Jedi tree | exploratory | 0 | 8 | 0.0078 |

**Confusion matrices** (rows: true cause; columns: what the model answered; `random` is the reply that is not one of the six listed words).

*No code*

| True cause | timing |
|---|---|
| order_dependence | 5 |
| randomness | 5 |
| shared_state | 6 |
| time_or_timezone | 5 |
| timing | 5 |

*Whole file*

| True cause | order_dependence | timing |
|---|---|---|
| order_dependence | 0 | 5 |
| randomness | 0 | 5 |
| shared_state | 3 | 3 |
| time_or_timezone | 0 | 5 |
| timing | 0 | 5 |

*AST tree only*

| True cause | order_dependence | random | time_or_timezone | timing |
|---|---|---|---|---|
| order_dependence | 1 | 0 | 0 | 4 |
| randomness | 0 | 3 | 0 | 2 |
| shared_state | 2 | 1 | 0 | 3 |
| time_or_timezone | 0 | 0 | 4 | 1 |
| timing | 0 | 0 | 0 | 5 |

*AST + Jedi tree*

| True cause | order_dependence | random | time_or_timezone | timing |
|---|---|---|---|---|
| order_dependence | 4 | 0 | 0 | 1 |
| randomness | 2 | 1 | 0 | 2 |
| shared_state | 6 | 0 | 0 | 0 |
| time_or_timezone | 0 | 0 | 4 | 1 |
| timing | 0 | 0 | 0 | 5 |

