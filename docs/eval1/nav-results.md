# Navigation results (work package B3)

Author: B. Date: 2026-10-03. Navigator version: v0.3 (`flakeguard/navigator/ast_nav.py`).

## Headline

Two numbers, and the gap between them is the point.

| gold set | precision | recall | F1 | correct in top 3 |
| --- | --- | --- | --- | --- |
| **tuned** (`nav-gold.json`, 10 tests the navigator was built against) | 1.00 | 0.86 | 0.92 | 100% |
| **held out** (`nav-gold-heldout.json`, 8 tests it had never seen) | **0.58** | **0.38** | **0.46** | **100%** |

**Quote the held-out row.** The tuned row measures how well the navigator fits
the code it was written against, which is not a property anyone cares about.
If a single number is needed for a slide: *F1 0.46 on unseen tests, with the
correct answer in the top 3 every time.*

## Why there are two gold sets

The first version of this document reported precision 1.00 and said it should
be read as an upper bound. That warning was not strong enough. There were two
separate ways the number was fitted to the data, not one.

1. **The labels were revised after seeing output.** Four disputed items were
   re-examined and all four were reclassified in the tool's favour. Each
   individual justification is sound and checkable in the `why` fields of
   `nav-gold.json`, but four out of four is the signature of motivated
   labelling. A neutral re-reading should break both ways sometimes.
2. **The navigator was tuned on the same 10 tests.** The `.pyi` filter, the
   TestCase-scaffolding filter, the dedupe-by-start-line rule and the
   resolution cap of 150 were each added because of noise seen in *those*
   tests' output. Precision is the metric those filters directly optimise, so
   precision is the number least entitled to trust.

So `nav-gold-heldout.json` was built. The protocol, recorded in the file and
visible in the git history:

- Tests drawn only from `test_cached.py`, `test_cachedmethod.py`,
  `test_classmethod.py` and `test_func.py` — four files the navigator had never
  been run against. Development used `test_lru`, `test_lfu`, `test_fifo`,
  `test_rr`, `test_ttl`, `test_tlru`, `test_keys`, `test_threading` only.
- Labels written from source alone, before the navigator was run on any of
  those ids even once.
- The file committed **before** the first scoring run
  (`b9e8091 test(navigator): held-out gold set, labelled before any scoring run`),
  so the history shows the labels were not adjusted to fit the result.

Residual bias that remains, stated plainly: the same person wrote the navigator
and the labels, and knows how it resolves names. This is held-out *data*, not an
independent labeller. A re-label by A or C is still worth doing.

## What the held-out run found

First run, before any fix:

```
micro precision 0.652  recall 0.259  f1 0.370  correct-in-top-3 62.5%  (8 tests)
```

Three of the eight scored **zero on every metric**: `LRUDecoratorTest::test_decorator`,
`CacheWrapperTest::test_decorator` and `CacheMethodTest::test_decorator`.

One cause for all three. **Inherited test methods were not found at all.**
pytest reports an inherited test under the concrete class, but the body lives
in a mixin:

```python
class DecoratorTestMixin(_TestCaseProtocol):
    def test_decorator(self): ...          # the body is here

class LRUDecoratorTest(unittest.TestCase, DecoratorTestMixin):
    DECORATOR = staticmethod(cachetools.func.lru_cache)   # the id says this
```

`_locate` looked only in the named class's own body, found nothing, and
returned an empty `NavResult`. This is not an edge case: `CacheTestMixin`
supplies 23 of cachetools' tests on its own. The tuned set could never have
exposed it, because all 10 of those tests happen to be defined directly in
their own class.

Fixed in v0.3 by walking base classes depth-first with jedi when a method is
not in the named class, and navigating against the file the body actually
lives in. Regression test: `test_finds_a_test_inherited_from_a_mixin`.

After the fix, on the same held-out set:

```
micro precision 0.579  recall 0.379  f1 0.458  correct-in-top-3 100.0%  (8 tests)
```

Top-3 went 62.5% to 100%, recall 0.26 to 0.38, F1 0.37 to 0.46. Precision fell
slightly because the three previously-empty tests now return results, some of
them wrong. The tuned set is unchanged at 1.00 / 0.86, so this is not a
trade-off between the two sets.

