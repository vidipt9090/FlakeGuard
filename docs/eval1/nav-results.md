# Navigation results (work package B3)

Author: B. Date: 2026-10-03. Navigator version: v0.5 (`flakeguard/navigator/ast_nav.py`).

## Headline

Four gold sets across three repositories, each built because the one before it
had stopped being able to answer the question.

| gold set | target | precision | recall | F1 | top-3 | **p@5** |
| --- | --- | --- | --- | --- | --- | --- |
| 1, tuned (`nav-gold.json`) | cachetools, 10 | 0.96 | 0.93 | 0.95 | 100% | 0.96 |
| 2, spent (`nav-gold-heldout.json`) | cachetools, 8 | 0.60 | 0.52 | 0.56 | 100% | 0.67 |
| 3, second repo (`nav-gold-itsdangerous.json`) | itsdangerous, 10 | 0.52 | 0.91 | 0.66 | 100% | 0.75 |
| **4, third repo** (`nav-gold-tenacity.json`) | **tenacity, 8** | 0.43 | **0.89** | 0.58 | **100%** | **0.68** |

Sub-scores:

| | fixtures | smells |
| --- | --- | --- |
| set 3, itsdangerous | **P 0.90 / R 1.00** | P 1.00 / R 1.00 |
| set 4, tenacity | no fixtures used | P 0.38 / R 1.00 |
| all four sets, smells combined | — | **P 0.75 / R 0.94** |

Latency: median 0.18-0.28 s per test, max 0.91 s, across three repositories.

**The number to quote: recall 0.89, precision@5 0.68, correct answer in the
top 3 for 8 of 8, on a third repository the navigator had never seen.** Sets 3
and 4 agree closely (recall 0.91 / 0.89, p@5 0.75 / 0.68), which is the first
real evidence that any of this generalises rather than fitting one library.

## Why four sets

Each is biased, and usefully in different directions.

**Set 1 is biased up and unfixable.** Labels revised after seeing output *and*
filters tuned on the same 10 tests. 0.96 measures fit, not skill.

**Set 2 was blind for one run, then spent** paying for the mixin bug it found.

**Set 3 is blind but biased down.** Its labels list only directly asserted
code, while most flagged false positives genuinely execute —
`Serializer.dumps` really does call `want_bytes` and `make_signer`.

**Set 4 is the cleanest.** Third repository, and unlike set 3 no part of the
implementation was written while reading it. Its labels are conservative in
the same way, so its 0.43 precision understates in the same direction.

**No label in sets 3 or 4 has been revised after scoring, and none will be.**
Revising upward after seeing output is what made set 1 useless. True precision
is somewhere between 0.43 and 0.96; `precision@5` is least exposed to either
bias, and recall and top-3 are barely exposed at all.

Residual bias no set removes: the same person wrote the navigator and every
label. **An independent re-label by A or C is the one control still missing**,
and it is cheap.

## Three things the held-out sets caught that the tuned set could not

**Set 2: inherited tests resolved to nothing.** Three of eight scored zero on
everything. pytest reports an inherited test under the concrete class, but the
body lives in the mixin. `CacheTestMixin` supplies 23 of cachetools' tests;
all 10 tests in set 1 happen to be defined directly in their own class, so set
1 was structurally incapable of noticing.

**Set 3: the gold set itself was broken.** Fixtures scored 0.25 / 0.28 and the
navigator was right — the labels were wrong, their line numbers read from
`main` before the repo was pinned to 2.2.0, so every fixture was off by one.
Fixed by `tools/relocate_gold.py`, which recomputes line numbers mechanically
from the pinned checkout by symbol name, rewrites only `start_line`, and
refuses any name matching several definitions (`cache_info` appears four times
in `_cached.py`, once per wrapper builder, and only one of them runs). Applied
to every set: set 1 needed 0 corrections, set 2 one, set 3 seventeen, set 4
zero. Fixtures then scored 0.90 / 1.00. **Re-run that tool whenever a target
repo is re-pinned**; a gold set keyed by line number can break silently.

**Set 4: the smell detector was close to useless.** First run: precision
**0.06**, 15 false positives against 3 real ones. Two distinct causes, both
now fixed:

- *Scanning everything reachable.* tenacity is a retry library, so
  `BaseRetrying` uses `time.monotonic` and `threading`. Walking up to it from
  any test meant **every tenacity test came back as a timing flake**, which
  carries no information at all. The scan now covers only code the test
  reaches directly; inheritance hops score below `DIRECT_SCORE` and are
  excluded. Setting that threshold too high broke set 3, whose code is reached
  *through fixtures* — fixtures are direct, inheritance is not.
- *Ignoring `setUp`.* tenacity's after-log tests pick a log level with
  `random.choice` in `setUp`, so the body looks deterministic. `setUp`,
  `tearDown`, `setup_method` and `teardown_method` are now scanned; smell
  recall went to 1.00.

Smells also now carry **where they were found**, which matters more than the
precision number:

