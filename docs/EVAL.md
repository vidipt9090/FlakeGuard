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

## RQ4: does more code context help a small model name the cause? (registered before RQ4 was run)

**Question.** Given a test that was flagged flaky, does the cause the model names match the known cause, and does it change with how
much code the model is shown? Model: `llama3.2:3b` through Ollama on this laptop (CPU). No hosted model.

**Sets.** The prompt text was tuned on the planted flaky tests (15) and then frozen (its sha256 is stored in the results). The result is
measured on the injected flaky tests (26). Tuning results are stored apart and are not a result.

**The four settings.** Everything except the code is identical across settings: the test id, the sentence "this test was flagged flaky",
the run summary ("failed in X of 20 shuffled-order runs and Y of 20 fixed-order runs", from the recorded runs) and the instructions.

| Setting | Code the model is given |
|---|---|
| `none` | no code at all |
| `file` | the whole text of the file that holds the test |
| `ast` | the test's own source, plus the nodes of the knowledge tree (`flakeguard/navigator/knowledge_tree.py`) whose resolver is `ast` (fixtures, module-level shared state, smells), each with its source text |
| `ast_jedi` | the test's own source plus every node of the tree: the `ast` ones and the ones `jedi.goto`/`jedi.infer` resolved (the code the test calls) |

The knowledge tree is built by `AstNavigator.explain` on the injected suite. `ast` is a filter on the tree's `via` field, not a separate
analyser, so the `ast` and `ast_jedi` settings differ only by the Jedi-resolved nodes.

**Not shown in any setting.** Failure messages and tracebacks (the operators write the cause into their assertion messages). In what the model sees,
the comment lines the operators insert ("# Injected ... by FlakeGuard") are deleted and the message part of an injected `assert` is removed.
Identifiers the operators choose (for example `_FLAKEGUARD_ORDER_READY`, `_race_flag`) stay in the code, so the file, ast and ast_jedi settings are easier than real code would be. This is a stated limitation.

**Decoding.** Temperature 0, `seed` 42, `num_ctx` 16384, JSON output requested (`format: json`), one call per test per setting, no retry, no self-consistency.
Ollama's reported prompt tokens and generated tokens are stored per call. A prompt that fills `num_ctx` is flagged `truncated`.

**Answer format.** A JSON object with `cause` (one word from: `order_dependence`, `shared_state`, `timing`, `randomness`, `time_or_timezone`, `other`) and `reason` (one sentence).

**"Diagnosis matches the known cause", exactly.** The model's `cause`, lower-cased and stripped of surrounding whitespace, is character-for-character equal
to the word mapped from the test's `root_cause` label: `order_dep` to `order_dependence`, `shared_state` to `shared_state`, `timing` to `timing`,
`randomness` to `randomness`, `time_tz` to `time_or_timezone`. Nothing else counts: no synonym, no partial credit, no accepting
`shared_state` where the label is `order_dep` (the confusion is reported separately). A reply that is not valid JSON, has no `cause` field, has
a `cause` outside the six words, is empty, or times out is **a failure and stays in the denominator**; it is also counted separately as a parse failure.
Figure: k of 26 with a Wilson 95% interval. Guessing one of five causes at random gives 0.20; always answering the most common cause (`shared_state`, 6 tests) gives 6 of 26.

**Fix metric (order-dependent tests only, N=5).** Only the 5 injected order-dependent tests are asked for a fix (the fix proposer in
`flakeguard/console/fixer.py` writes a fixture for module-level dict, list or set state; `fix_proposer_applies` is recorded per test and for these
mutants it is expected to be 0 of 5, because their shared state is a flag set through `global`, not a container). A second call, in the same setting, asks for
`fixed_test`: the complete replacement source of the test function. The fix is **validated** when all of these hold on a copy of the injected suite:
(1) the file still parses and the function is in the same place with the same name; (2) every non-blank line of the original (pre-injection) test body is still in it;
(3) the file collects the same tests as before; (4) the test passes when run alone (without its setup test it fails before the fix); (5) the test does not fail in any of 10 whole-suite
runs in shuffled order (seeds 1 to 10; without the fix it failed in the seeds recorded in `perturbation.json`). A fix that is not valid code, is missing, or does not keep the test is **not** validated and stays in the denominator.
What validation cannot tell: a fix that removes the injected dependence by deleting the check passes, and that is the correct change for this dependence. N=5, so no figure here is a rate.

**Recorded per call.** The code sent (characters), prompt tokens, generated tokens, seconds, the raw reply, the parsed cause, match, parse failure, truncated.
The repeat check re-runs the `none` setting for all 26 tests and reports how many replies differ.

## RQ3: false-red PRs and false quarantine (a simulation; registered before RQ3 was run)

**This is a simulation over labelled tests. No pull request was opened and FlakeGuard's PR flow was not run.** Each labelled test is treated as if it were the one
new test in a PR whose other changes are fine, and the pipelines are applied to the runs already recorded in `results/<label>/`.

**Pipelines compared.**
* *Naive CI*: one run in the suite's fixed order (run 1 of `b1_fixed_order.json`). Any failure turns the PR red. A second row uses all 20 recorded fixed-order runs as 20 separate hypothetical CI runs (pairs of test and run).
* *Fixed-order rerun (B1) at N=20*: the same 20 fixed-order runs; a test that failed every time is called real, one that both passed and failed is called flaky.
* *FlakeGuard triage*: the shuffled runs at N=5, 10, 20 (same rule: both outcomes seen means flaky, only failures means real, only passes means no evidence of flakiness), and the adaptive stopping policy of `flakeguard/stats/adaptive.py` on the same runs.

