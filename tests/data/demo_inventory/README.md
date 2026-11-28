# demo_inventory (local fixture)

A small project used to record the first FlakeGuard console run. It is a local
fixture, not a GitHub pull request. Its faults are deliberate:

| Test | Fault |
|---|---|
| `tests/test_warmup.py::test_cache_warm` and `tests/test_report.py::test_report_total` | Order dependence: the first writes the module-level dict `CACHE` (`src/inventory/cache.py:3`), the second reads it and expects it to be empty |
| `tests/test_stock.py::test_reserve_negative` | Real failure: `reserve` accepts a negative quantity, so the test fails every run |
| `tests/test_sync.py::test_sync_timeout` | About 1 in 10 runs fail, from an unseeded random draw (`os.urandom`) |

Everything else is meant to pass in every run.