**Disclosure: the post-fix number is no longer blind.** A bug was found using
the held-out set and then fixed, which is exactly the contamination this set
existed to avoid. 0.46 is therefore itself a mild over-estimate. It is reported
because it is still far more honest than the tuned 0.92, and because hiding a
real bug to protect a measurement would be the worse trade. No further tuning
was done against this set after the fix. Eval 2 needs a *third*, fresh held-out
set, ideally labelled by A or C.

## Where the remaining held-out recall goes

Recall is 0.38, so roughly three in five gold entries are still missed. They
are not scattered: three systematic causes account for nearly all of them.

**1. Resolution does not enter function bodies (`_wrapper`, missed in 6 of 8).**
`cached()` does `from ._cached import _wrapper` *inside* its own body and calls
it from a nested `decorator` closure. v0.3 expands one hop outward (base
classes, decorators) but never walks *into* a found function. Every decorator
test in the held-out set loses `_wrapper` and its concrete builder this way.
This is the largest single bucket and the obvious v0.4 target.

**2. Dispatch is inverted by the mixin pattern (`CacheWrapperTest.cache`,
`Cache`).** The mixin calls `self.cache(2)`, and the mixin's own `cache` raises
`NotImplementedError`; the real implementation is in the concrete subclass.
Static resolution from inside the base cannot know which subclass is running.
This is the template-method pattern, and it defeats name resolution by design.
Runtime data from A's collector is the realistic answer, not more AST work.

**3. Callee default arguments (`methodkey`, `hashkey`).** `cachedmethod(cache,
key=keys.methodkey, ...)` carries the real key function as a default in the
*callee's* signature. v0.3 reads defaults in the test being navigated, not in
functions it resolves to.

Also still missing from both sets, unchanged: `_HashedTuple` (a return type, no
return-type inference) and `_condition_info` / `_unlocked` (which concrete
wrapper runs is decided at runtime from argument values).

New false positives the held-out set exposed: `tests/__init__.py:9,17,21`, the
`assertEqual`-style stubs of `_TestCaseProtocol`. They are repo-local so they
survive the filters. A Protocol-class filter would remove them — deliberately
**not** added, because tuning on the held-out set again is how the first set
was spoiled.

## Latency

Measured on laptop 1, tuned set: min 0.05 s, median 0.18 s, max 0.63 s,
0.75 s cold including the import. Fast enough to run live in the demo.

## Reproduce

```bash
python -m flakeguard.navigator.evaluate --repo ../cachetools \
    --gold docs/eval1/nav-gold-heldout.json --markdown    # the number to quote
python -m flakeguard.navigator.evaluate --repo ../cachetools \
    --gold docs/eval1/nav-gold.json --markdown            # the tuned set
python -m flakeguard.navigator.evaluate --repo ../cachetools \
    --gold docs/eval1/nav-gold-v1.json --markdown         # labels before revision
```

## Things this measurement does not tell you

- **No fixtures were exercised.** cachetools has no `conftest.py` and no pytest
  fixtures anywhere; it is a `unittest` suite. The fixture and conftest-chain
  logic is covered by `tests/test_navigator.py` against `tests/data/navsample`,
  and will be exercised for real against C's `synthetic/`. Any claim about
  fixture navigation rests on those, not on these tables.
- **Shared state barely appears.** One module-level global in the whole
  cachetools suite (`count` in `test_threading.py`, which the navigator finds).
  Worse, `test_classmethod.py` keeps its mutable state in **class** attributes
  (`Cached.cache`, `Cached.count`), which is the same flakiness mechanism but
  outside the `NavResult` contract's wording of "module-level mutable globals".
  Worth raising with A and C before Eval 2: the contract may need widening.
- **18 tests across two sets is a small sample.** No confidence intervals are
  quoted because they would be meaningless at this size.
- **Both sets come from one repo.** cachetools is a clean, well-typed library.
  Nothing here predicts behaviour on a messy codebase, which is what Emma is.
