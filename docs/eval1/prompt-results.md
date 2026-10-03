# Prompt Engineering Results & Comparison (Eval 1)

## Benchmark Comparison Matrix

Evaluation across 5 planted flaky tests (`order_dep`, `shared_state`, `timing`, `randomness`, `time_tz`) + 1 real failure (`real_fail`):

| Prompt | Model | JSON valid | Verdict right | Root cause right | Evidence ids valid | Avg latency |
| --- | --- | --- | --- | --- | --- | --- |
| **v1** | `llama3.2:3b` | 6/6 | 5/6 | 0/6 | 0/6 | 4.39s |
| **v1** | `codellama:latest` | 6/6 | 5/6 | 1/6 | 0/6 | 10.59s |
| **v2** | `llama3.2:3b` | 6/6 | 5/6 | 4/6 | 6/6 | 4.62s |
| **v2** | `codellama:latest` | 6/6 | 6/6 | 5/6 | 6/6 | 10.85s |
| **v3** | `llama3.2:3b` | 6/6 | 6/6 | 5/6 | 6/6 | 4.75s |
| **v3** | `codellama:latest` | 6/6 | 6/6 | 6/6 | 6/6 | 11.20s |

---

## Detailed Failure Analysis & Explanations

### Example 1: `v1` on `llama3.2:3b` (Order Dependence - `test_b_needs_registered`)
- **LLM Output (v1)**: 
  ```json
  {
    "verdict": "flaky",
    "root_cause": "order_dependency",
    "explanation": "The test fails because apple is not in registry when run alone."
  }
  ```
- **Why it failed taxonomy/citation**: Prompt `v1` lacked taxonomy restrictions and snippet ID rules. The model output `"order_dependency"` instead of `"order_dep"` and did not cite snippet IDs (`[E1, E2, E3]`), resulting in 0/6 for `rc_right` and `evidence_ids_valid`.

### Example 2: `v2` on `codellama:latest` (Shared State - `test_expects_cache`)
- **LLM Output (v2)**:
  ```json
  {
    "verdict": "flaky",
    "root_cause": "shared_state",
    "confidence": 0.85,
    "evidence": [{"id": "E1", "type": "static", "strength": "strong"}, {"id": "E3", "type": "static", "strength": "strong"}],
    "explanation": "KeyError 'rate' occurs because test_pollutes_cache (E3) cleared _cache (E2) used by apply_rate (E1).",
    "fix_hint": "Reset _cache in an autouse fixture or mock."
  }
  ```
- **Improvement**: Schema enforcement and taxonomy constraints in `v2` resulted in perfect JSON structure, exact enum matching (`"shared_state"`), and valid evidence ID citations.

### Example 3: `v3` on `llama3.2:3b` (Real Failure - `test_rounding`)
- **LLM Output (v3)**:
  ```json
  {
    "verdict": "real",
    "root_cause": "none",
    "confidence": 0.95,
    "evidence": [{"id": "E1", "type": "static", "strength": "strong"}],
    "explanation": "The function total_rounded uses int() which truncates 10.6 to 10 instead of rounding to 11. This is a deterministic code bug.",
    "fix_hint": "Use round() in shop.total_rounded."
  }
  ```
- **Improvement**: Few-shot examples in `v3` prevented false positive flakiness classifications. The real failure was correctly identified as `verdict: "real"`.

---

## Verified Refactoring

The refactored test suite in `synthetic/tests/test_refactored.py` was evaluated using:
```bash
pytest synthetic/tests/test_refactored.py --count=20 -p randomly
```
- **Result**: **100/100 passed** (100% pass rate across 20 repetitions and random shuffling).
- **Summary**: All 5 planted flaky tests were refactored into isolated, deterministic tests (using explicit state initialization, clock freezing via `freezegun`, thread joining, and parameter mocking).
