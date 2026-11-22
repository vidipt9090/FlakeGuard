<!-- flakeguard-pr-comment -->
## FlakeGuard · 1 flaky test, 1 real failure, 1 test that needs more evidence

| Test | Verdict | Evidence |
|---|---|---|
| `test_report_total` | Flaky, order-dependent | Failed 5 of 10 shuffled runs |
| `test_reserve_negative` | Real failure | Failed 17 of 17 runs |
| `test_sync_timeout` | Unknown, too few failures | 1 failure in 17 runs. Too few to call it flaky. |

**test_report_total**

- **Why:** This test reads the shared CACHE (src/inventory/cache.py:3) through total at src/inventory/report.py:11. Another test, test_cache_warm, writes it through warm at src/inventory/cache.py:7. If test_cache_warm runs first, this test fails.
- **Where:** tests/ › test_report.py › test_report_total › reads CACHE ← test_cache_warm
- **Limits:** The order dependence is shown for these two tests. Other causes of flakiness in this test are not ruled out.

**test_reserve_negative**

- **Why:** This test failed in all 17 runs it was in, including when run on its own, so test order does not explain it. The failure message is: Failed: DID NOT RAISE ValueError
- **Quarantine:** Fails in every run. A real failure cannot be quarantined.

**test_sync_timeout**

- **Why:** This test failed in 1 of 17 runs and passed in the other 16. No polluter test was found, and no targeted run reproduced the failure.
- **Limits:** 1 failure in 17 runs is not enough to tell a flaky test from a one-off. Run more shuffled runs to decide.

**Reply to this comment with**

```
/flakeguard ask why is this order-dependent?
/flakeguard quarantine test_report_total
```

This comment is updated in place on every push.

Scanned commit cfd9e36 · shuffled seeds 1 to 10 · [Actions run](https://github.com/vidipt9090/flakeguard-demo/actions/runs/1)
