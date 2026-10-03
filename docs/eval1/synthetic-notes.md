# Synthetic Project Analysis & Failure Rates

## Overview

The `synthetic/` project contains a tiny e-commerce shop module (`shop.py`) along with 10 test cases:
- 5 planted flaky tests (covering 5 root causes)
- 2 real failures (always fail)
- 3 stable tests

## 20 Shuffled Runs Benchmark (`pytest -p randomly`)

Results across 20 shuffled runs with different random seeds:

| Test ID | Root Cause / Label | Failure Frequency | Pass Rate | Failure Mechanism |
| --- | --- | --- | --- | --- |
| `test_order_dep.py::test_b_needs_registered` | `order_dep` (flaky) | **10 / 20 (50%)** | 50% | Fails if executed before `test_a_register` initializes state. |
| `test_shared_state.py::test_expects_cache` | `shared_state` (flaky) | **10 / 20 (50%)** | 50% | Fails with `KeyError` if `test_pollutes_cache` runs first and clears `_cache`. |
| `test_timing.py::test_job_finishes` | `timing` (flaky) | **7 / 20 (35%)** | 65% | Fails when `slow_job` takes longer than the `time.sleep(0.05)` threshold. |
| `test_randomness.py::test_discount_is_small` | `randomness` (flaky) | **1 / 20 (5%)** | 95% | Fails when `random.random() >= 0.9` (~10% probability). |
| `test_time_tz.py::test_greeting_is_day` | `time_tz` (flaky) | **0 / 20 (0% daytime)** | 100% | Fails only between 22:00 and 05:00 local time. Captured via `freezegun` at 23:00. |
| `test_real_failures.py::test_rounding` | `real_fail` (bug) | **20 / 20 (100%)** | 0% | Real bug: `total_rounded` truncates instead of rounding. |
| `test_real_failures.py::test_negative_qty_rejected` | `real_fail` (bug) | **20 / 20 (100%)** | 0% | Real bug: `check_qty` does not raise `ValueError` on negative inputs. |
| `test_stable.py::test_sum` | `stable` | **0 / 20 (0%)** | 100% | Deterministic and isolated test. |
| `test_order_dep.py::test_a_register` | `stable` | **0 / 20 (0%)** | 100% | Helper registration test. |
| `test_shared_state.py::test_pollutes_cache` | `stable` | **0 / 20 (0%)** | 100% | Cache mutation test. |

## Notes on Root Cause Mechanisms

1. **`order_dep` vs `shared_state`**:
   - `order_dep`: Test *needs* an earlier test to run first to set up state.
   - `shared_state`: Test *pollutes* shared state, breaking subsequent tests.
2. **`time_tz` Handling**:
   - During daytime execution, `test_greeting_is_day` natural failure rate is 0%.
   - A single night-time failure log was captured using `freezegun` (`@freeze_time("2026-10-03 23:00")`) and stored in `synthetic/time_tz_failure.log`.