```
Flakiness smells (2)
  - time.time (tests/test_tenacity.py:240)
  - random. (tenacity/wait.py:66)
```

`random.` alone is not something an LLM can cite. `random. (tenacity/wait.py:66)`
is evidence with an address, which is what C's bundle needs. The contract keeps
`smells: list[str]`, so this is formatting, not a contract change.

Set 4's smell precision is 0.38 and remains the weakest number here. Its code
metrics are still blind — only the smell path was changed — but its *smell*
metric is now spent, and Eval 2 needs a fresh target to re-measure it.

## Two improvements that were tried and reverted

Worth recording, because both look obviously right on paper.

**Return-type inference.** jedi can execute a function and report what it
hands back, which should have found `_HashedTuple` — a class that exists only
as a return value and that two tests assert on. Measured on all three sets
available at the time it added **no recall whatsoever** and only false
positives. Removed.

**Multi-hop expansion.** Walking the class hierarchy to the top instead of one
level does raise recall (set 1 to 1.00). It also buries the direct answer: F1
fell about 12 points on the held-out sets and correct-in-top-3 dropped from
100% to 75%. Recall is worth little if the right chunk no longer fits in the
bundle. Held at one hop.

What was kept from that round: **distance weighting**. Evidence the test names
itself outranks evidence reached by following links, which lifted precision@5
(set 3 0.72 to 0.75, set 2 0.64 to 0.67) at no cost to anything else.

## What still misses

**Runtime dispatch.** `cached()` picks one of eight wrapper builders from the
*values* of `lock`, `condition` and `info` at decoration time. Static
resolution reaches `cached` and stops, so the navigator often returns the
wrong variant's `cache_info`. The strongest argument for pairing static
navigation with the runtime data A's collector produces.

**Return types.** `hashkey()` returns a `_HashedTuple` whose `__hash__` the
test asserts on. Nothing names it in the source, and jedi's `execute()` did
not recover it.

**Template-method dispatch.** A mixin calls `self.cache(2)` and the real
implementation is in whichever subclass is running. Resolving `self.x` against
the concrete class from the test id handles the common case; a base calling
into an unknown subclass does not.

**Deep inheritance**, deliberately: `TTLCache -> _TimedCache` is found,
`_TimedCache -> Cache` is not. See the reverted experiment above.

## Reproduce

```bash
git clone https://github.com/tkem/cachetools.git ../cachetools
cd ../cachetools && git checkout 3c082c654c2804b9354e4b62dbd2994f1aac464d && cd -
git clone https://github.com/pallets/itsdangerous.git ../itsdangerous
cd ../itsdangerous && git checkout 2.2.0 && cd -
git clone https://github.com/jd/tenacity.git ../tenacity
cd ../tenacity && git checkout 9.1.2 && cd -

# the number to quote
python -m flakeguard.navigator.evaluate --repo ../tenacity \
    --gold docs/eval1/nav-gold-tenacity.json --markdown
python -m flakeguard.navigator.evaluate --repo ../itsdangerous \
    --gold docs/eval1/nav-gold-itsdangerous.json
python -m flakeguard.navigator.evaluate --repo ../cachetools --gold docs/eval1/nav-gold.json
python -m flakeguard.navigator.evaluate --repo ../cachetools --gold docs/eval1/nav-gold-heldout.json

# after re-pinning any target repo
python tools/relocate_gold.py docs/eval1/<gold>.json --repo ../<checkout>
```

The navigator is purely static: it parses a target but never imports it, so
the target's own dependencies need not be installed. tenacity's tests need
`tornado` and itsdangerous' need `freezegun`; neither is in our venv and
navigation works on both.

## Things these measurements still do not tell you

- **36 tests across three libraries is a small sample.** No confidence
  intervals, they would be meaningless at this size.
- **All three targets are clean, well-typed libraries.** Nothing here predicts
  behaviour on a messy codebase, which is what Emma is.
- **Shared state is barely represented.** Two module-level globals across
  three suites. Worse, `test_classmethod.py` keeps its mutable state in
  **class** attributes (`Cached.cache`, `Cached.count`) — the same flakiness
  mechanism, but outside the `NavResult` contract's wording of "module-level
  mutable globals". **Worth raising with A and C: the contract may need
  widening**, and that needs a `contract-change` PR with two approvals.
- **No measurement on planted flakes.** `synthetic/` is C's work package and
  is where order-dependence navigation gets tested for real.

---

## Addendum, 2026-10-10: the knowledge tree and the navigation trace

The numbers above score the navigator's *answer*. They say nothing about how
it got there, which is the part a reviewer has to trust. Two additions, both in
`flakeguard/navigator/`:

- **`trace.py`** records every step — each name the AST walk collected, each
  `jedi.goto` / `jedi.infer` call with what it returned and what survived
  filtering, each expansion hop, with the depth it happened at.
- **`knowledge_tree.py`** rearranges a `NavResult` by distance from the test,
  with the edge that reached each node named rather than implied.

