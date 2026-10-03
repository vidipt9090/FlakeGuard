# Navigation results (work package B3)

Author: B. Date: 2026-10-03. Navigator version: v0.2 (`flakeguard/navigator/ast_nav.py`).

## What was measured

Target: cachetools pinned at `3c082c654c2804b9354e4b62dbd2994f1aac464d` (v7.2.0),
the sha frozen in the root README. 10 tests chosen to cover the eviction
policies, the key functions, the timed caches and the threading suite.

Ground truth is hand written in `nav-gold.json`: for each test, the definitions
whose behaviour the test asserts on. A predicted chunk counts as a match when
the path is equal and the gold start line falls inside the predicted span.
Spans are compared loosely on purpose, because jedi and `ast` disagree by a
line on where a class body ends and a navigator that found the right class
should not be marked wrong for that.

Reproduce:

```bash
python -m flakeguard.navigator.evaluate --repo ../cachetools \
    --gold docs/eval1/nav-gold.json --markdown
```

## Numbers

| test | TP | FP | FN | precision | recall | correct in top 3 |
| --- | --- | --- | --- | --- | --- | --- |
| `LRUCacheTest::test_lru` | 2 | 0 | 0 | 1.00 | 1.00 | yes |
| `LFUCacheTest::test_lfu` | 2 | 0 | 0 | 1.00 | 1.00 | yes |
| `FIFOCacheTest::test_fifo` | 2 | 0 | 0 | 1.00 | 1.00 | yes |
| `RRCacheTest::test_rr` | 2 | 0 | 0 | 1.00 | 1.00 | yes |
| `RRCacheTest::test_rr_bad_choice` | 3 | 0 | 0 | 1.00 | 1.00 | yes |
| `TTLCacheTest::test_ttl` | 4 | 0 | 1 | 1.00 | 0.80 | yes |
| `TLRUCacheTest::test_ttu` | 4 | 0 | 0 | 1.00 | 1.00 | yes |
| `CacheKeysTest::test_hashkey` | 1 | 0 | 1 | 1.00 | 0.50 | yes |
| `CacheKeysTest::test_typedkey` | 1 | 0 | 1 | 1.00 | 0.50 | yes |
| `ThreadingTest::test_cached_stampede` | 3 | 0 | 1 | 1.00 | 0.75 | yes |
| **overall (10 tests)** | 24 | 0 | 4 | **1.00** | **0.86** | **100%** |

Micro F1 0.92. Latency per test on laptop 1: min 0.05 s, median 0.18 s,
max 0.63 s, 0.75 s cold including the import. Fast enough to run live.

## Read the precision with suspicion

Precision of exactly 1.00 is not a result to be proud of without the history,
so here is the history.

| gold version | precision | recall | F1 | top 3 |
| --- | --- | --- | --- | --- |
| v1, written blind before any run (`nav-gold-v1.json`) | 0.58 | 0.82 | 0.68 | 100% |
| v2, corrected after reading the source (`nav-gold.json`) | 1.00 | 0.86 | 0.92 | 100% |

v1 listed only the class each test names. Every v1 "false positive" turned out
to be code that genuinely runs:

- `Cache` (`__init__.py:45`) is the base class. Every `cache[1] = 1` in these
  tests dispatches to `Cache.__setitem__`. v1 omitted it because I was thinking
  about which class the test *mentions*, not which code *executes*.
- `_TimedCache._Timer` (`:376`) is what `cache.timer()` calls.
- `cache_info` (`_cached.py:49`) is called outright as `func.cache_info()`.
- `bad_choice` (`test_rr.py:72`) and the `Timer` classes in `test_ttl.py:9` /
  `test_tlru.py:13` are callbacks and fake clocks the test hands in and the
  library then invokes.

Each addition is justified by a mechanism recorded in the `why` field of
`nav-gold.json`, and anyone can check it by reading the source. But the
correction was made *after* seeing v0.2's output, and that is a known way to
flatter a tool. **Treat 1.00 as an upper bound and 0.58 as a lower bound.** The
honest reading is that the navigator is precise on this suite, not perfect.

