<!-- flakeguard-post-merge -->
## FlakeGuard post-merge check

The scan after this change found 3 tests that failed.

| Test | Verdict | Evidence |
|---|---|---|
| `test_report_total` | Flaky, order-dependent | Failed 5 of 10 shuffled runs |
| `test_reserve_negative` | Real failure | Failed 17 of 17 runs |
| `test_sync_timeout` | Unknown, too few failures | 1 failure in 17 runs. Too few to call it flaky. |

Scanned commit cfd9e36 · shuffled seeds 1 to 10 · [Actions run](https://github.com/vidipt9090/flakeguard-demo/actions/runs/1)