**What is counted** (every count with its N and a Wilson 95% interval):
* *False-red PR*: a PR whose test is labelled flaky and failed in the naive CI run (so it went red for a flake). *Cleared*: triage calls it flaky, so it is quarantined or flagged instead of blocking. *Wrongly blocked*: triage calls it real, so the PR stays blocked as a real bug. The B1 row shows the tests it calls real although they are labelled flaky; on the planted set that is 8 of 15 (±1) because a fixed order makes an order-dependent test fail every time.
* *Real failure wrongly quarantined*: a test labelled real that triage calls flaky (it would be quarantined and the bug hidden). Also shown: real failures called real.
* *Stable test wrongly flagged*: a test labelled stable that triage calls flaky.
Labelled `flaky` tests that never fail in any run (the injected `time_tz` ones) cannot be red and are listed apart.
Planted and injected are separate tables. Natural: not run, dashes. The two real pull requests of the demo repo (#3, a clean change; #4, a revert that brings four faulty tests back)
are mentioned as anecdotes about what the bot did; they are not data for any figure here.

### RQ4 prompt tuning (planted set only; frozen before any injected call)

Two prompt versions were tried, both scored on the 15 planted flaky tests in all four settings, with the same decoding. Nothing was tuned on injected tests, and no third version was tried.

| Prompt | none | file | ast | ast_jedi | What changed |
|---|---|---|---|---|---|
| v1 | 5/15 | 6/15 | 7/15 | 7/15 | one-line description of each cause |
| v2 | 3/15 | 4/15 | 9/15 | 10/15 | a clue for each cause (words and patterns to look for) and a warning not to answer `shared_state` just because a global name appears |

v2 is the frozen prompt. The v1 and v2 logs are `results/planted/rq4_tuning_v1.json` and `rq4_tuning_v2.json`. These are tuning scores on the set the prompt was tuned on; they are not a result.

### RQ4 masked rerun `rq4_masked` (registered before it was run)

**Why.** The text sent to the model in the `ast`, `ast_jedi` and `file` settings holds names that only the fault injector writes (`results/injected/rq4_leakage_split.json`: 21 of 26 tests in `ast` and `ast_jedi`). Real code would not have them. This run asks whether the `ast` and `ast_jedi` gains survive without them. It is a new run; `results/injected/rq4.json` is never replaced or edited.

**What is masked.** Only the seven identifiers that appear in the blocks of `flakeguard/injector/operators.py` and start with an underscore, in the code part of the prompt, with one fixed neutral name each (whole-word match):

| Injector name | Replaced by |
|---|---|
| `_FLAKEGUARD_ORDER_READY` | `_x1` |
| `_FLAKEGUARD_SHARED_CACHE` | `_x2` |
| `_bg_job` | `_x3` |
| `_fg_random` | `_x4` |
| `_hour` | `_x5` |
| `_race_flag` | `_x6` |
| `_th` | `_x7` |

The run stops if a prompt still holds one of the seven names. **Not masked:** natural cues (`sleep`, `random`, `datetime`, `now`, `Thread`, `threading`, `global`), the structure around the names (for example `globals().get(...)`), test names, and the run summary line. So the masked contexts are still easier than real code.

**Before and after, two tests (the `ast` context, lines that hold a masked name).**

`tests/test_cached.py::CacheWrapperTest::test_decorator_lock_cond_info` (order dependence)

    before:  assert globals().get('_FLAKEGUARD_ORDER_READY') is True
    after:   assert globals().get('_x1') is True

`tests/test_cachedmethod.py::UnboundMethodTest::test_class_access_copy` (timing)

    before:  import random as _fg_random, threading, time        after:  import random as _x4, threading, time
    before:  _race_flag = [False]                                after:  _x6 = [False]
    before:  def _bg_job():                                      after:  def _x3():
    before:  time.sleep(_fg_random.uniform(0.01, 0.04))          after:  time.sleep(_x4.uniform(0.01, 0.04))
    before:  _race_flag[0] = True                                after:  _x6[0] = True
    before:  _th = threading.Thread(target=_bg_job)              after:  _x7 = threading.Thread(target=_x3)
    before:  _th.start()                                         after:  _x7.start()
    before:  assert _race_flag[0] is True                        after:  assert _x6[0] is True

**Run.** Settings `ast` and `ast_jedi` only; 26 flaky tests each, so 52 diagnosis prompts; no fix calls (`--no-fix`); prompt v2 as frozen; `llama3.2:3b`, temperature 0, seed 42, `num_ctx` 16384, same order (setting by setting, dataset order). Command: `python scripts/run_rq4.py injected --settings ast,ast_jedi --no-fix --mask --out rq4_masked.json`. A dry run before this entry showed masking changes the prompt of 21 of 26 tests in each setting; the other 5 (the randomness tests, which hold no injector name) are the same request as in `rq4`, so their replies come from the existing call cache and are not asked again. The cache is keyed by the full request, so masked prompts never hit an unmasked reply.

**What will be reported, whatever the outcome.** Per setting: correct of 26 with a Wilson 95% interval; per fault class counts; the answers given. Paired exact McNemar tests on the same 26 tests, two-sided: masked `ast` vs `none`, masked `ast_jedi` vs `none` (reusing the recorded `none` results), masked vs unmasked `ast`, masked vs unmasked `ast_jedi`. These four are planned; Bonferroni threshold 0.05 / 4 = 0.0125. Discordant counts are shown with each p. The exact-match rule and the definitions above are unchanged, nothing is rescored, and if the gain shrinks or vanishes it is reported as it is.
