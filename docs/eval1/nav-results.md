# Navigation results (work package B3)

Author: B. Date: 2026-10-03. Navigator version: v0.4 (`flakeguard/navigator/ast_nav.py`).

## Headline

Three gold sets, built in that order, each because the one before it had
stopped being able to answer the question.

| gold set | target | precision | recall | F1 | top-3 | precision@5 |
| --- | --- | --- | --- | --- | --- | --- |
| 1, tuned (`nav-gold.json`) | cachetools, 10 tests | 0.96 | 0.93 | 0.95 | 100% | 0.96 |
| 2, spent (`nav-gold-heldout.json`) | cachetools, 8 tests | 0.60 | 0.52 | 0.56 | 100% | 0.64 |
| **3, second repo** (`nav-gold-itsdangerous.json`) | **itsdangerous, 10 tests** | **0.52** | **0.91** | **0.66** | **100%** | **0.72** |

Fixtures, scored for the first time on set 3 (cachetools has none at all):
**precision 0.90, recall 1.00** (18 true positives, 2 false, 0 missed).

Latency on laptop 1: median 0.22 s, max 0.83 s per test across both repos.

**If one number is quoted, quote precision@5 = 0.72 with recall 0.91 on an
unseen repository.** Precision over the whole returned list (0.52) and the
tuned 0.96 are both misleading, in opposite directions, for reasons below.

## Why three sets, and what each is good for

Each set is biased, and the useful thing is that the directions differ.

**Set 1 is biased upward and cannot be fixed.** Two channels, not one:
the labels were revised after seeing output (four disputed items examined,
four resolved in the tool's favour — four out of four is the signature of
motivated labelling), *and* the navigator's filters were tuned on those same
10 tests. Precision is the metric those filters optimise. 0.96 measures fit,
not skill.

**Set 2 was blind for exactly one run, then spent.** It was drawn from four
cachetools files the navigator had never been run against, labelled from
source, and committed before scoring. It immediately earned its keep (below).
Fixing the bug it found means it can no longer measure generalisation either.

**Set 3 is the current estimate, and is biased *downward*.** A different
repository, so nothing about cachetools' structure can leak in, and a
pytest-style project with real fixtures. Its labels were written blind and
conservatively: only the code a test directly asserts on. Inspection of the
"false positives" shows most of them genuinely execute —
`Serializer.dumps` literally calls `want_bytes`, `dump_payload`,
`make_signer` and `Signer.sign`, none of which the blind labels listed. So
0.52 understates precision as surely as 0.96 overstates it.

**Those labels have not been revised, and will not be.** Correcting them
upward after seeing output is exactly what spoiled set 1. The honest reading
is that true precision sits between the two, and `precision@5 = 0.72` — the
first five ranked chunks, which is what an evidence bundle actually carries —
is the figure least exposed to either bias.

Residual bias that no set removes: the same person wrote the navigator and
every label. **An independent re-label by A or C is the missing control**, and
it is cheap. It is the single thing most worth doing before Eval 2.

## What the held-out sets caught

Neither bug could have been found on set 1, and both were serious.

**Set 2, first run: inherited tests resolved to nothing.** Three of eight
tests scored zero on every metric. pytest reports an inherited test under the
concrete class, but the body lives in a mixin:

```python
class DecoratorTestMixin(_TestCaseProtocol):
    def test_decorator(self): ...          # the body is here

class LRUDecoratorTest(unittest.TestCase, DecoratorTestMixin):
    DECORATOR = staticmethod(cachetools.func.lru_cache)   # the id says this
```

`CacheTestMixin` supplies 23 of cachetools' tests on its own. All 10 tests in
set 1 happen to be defined directly in their own class, so set 1 was
structurally incapable of noticing.

**Set 3, first run: the gold set itself was broken.** Fixture scores came back
at precision 0.25 / recall 0.28. The navigator was returning exactly the right
fixtures; the labels were wrong. Their line numbers had been read from the
`main` checkout *before* the repo was pinned to tag 2.2.0, so every fixture in
the file was off by one and scored as a miss.

That is a measurement failure, not a navigator failure, and hand-patching the
numbers would have meant exercising judgment over the gold set again. Instead
`tools/relocate_gold.py` recomputes every line mechanically from the pinned
checkout by symbol name. It rewrites only `start_line`, never a name and never
which entries exist, refuses any name matching several definitions (there are
four `cache_info` closures in `_cached.py`, one per wrapper builder, and only
one of them runs), and prints every change. Applied to all three sets: set 1
needed **0** corrections, set 2 one, set 3 seventeen. Fixtures then scored
0.90 / 1.00.

