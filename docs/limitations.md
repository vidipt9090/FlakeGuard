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
