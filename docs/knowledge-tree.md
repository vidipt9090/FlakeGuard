# The knowledge tree

Author: B. Date: 2026-10-10.
Code: `flakeguard/navigator/knowledge_tree.py`, `flakeguard/navigator/trace.py`.

## What it is, and what problem it solves

The navigator answers: given a failing test id, which code does this test
actually exercise? Its answer is a `NavResult` — four flat lists:
`code_under_test`, `fixtures`, `shared_state`, `smells`.

That shape is right for the evidence bundle and wrong for understanding,
because it throws away the one thing that explains the answer: **how far from
the test each thing is.** A class the test instantiates on line 3 and a base
class found two hops up the hierarchy land in the same list with nothing but a
score to tell them apart.

The knowledge tree puts the structure back:

```
TEST  tests/test_ttl.py::TTLCacheTest::test_ttl
|- [calls]           TTLCache  src/cachetools/__init__.py:451  score 13.00
|  `- [expands]      _TimedCache  src/cachetools/__init__.py:373  score 0.45
|- [calls]           Timer  tests/test_ttl.py:9  score 1.00
|- [infers]          _Timer  src/cachetools/__init__.py:376  score 2.00
`- [smells]          time.monotonic  src/cachetools/__init__.py:451
```

Read that tree and the navigator's behaviour is legible. `TTLCache` is named
by the test, so `jedi.goto` found it. `_TimedCache` is never mentioned
anywhere in the test — it is `TTLCache`'s base class, so the expansion hop
found it, one level further out and scored accordingly. `_Timer` is not named
either; it is the *type* of a value the test uses an operator on, which only
`jedi.infer` can tell you.

The tree is derived. `NavResult` stays the contract and the evidence bundle
still reads only that.

## The edges

Every node except the root records the edge that reached it. The edge is the
mechanism, which is why it is worth naming rather than just drawing a line.

| Edge | Found by | Meaning |
| --- | --- | --- |
| `calls` | `jedi.goto` | the test names it |
| `infers` | `jedi.infer` | the test uses an operator on it, so the *type* is the real target. `cache[1] = 1` never names `__setitem__` |
| `fixture` | ast | a pytest fixture the test requests, or an autouse one |
| `fixture-builds` | `jedi.goto` | built by a fixture; the test only ever sees an untyped argument |
| `overrides` | ast | `self.x` in an inherited test, resolved against the concrete class the test id names |
| `expands` | `jedi.goto` | reached from its parent's base classes, decorators, callee defaults, or one step into its body |
| `touches` | ast | module-level mutable state in a file this test reaches |
| `smells` | ast | a flakiness pattern matched in directly-exercised code |
| `reaches` | — | the edge was not recorded; the tree was built from a `NavResult` with no provenance |

`reaches` only appears when a tree is built from a result loaded off disk. It
is named explicitly rather than guessed, because an invented edge would be a
wrong explanation, which is worse than an absent one.

## Depth

`depth` is hop distance from the test. 0 is the test itself, 1 is something the
test names directly, 2 is what *that* is built on.

Depth is not cosmetic — it is the same axis the evidence weights use:

| | weight | why |
| --- | --- | --- |
| direct name resolution | 1.0 | the test wrote it down |
| `self.x` concrete override | 0.9 | the class the id names supplies what runs |
| what a fixture built | 0.8 | one indirection, but the test drives it |
| one expansion hop | 0.45 | library infrastructure, reachable from every test |

`DIRECT_SCORE = 0.8` is the line between "this test drives it" and "the
library is built on it", and the smell scan only looks below it. That matters:
scanning everything reachable in a library whose job involves clocks made
every tenacity test report `timing`, because `BaseRetrying` uses
`time.monotonic`. A smell on every test carries no information.

`EXPAND_ROUNDS = 1`, so trees top out at depth 2 today. A second round does
reach further and lifts recall, and it cost 12 points of F1 and dropped
correct-in-top-3 from 100% to 75% — recall is worth nothing if the right chunk
no longer fits in the bundle. The tree makes that trade visible instead of
leaving it as a constant in a file.

## The trace

`NavTrace` records how the tree was built: one ordered `TraceEvent` per step,
each tagged with its phase and the hop depth it happened at.