`NavResult` is unchanged and `related()` is unaffected; `explain()` opts in.
`tests/test_knowledge_tree.py` asserts the two paths agree chunk for chunk.

Full write-up and the edge/phase tables: **`docs/knowledge-tree.md`**.

### What the tree shape adds to the story above

| | synthetic, 31 cases | cachetools @ `3c082c6`, 10 gold cases |
| --- | --- | --- |
| resolved | 31 / 31 | 10 / 10 |
| mean nodes per tree | 12.4 | 4.4 |
| mean / max depth | 1.19 / 2 | **2.0 / 2** |
| trees reaching hop 2 | 6 | **10** |
| jedi calls | 176 | 966 |
| jedi hit rate | 100% | 90% |
| median / max latency | 42 ms / 1.0 s | 629 ms / 1.6 s |

The two sets fail differently, and that is the useful part. Synthetic trees are
**wide and shallow** — a flat module with a lot of module-level mutable state,
so most nodes are `touches` at hop 1. cachetools trees are **narrow and deep** —
every single one reaches hop 2, because the library's API *is* its class
hierarchy and its operators. This is direct evidence for the two design
decisions the sections above argued for on recall grounds alone: a navigator
with only `jedi.goto` at one hop would find almost nothing in cachetools.

It also quantifies the filtering. On `test_ttl`, jedi is asked **202** times to
produce a tree of **6** nodes. The gap between "definitions returned" and
"definitions kept" is where precision comes from, and it is now a recorded
number per call rather than an inference.

### One result that changes how these numbers should be read

> The navigator resolves names with jedi, and **jedi resolves against what is
> importable**. Running the same evaluation under two interpreters on the same
> machine, with no repository change in between:
>
> | | jedi 0.20.0, freezegun present | jedi 0.19.1, freezegun absent |
> | --- | --- | --- |
> | `test_case_19` code under test | 3 chunks | 1 chunk |
> | `test_case_19` shared state | 17 | 8 |
>
> Every navigator number in this document is therefore conditional on its
> environment. `jedi>=0.20.0` is now pinned in `pyproject.toml`, and the
> pipeline's `test` stage records `jedi --version` and a full `pip freeze`
> alongside the results. This was found while building the trace — it is
> exactly the class of silent drift the `gate` stage's navigator checks exist
> to catch.

---

## Correction, 2026-10-11: dependencies were being counted as code under test

The addendum above reported that the same test id resolved to 3 chunks under
jedi 0.20 and 1 chunk under 0.19, and attributed the difference to the jedi
version. That was half the story, and the smaller half.

**The real cause was a navigator bug.** `_is_within()` asked only "is this
path under the repository root?". A virtualenv sits *inside* the repository
root, so every installed package answered yes. With `freezegun` importable,
`@freeze_time` made jedi resolve into
`.venv/Lib/site-packages/freezegun/api.py`, and that counted as code under
test.

On `test_case_21`, **11 of 20 chunks were freezegun internals**:

| | before | after |
| --- | --- | --- |
| `test_case_21` code under test | 3 (2 of them freezegun) | 1 |
| `test_case_21` shared state | 17 (9 of them freezegun) | 8 |
| vendored chunks in the result | 11 of 20 | 0 |

This is worse than noise. The evidence bundle carries only the first few
chunks, so third-party source does not sit harmlessly at the bottom of the
list — it **pushes the repository's own code out of the bundle entirely**. A
`freezegun` internal scoring 2.35 outranked `shop.py` scoring 1.00 on the very
case whose planted root cause is in `shop.py`.

The fix excludes vendored directories (`site-packages`, `dist-packages`,
`.venv`, `venv`, `.tox`, `.nox`, `node_modules`, `__pypackages__`, `.eggs`)
even when they sit under the repository root.
`tests/test_navigator.py::test_a_virtualenv_inside_the_repo_is_not_code_under_test`
builds a repository with a fake installed package and asserts it never
reaches the result.

**The interpreters now agree.** The jedi-0.19 numbers were closer to correct
by accident: 0.19 could not see `freezegun`, so it could not resolve into it.
Both interpreters now give the same answer, which is the outcome that matters
more than either number.

### What this changes in the measured results

| | before the fix | after |
| --- | --- | --- |
| synthetic, mean tree nodes | 12.39 | 10.77 |
| synthetic, trees reaching hop 2 | 6 | 1 |
| cachetools, every figure | unchanged | unchanged |

cachetools is unaffected because its checkout has no virtualenv inside it,
which is also why this went unnoticed for so long: **the bug was invisible on
the repository the navigator was scored against, and only appeared on the
one it ships inside.**

The honest reading of "trees reaching hop 2: 6 → 1" is that five of those six
second hops were the navigator walking into freezegun's class hierarchy. The
synthetic benchmark is a single flat module; it never had five real second
hops. The quality gate's synthetic hop-2 check is therefore a bare floor, and
the real guard on the expansion pass is the external check, where all ten
cachetools trees reach hop 2.