The fix is an independent re-label: A or C should label the same 10 tests from
the source alone without seeing navigator output, and we take that as v3. That
is cheap and worth doing before Eval 2, when these numbers start carrying real
weight. Recall and the top-3 figure are much less exposed to this problem,
because adding gold entries can only push recall *down*.

## The three failures, and why

**1. `_HashedTuple` — a return type, not a call.** (`test_hashkey`,
`test_typedkey`, recall 0.50 on both.) The test does
`self.assertEqual(hash(key()), hash(key()))`. The object being tested is what
`hashkey()` *returns*. Resolving the name `hashkey` lands on the function;
nothing in the source text names `_HashedTuple`. Finding it needs return-type
inference (`jedi` can execute a function and report its return types), which
v0.2 does not do. This is the clearest single win available for v0.3.

**2. `_condition_info` — dispatch chosen at runtime.** (`test_cached_stampede`,
recall 0.75.) `cached()` picks one of six wrapper builders depending on whether
`lock`, `condition` and `info` were passed. Which one runs is decided by the
argument values at decoration time. Static resolution reaches `cached` and
stops; no amount of AST work tells you that `condition=...` plus `info=True`
selects `_condition_info`. Honest limitation of static navigation, and a good
argument for pairing it with the runtime data A's collector produces.

**3. `Cache` under `TTLCache` — expansion is one hop deep.** (`test_ttl`,
recall 0.80.) v0.2 expands a found class to its base classes, so
`TTLCache -> _TimedCache` is found. `_TimedCache -> Cache` is a second hop and
is not followed. This is a deliberate bound, not an oversight: each hop costs
jedi round trips and widens the chunk set that C's evidence bundle has to fit
in 2-4k tokens. Full MRO walking is a one-line change if Eval 2 shows we want
it; the cost is noise, not correctness.

## What changed between v0.1 and v0.2

v0.1 did what the work package describes: collect called names, resolve each
with jedi, keep repo-local definitions. On cachetools that scores badly, and
the reasons are worth recording because they generalise to any real library.

| change | why | effect |
| --- | --- | --- |
| infer the *type* of operator receivers | `cache[1] = 1` is a `__setitem__` call with no name to resolve. A container library's API *is* its operators. | the single largest gain; without it most cache tests resolve nothing |
| hop from `.pyi` stub to the `.py` implementation | jedi prefers type stubs. A stub is a signature, not the code that runs, so `cached` resolved to a declaration with no body | fixed every `_cached.py` / `_cachedmethod.py` result |
| resolve bare names used as values | `Thread(target=func)` never calls `func` by name, but `func` is the code under test | found `func` in the threading suite |
| expand to base classes and decorators | inheritance and decoration run without being named in the test | recall 0.53 to 0.77 on gold v1 |
| raise the resolution cap from 40 to 150 | `ast.walk` is breadth-first, so a low cap silently drops names nested deep inside a call, which is where callbacks like `timer=Timer()` live | found `Timer`; worst-case latency still 0.63 s |
| drop type stubs, `TestCase` scaffolding and the test's own class from results | inferring `self` resolves to the TestCase subclass, which is not code under test | precision, and much shorter output |

## Things this measurement does not tell you

- **No fixtures were exercised.** cachetools has no `conftest.py` and no pytest
  fixtures anywhere; it is a `unittest` suite. The fixture and conftest-chain
  logic is covered by `tests/test_navigator.py` against
  `tests/data/navsample`, and will be exercised for real against C's
  `synthetic/` project. Any claim about fixture navigation rests on those, not
  on this table.
- **Shared state barely appears.** cachetools is a clean library with one
  module-level global in the whole test suite (`count` in `test_threading.py`,
  which the navigator does find). The order-dependence case this project exists
  to catch is not represented here. `synthetic/` is where that gets measured.
- **10 tests is a small sample.** No confidence intervals are quoted because
  they would be meaningless at this size. Eval 2 should widen the gold set and
  add a second target repo.
