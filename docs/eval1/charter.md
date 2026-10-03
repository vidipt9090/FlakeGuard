# flakeguard – Project Charter

## Problem

Test suites in large Python projects contain **flaky tests**: tests that pass and fail non-deterministically without any code change. Flaky tests erode CI reliability, waste developer time on spurious re-runs, and mask genuine regressions. No open-source tool currently combines execution-order analysis, LLM-assisted root-cause explanation, and automated quarantine in a single auditable pipeline.

## Worked Example

A test `tests/test_cache.py::test_lru_cache_hit` passes 9 out of 10 randomly-ordered runs. On the failing run, another test mutated a shared `_cache` global before `test_lru_cache_hit` executed. A human would call this a `shared_state` flake. **flakeguard** collects 10+ shuffled runs, detects the instability statistically, retrieves the relevant source code via semantic navigation, and asks an LLM to confirm the root cause with structured evidence — all without requiring the developer to reproduce it manually.

## Pipeline

```
collect (GitHub Actions) → parse (run_table.parquet) → navigate (code chunks) →
retrieve (Chroma/vector index) → LLM classify → label (labels.csv) → report
```

## Personas

| Persona | Pain point |
| --- | --- |
| Developer | Tired of re-running CI to silence a flaky test they don't own |
| Tech lead | Cannot trust the red/green signal; wants quarantine with audit trail |
| QA engineer | Needs to distinguish real failures from flakes in a release gate |

## Research Question

> Can an LLM, given shuffled-run evidence and retrieved source context, correctly identify the root cause of a flaky test at accuracy ≥ 0.70 across the `stable`, `flaky`, and `real_fail` labels on the cachetools and Emma test suites?

## Metrics

| Metric | Target |
| --- | --- |
| Label accuracy (F1 macro) | ≥ 0.70 on held-out test set |
| Root-cause match rate | ≥ 0.60 (exact match of root-cause string) |
| Quarantine false-positive rate | < 0.05 (human approves all quarantines) |
| Pipeline latency per test | < 30 s end-to-end on laptop hardware |

## Baselines

- **B1 (rerun-based):** Mark a test as flaky if it fails in any of N runs. Simple but noisy.
- **B2 (coverage-based, DeFlaker-style):** Flag tests whose coverage intersects with changed lines. Requires coverage data.
- **B3 (scikit-learn classifier):** Logistic regression on run-table features (pass rate, duration variance, order correlation).

## Target Substitutions and Why

| Original target | Substituted with | Reason |
| --- | --- | --- |
| Large internal repo | cachetools (MIT, pinned SHA) | Reproducible, fast (4.4 s/run), no IP issues |
| Internal CI | GitHub Actions matrix | Free for public repos; reproducible seeds |
| GPT-4 | Ollama local model (temp 0) | No cost, no data-privacy risk, reproducible |

---
*Last updated: 2026-10-03. B and C: please comment below or open a PR.*
