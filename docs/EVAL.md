# How the results are produced (M8)

Every table on the Results screen comes from `python scripts/run_eval.py <label>` and is written to `results/<label>/`.
Each file records the dataset, label type, N, the exact command, the date and the commit. Label types are never mixed.

## Label types

| Label | What it is | Status |
|---|---|---|
| planted | `synthetic/`: 31 hand-written tests, faults written in by hand. Labels by construction. | Run |
| injected | cachetools 8.0.2 (source archive pinned by sha256) with faults inserted by `flakeguard/injector` operators. Labels by construction. | Run |
| natural | Flakes found in real projects. None were available. | **Not run. Shown as dashes.** |

Planted results are partly circular: the faults were written to be the kinds the methods are built to find. Injected results
are only partly independent: the operators produce the same fault classes the detector looks for.

## Methods

* **B1, fixed-order rerun.** N whole-suite runs in the suite's own order (`-p no:randomly`). A test is *flaky* if it both passed and failed, *real* if it failed every time, *none seen* if it never failed. Never "stable".
* **Perturbation (shuffled runs).** N whole-suite runs in shuffled orders (pytest-randomly, seeds 1 to N), same rule. This is what the old "rerun" baseline in `results/baseline_metrics.csv` really was.
* **B2, coverage diff.** Defined below.
* **B3, classifier.** `B3FeatureClassifier` (random forest, 50 trees, `random_state=42`) on run features from the N fixed-order runs (failure rate, pass rate, flips, flip rate, entropy, duration mean and standard deviation) and, in the main variant, three code features (the words sleep, random, datetime in the test source). **Trained on the planted set, scored on the injected set**, so it is never scored on a test it was trained on. A secondary check trains on the other injected tests and scores each held-out one (**leave-one-out**, labelled as such in every row). A variant without the code features is reported next to each, because the code features read text the operators insert.

N = 5, 10 and 20 whole-suite runs are the primary comparison. Minutes are wall-clock on this laptop, compared with a 6-minute budget.

## B2 definition (registered before B2 was run)

We have not read the DeFlaker paper. B2 is the heuristic that `flakeguard/baselines/b2_coverage.py` implements and describes, and we make no claim that it reproduces the published tool.

* **Input 1, the change.** The set of changed source lines of one hypothetical commit. There is no real commit in a synthetic dataset, so the change is a single source line sampled at random (`random.Random(20261122)`) from the lines of `src/cachetools` that at least one test executes. Ten such one-line changes are sampled; no code is edited, only the line set is used.
* **Input 2, coverage.** One fixed-order run of the suite under coverage.py 7.17.4 with `dynamic_context = test_function`, so every executed library line is attributed to the test that executed it. Only library source is measured, not the test files.
* **Rule.** A test that failed in at least one of the N fixed-order runs and executed none of the changed lines is **flaky** (the failure cannot come from the change). A failing test that executed a changed line is **real**. A test that never failed is **none seen**.
* **Reporting.** Each row is scored on the sampled change with the median recall; the minimum and maximum over the ten changes are stored next to it. Minutes are N fixed-order runs plus the coverage run.
* **Known weakness it will show.** A test that fails every time but does not touch the change is called flaky, so real failures can be called flaky.
* **Not applicable to planted.** The planted suite has no coverage run or change, so B2 is a dash there.

## Injection operators (flakeguard/injector/operators.py)

| Operator | Fault, by construction | Checked by running it |
|---|---|---|
| timing | A worker sleeps a random 0.01 to 0.04 s; the test waits 0.02 s and asserts it finished | `tests/test_injector_behaviour.py`: fails and passes within 60 calls |
| shared_state | All mutated tests of one module share a counter; only the first to run passes | first passes, every later one fails |
| randomness | `assert random.random() < 0.85` | about 15% of 2000 calls fail |
| time_tz | Asserts the local hour is 8 to 17 | passes at 12:00, fails at 23:00 and 03:00 (frozen clock) |
| order_dep | The victim passes only if its setup test ran earlier in the process | fails alone, passes after setup |
| real_fail | A check that never passes | fails every time |

The first timing operator slept a fixed 0.04 s against a 0.02 s wait and failed every time, which contradicted its label. It was
changed before any method was scored (the old behaviour: 50 failures in 50 calls on this machine).

Untouched tests are labelled stable because the untouched suite passed in all 6 pristine runs (3 fixed order, 3 shuffled). That is evidence, not proof.

## Sensitivity tables

A second scope next to the primary one, never replacing it. Planted: five tests whose code cannot pass on this machine are relabelled real, with the reason read from the code. Injected: the time_tz faults are set aside because they cannot fail when the local hour is 8 to 17 and every run started in that window.