| Phase | What it does |
| --- | --- |
| `locate` | test id → file, class, function (pure ast) |
| `inherit` | the body is in a base class, not the class the id names |
| `ast_walk` | walk the test body, collect every candidate name |
| `jedi_goto` | name → definition |
| `jedi_infer` | expression → the type whose operator actually runs |
| `fixture` | test arguments → the conftest.py chain |
| `concrete` | `self.x` → the override in the class the test id names |
| `expand` | a definition's bases, decorators, defaults and callees |
| `shared_state` | module-level mutable values in reachable files |
| `smell` | flakiness pattern scan |

Each event carries `results` (how many definitions jedi returned) and `kept`
(how many survived filtering). **The gap between those two is where precision
comes from** — a `goto` that returns three definitions in `site-packages`
found nothing useful, and on `test_ttl` jedi is asked 202 times to produce a
tree of 6 nodes.

Tracing is off by default and costs one method call returning a shared no-op,
so `related()` is unaffected. `explain()` turns it on for one call:

```python
from flakeguard.navigator.ast_nav import AstNavigator

nav = AstNavigator("../cachetools", repo="cachetools", sha="3c082c6")
explained = nav.explain("tests/test_ttl.py::TTLCacheTest::test_ttl")

print(explained.tree.render())        # the text tree above
print(explained.tree.stats())         # nodes, depth, edges by type
print(explained.trace.summary())      # ast names, jedi calls, hit rate, ms
print(explained.result.code_under_test)   # unchanged NavResult
```

`tests/test_knowledge_tree.py` asserts that `explain()` and `related()` agree
on every chunk, so the instrumented path cannot drift from the contract one.

## Seeing it

**In the dashboard** — `streamlit run flakeguard/app/dashboard.py`:

- **🌳 Knowledge Tree** — the tree as a node-link drawing with depth on the x
  axis, a containment view, nodes-per-hop, the text form, a table of every
  node with what its edge means, and the source behind any node. A depth
  slider collapses the tree hop by hop.
- **🔬 AST → Jedi Trace** — the same navigation replayed. A step slider walks
  the event list; the chart shows which phase each step was in and the card
  below explains what that step did and what it returned. Plus steps per hop,
  goto-vs-infer resolution rates, and where the time went.

Both pages read exported JSON by default, and both can **run the navigator
live** against a checkout on the machine — pick a repo and a test id and watch
it resolve.

**As files** — exported by `scripts/export_knowledge_trees.py`, which the
`navigate` stage of the pipeline runs on every push:

```
results/knowledge_trees/<case>.json   tree + stats + full ordered trace
results/nav_trace.csv                  one row per case: shape and counters
results/nav_trace_summary.json         totals; the quality gate reads this
```

## Measured, as of 2026-10-10

Synthetic planted benchmark, 31 cases, `jedi 0.20.0`:

| | |
| --- | --- |
| resolved to something | 31 / 31 (100%) |
| mean nodes per tree | 12.4 |
| mean / max depth | 1.19 / 2 |
| trees reaching hop 2 | 6 |
| jedi hit rate | 100% |
| median / max latency | 42 ms / 1.0 s |

cachetools @ `3c082c6`, 10 gold cases:

| | |
| --- | --- |
| resolved | 10 / 10 |
| mean nodes per tree | 4.4 |
| mean / max depth | **2.0 / 2** — every tree reaches a second hop |
| jedi calls | 966 |
| jedi hit rate | 90% |
| median / max latency | 629 ms / 1.6 s |

The two sets say different things and both are worth having. The synthetic
trees are **wide and shallow**: a flat module with a lot of module-level
mutable state, so most nodes are `touches` at hop 1. The cachetools trees are
**narrow and deep**: every one reaches hop 2, because the library's API *is*
its class hierarchy and its operators. A navigator that only did `jedi.goto`
at one hop would find almost nothing there — which is the reason both
resolution paths and the expansion hop exist.

> **These numbers depend on the installed resolver.** Under jedi 0.19.1
> without `freezegun`, `test_case_19` resolved to 1 chunk instead of 3. The
> pipeline records `jedi --version` and a full `pip freeze` next to the
> numbers for exactly this reason, and `jedi>=0.20.0` is now pinned in
> `pyproject.toml`.
