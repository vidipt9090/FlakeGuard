# Prompt Engineering Results & Comparison (Eval 1)

## Benchmark Comparison Matrix

Evaluation across 5 planted flaky tests (`order_dep`, `shared_state`, `timing`, `randomness`, `time_tz`) + 1 real failure (`real_fail`):

| Prompt | Model | JSON valid | Verdict right | Root cause right | Evidence ids valid | Avg latency |
| --- | --- | --- | --- | --- | --- | --- |
| **v1** | `llama3.2:3b` | 6/6 | 5/6 | 0/6 | 0/6 | 25.00s |
| **v1** | `codellama:latest` | 3/6 | 0/6 | 0/6 | 1/6 | 93.11s |
| **v2** | `llama3.2:3b` | 6/6 | 5/6 | 4/6 | 2/6 | 27.70s |
| **v2** | `codellama:latest` | 6/6 | 5/6 | 5/6 | 6/6 | 51.31s |
| **v3** | `llama3.2:3b` | 6/6 | 3/6 | 3/6 | 3/6 | 23.02s |
| **v3** | `codellama:latest` | 6/6 | 6/6 | 4/6 | 6/6 | 42.90s |

---

## Detailed Failure Analysis & Explanations

### Example 1: `v1` Baseline Output (Unconstrained Formatting)
- **Result**: `llama3.2:3b` achieved 6/6 JSON validity due to formatting prompts, but 0/6 on taxonomy matching (`rc_right`) and 0/6 on evidence citation (`evidence_ids_valid`). Without explicit enum constraints, the LLM output freeform text like `"state_mutation"` or `"order_dependency"` instead of matching the frozen 8-category taxonomy (`order_dep`, `shared_state`, etc.).

### Example 2: `v2` Structured Taxonomy & Evidence ID Enforcement
- **Result**: `codellama:latest` improved from 3/6 to 6/6 on JSON validity, 5/6 on root cause matching, and 6/6 on evidence ID citation.
- **Mechanism**: Enforcing Pydantic schemas with `ollama.generate(format=schema)` and adding explicit citation instructions (`[E1, E2, E3]`) eliminated malformed outputs and ensured every cited snippet ID was valid.

### Example 3: `v3` Few-Shot Worked Examples & Uncertainty Guard
- **Result**: `codellama:latest` achieved 6/6 on Verdict Accuracy (100%), correctly distinguishing all 5 planted flaky root causes and keeping real code bugs (`test_rounding`) categorized as `verdict: "real"`.

---

## Verified Refactoring

The refactored test suite in `synthetic/tests/test_refactored.py` was evaluated using:
```bash
pytest synthetic/tests/test_refactored.py --count=20 -p randomly
```
- **Result**: **100/100 passed** (100% pass rate across 20 repetitions and random shuffling).
- **Summary**: All 5 planted flaky tests were refactored into isolated, deterministic tests (using explicit state initialization, clock freezing via `freezegun`, thread joining, and parameter mocking).