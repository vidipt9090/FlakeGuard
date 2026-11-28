# flakeguard-demo

A small Python "inventory" project with pytest tests. **It is deliberately seeded with test
faults for the FlakeGuard demo.** The faults are not bugs to fix by accident: they exist so
that FlakeGuard has something real to find.

```bash
pip install -e ".[test]"      # installs pytest and pytest-randomly
```

## The seeded faults

| Test | Fault | What FlakeGuard should say |
|---|---|---|
| `tests/test_warmup.py::test_cache_warm` | **Polluter.** Writes `CACHE["sku-1"] = 40` (module-level dict, `src/inventory/cache.py:3`) and never clears it. | Polluter |
| `tests/test_report.py::test_report_total` | **Order-dependent victim.** Reads `CACHE` through `Report.total` and fails if `test_cache_warm` ran first. | Flaky, order-dependent |
| `tests/test_stock.py::test_reserve_negative` | **Real bug.** `StockService.reserve` accepts a negative quantity, so this test fails in every run, in any order. | Real failure (cannot be quarantined) |
| `tests/test_sync.py::test_sync_timeout` | **Rare seeded failure.** The simulated remote end times out when a draw from Python's shared `random` generator is below 0.1. The draw is decided by the `pytest-randomly` seed, so a failure can be reproduced. About 9% of seeds fail. | Unknown (too few failures to call it flaky) |

The other tests (`test_report_title`, `test_reserve_ok`, `test_sync_clean`) are clean and pass in every run.

## Default order

Default order means `pytest -p no:randomly` (collection order, no shuffling):

**Every test passes in default order except `test_reserve_negative`, which fails by design
in every run.** The order-dependent test passes here because `test_warmup.py` sorts after
`test_report.py`, so the polluter runs last.

```bash
pytest -p no:randomly
# 1 failed, 6 passed. The one failure is test_reserve_negative.
```

Without `pytest-randomly` active, `tests/conftest.py` fixes the `random` seed at 0, so
`test_sync_timeout` passes in default order.

## Reproduce each fault

Order dependence (the polluter first, then the victim fails; the victim alone passes):

```bash
pytest -p no:randomly tests/test_warmup.py::test_cache_warm tests/test_report.py::test_report_total   # fails
pytest -p no:randomly tests/test_report.py::test_report_total                                          # passes
```

Real bug:

```bash
pytest tests/test_stock.py::test_reserve_negative       # fails every time
```

Rare seeded failure (seed 4 fails; the others in 1 to 10 pass):

```bash
pytest -p randomly --randomly-seed=4 tests/test_sync.py::test_sync_timeout   # fails
pytest -p randomly --randomly-seed=1 tests/test_sync.py::test_sync_timeout   # passes
```

## Use fixed seeds 1 to 10 for scans

Each shuffled run uses a seed. With random seeds, 10 shuffled runs hit a failing seed only
about 61% of the time (11 of 120 seeds fail), so about 4 scans in 10 would show no sync
failure at all. **For the demo, scan with the fixed seeds 1 to 10.** Seed 4 is the only
failing seed in that range, which gives a reproducible "1 failure in 10 runs".

`test_sync_timeout` by seed, measured with
`pytest -p randomly --randomly-seed=N tests/test_sync.py::test_sync_timeout`:

| Seed | 1 | 2 | 3 | **4** | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Result | pass | pass | pass | **fail** | pass | pass | pass | pass | pass | pass |

**Caveat (checked 2026-11-21):** the current FlakeGuard engine does not accept seeds. It
hard-codes seeds 1001 to 1010 for its shuffled runs, and `test_sync_timeout` passes for all
ten of them. Until the engine takes explicit seeds, a FlakeGuard scan of this repo will not
show the sync failure. Running the seeds above by hand with `pytest` does.