Worth keeping: a gold set pinned by line number is itself a thing that can
silently break. Re-run that tool whenever a target repo is re-pinned.

## v0.2 to v0.4: what moved the numbers

| change | why | effect |
| --- | --- | --- |
| find tests inherited from a mixin | pytest reports the id under the concrete class; the body is in the base | set 2 top-3 62.5% to 100% |
| resolve `self.x` against the **concrete** class | the mixin declares the hook, the subclass supplies what runs; jedi resolves `self` to the base and finds the abstract stub | recovered `CacheWrapperTest.cache`, `DECORATOR` |
| one step into a resolved function's body | `cached()` imports `_wrapper` inside itself and calls it from a closure, so the function doing the work is invisible from the test | largest recall bucket on set 2 |
| callee default arguments | `cachedmethod(cache, key=keys.methodkey)` names the key function the test never mentions | recovered `methodkey`, `hashkey` |
| fixtures: class scope, base classes, conftest chain, transitive, autouse | pytest resolves fixtures by name through all of these; v0.3 looked only at module level and conftest | fixture recall 1.00 on set 3 |
| resolve what a **fixture builds** | the test sees an untyped parameter; the class under test is only reachable through the fixture that made it | without it, fixture-based suites resolved **nothing** |
| drop abstract stubs (`...`, `pass`, `NotImplementedError`) | Protocol declarations and template hooks resolve like any function but never run | removed the `_TestCaseProtocol` false positives |

Set 1 moved 0.92 to 0.95 F1, set 2 moved 0.46 to 0.56, and neither regressed,
so these are genuine improvements rather than a trade between targets.

## What still misses, and why

**Runtime dispatch.** `cached()` picks one of eight wrapper builders from the
*values* of `lock`, `condition` and `info` at decoration time. Static
resolution reaches `cached` and stops. The navigator often returns the wrong
variant's `cache_info`. No amount of AST work fixes this; it is the strongest
argument for pairing static navigation with the runtime data A's collector
produces.

**Return types.** `hashkey()` returns a `_HashedTuple` whose `__hash__` and
`__eq__` are what the test asserts on. Nothing in the source text names it.
jedi can execute a function and report return types; v0.4 does not. This is
the clearest remaining win.

**Deep inheritance.** Expansion is one hop, so `TTLCache -> _TimedCache` is
found and `_TimedCache -> Cache` is not. A deliberate bound: each hop costs
jedi round trips and widens the chunk set C's bundle must fit in 2-4k tokens.

## Reproduce

```bash
git clone https://github.com/tkem/cachetools.git ../cachetools
cd ../cachetools && git checkout 3c082c654c2804b9354e4b62dbd2994f1aac464d && cd -
git clone https://github.com/pallets/itsdangerous.git ../itsdangerous
cd ../itsdangerous && git checkout 2.2.0 && cd -

# the number to quote
python -m flakeguard.navigator.evaluate --repo ../itsdangerous \
    --gold docs/eval1/nav-gold-itsdangerous.json --markdown
# the cachetools sets, for contrast
python -m flakeguard.navigator.evaluate --repo ../cachetools --gold docs/eval1/nav-gold.json
python -m flakeguard.navigator.evaluate --repo ../cachetools --gold docs/eval1/nav-gold-heldout.json
# after re-pinning any target repo
python tools/relocate_gold.py docs/eval1/<gold>.json --repo ../<checkout>
```

The navigator is purely static: it parses the target but never imports it, so
the target's own dependencies need not be installed. itsdangerous' tests
require `freezegun`, which is not in our venv, and navigation works anyway.

## Things these measurements still do not tell you

- **28 tests across two libraries is a small sample.** No confidence intervals
  are quoted because they would be meaningless at this size.
- **Both targets are clean, well-typed libraries.** Nothing here predicts
  behaviour on a messy codebase, which is what Emma is.
- **Shared state is barely represented.** One module-level global across both
  suites. Worse, `test_classmethod.py` keeps its mutable state in **class**
  attributes (`Cached.cache`, `Cached.count`) — the same flakiness mechanism,
  but outside the `NavResult` contract's wording of "module-level mutable
  globals". **Worth raising with A and C: the contract may need widening.**
- **No measurement on planted flakes yet.** `synthetic/` is C's work package
  and is where order-dependence and shared-state navigation get tested for
  real.
