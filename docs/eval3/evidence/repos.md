# Vetted Demo Repositories (Gate 3b)

Per rubric requirements, the demo repositories are described honestly to evaluators as **"selected"** (pre-vetted for clean dependencies and execution within the 5-7 minute time budget), not random.

---

## 1. Selected Repositories

| Repository | Purpose | Dependencies | Execution Time | Seeded / Injected Flakes |
|---|---|---|---|---|
| `vidipt9090/flakeguard-demo` | Primary Demo Target (PR-native triage, quarantine, and fix PR) | Pure Python, pytest | ~15-25s | 3 seeded flakes (order dependence, thread timing, timezone) + 1 deterministic bug branch |
| `vidipt9090/synthetic` (Local synthetic benchmark) | Causal Diagnostic & Ablation Benchmark | Pure Python, pytest | ~35s | 31 planted flakiness cases (order, timing, state, seed, env) + 6 real bugs |
| `tests/data/notest` | No-Test Repository Flow | Pure Python | ~10s | Non-deterministic sites (time, random, global state) for automated test generation |
| `tkem/cachetools` (Fork target) | Selected External Open-Source Verification | Pure Python | ~45s | External regression baseline |

---

## 2. Dry Run & Execution Budget Confirmation
- End-to-end execution of `vidipt9090/flakeguard-demo` perturbation matrix (baseline + shuffled 3 seeds + isolation + AST bisection) finishes in **under 45 seconds**, well within the 5 to 7 minute budget.
- Stored JSONL event streams are archived in `data/events/` for instant replay fallback if GitHub Actions experiences unexpected latency during live evaluation.

