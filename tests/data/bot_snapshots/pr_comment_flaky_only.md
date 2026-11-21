<!-- flakeguard-pr-comment -->
## FlakeGuard · 1 flaky test found

| Test | Verdict | Evidence |
|---|---|---|
| `test_report_total` | Flaky, order-dependent | Failed 5 of 10 shuffled runs |

**test_report_total**

- **Why:** This test reads the shared CACHE (src/inventory/cache.py:3) through total at src/inventory/report.py:11. Another test, test_cache_warm, writes it through warm at src/inventory/cache.py:7. If test_cache_warm runs first, this test fails.
- **Where:** tests/ › test_report.py › test_report_total › reads CACHE ← test_cache_warm
- **Limits:** The order dependence is shown for these two tests. Other causes of flakiness in this test are not ruled out.

This comment is updated in place on every push.

Scanned commit cfd9e36 · shuffled seeds 1 to 10 · [Actions run](https://github.com/vidipt9090/flakeguard-demo/actions/runs/1)
