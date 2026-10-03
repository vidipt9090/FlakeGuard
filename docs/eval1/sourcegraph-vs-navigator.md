# Sourcegraph, tried and measured (work package B1)

Author: B. Date: 2026-10-03. Laptop 1 (Ryzen 7 6800H, 15.2 GB RAM, RTX 3050 4 GB).

**Short answer: Sourcegraph self-hosting works, and we still need our own
navigator.** Those are two separate findings and the second does not depend on
the first failing.

## What was tried

| step | result |
| --- | --- |
| `sourcegraph/server` still published? | yes. 13,371 tags, newest `6.12.5040` pushed 2026-02-10. The plan's worry that free self-hosting is gone is wrong. |
| `docker pull sourcegraph/server:latest` | fails: there is no `latest` tag. You must name a version. This is the first thing that trips you up. |
| image size | 1.09 GB compressed over 26 layers, 4.24 GB on disk |
| `docker run -d -p 7080:7080 sourcegraph/server:6.10.3349` | came up and served HTTP 200 on `localhost:7080` |
| memory while idle with one repo | **968 MiB**, 12.8% of the 7.36 GB the Docker VM was given |
| admin account | created through `POST /-/sign-up`; the first account becomes site admin |
| add a public repo with no access token | works. An `OTHER` code host with `{"url":"https://github.com/","repos":["tkem/cachetools"]}` cloned cachetools without any GitHub credentials |
| symbol search | works: `repo:cachetools type:symbol LRUCache` returns `CLASS` at line 286, the same definition our navigator reports |

Reproduce:

```bash
docker run -d --name sg-trial --publish 7080:7080 \
  --volume "$PWD/sourcegraph-trial/config:/etc/sourcegraph" \
  --volume "$PWD/sourcegraph-trial/data:/var/opt/sourcegraph" \
  sourcegraph/server:6.10.3349
# then open http://localhost:7080 and create the first account
```

Correcting two things in the plan: it is *not* too heavy for this laptop
(968 MiB, not the 8 GB the docs imply for a one-repo instance), and it is *not*
unavailable. Anyone repeating this should not claim either.

## Why we still write our own navigator

Two measurements, not opinion.

**1. There is no precise code intelligence for Python out of the box.**

```
{repository(name:"github.com/tkem/cachetools"){commit(rev:"HEAD")
  {blob(path:"tests/test_lru.py"){lsif{__typename}}}}}
  ->  {"lsif": null}
```

`null` means no SCIP index. Navigation falls back to search-based heuristics:
match the identifier under the cursor against the symbol index and guess.
Precise navigation needs a `scip-python` index built and uploaded from CI, which
is a second pipeline to own, on top of the one A is already building.

**2. The symbol index misses exactly the code our tests exercise.**

cachetools defines `__setitem__` eight times (`src/cachetools/__init__.py`
lines 35, 77, 178, 231, 300, 343, 497, 635). Sourcegraph finds none of them:

| query | matches |
| --- | --- |
| `repo:cachetools type:symbol __setitem__` | **0** |
| `repo:cachetools type:symbol popitem` | 8 |
| `repo:cachetools type:symbol fixture` | 0 |

Ordinary methods index fine; dunder methods do not. That is not a cosmetic gap
for this project. Every assertion in the cachetools cache tests is written as
`cache[1] = 1`, which *is* a `__setitem__` call. The one construct Sourcegraph
cannot see is the one the tests are made of.

## The task we actually need done

Given a failing test id, produce: the code under test, the fixtures it pulls in,
the module-level mutable state it can touch, and the nondeterminism smells in
all of that. Then hand it to an LLM as a bounded evidence bundle.

Sourcegraph answers a different question. It is a search engine: you give it a
name and it finds occurrences. Our input is a test id, and the name is what we
do not have yet. Working from `tests/test_lru.py::LRUCacheTest::test_lru` in the
UI means a human reads the test, notices `LRUCache`, searches for it, reasons
that `cache[1] = 1` must land in a `__setitem__` somewhere up the MRO, and
searches again. The inference is done by the person, and it is the inference we
need automated.

Concretely, for the same test:

| capability | Sourcegraph (search-based) | `flakeguard` navigator v0.2 |
| --- | --- | --- |
| find `LRUCache` by name | yes | yes |
| from a test id, with no name given | no, you supply the name | yes, resolves from the AST |
| `cache[1] = 1` to the class that implements it | no, dunders are not indexed | yes, by inferring the receiver's type |
| walk to base classes that supply the behaviour | no | yes, one hop |
| resolve pytest fixtures through the `conftest.py` chain | no, fixtures are resolved by name at runtime, not by import | yes |
| list module-level mutable state the test can reach | no | yes |
| flag `time.sleep`, `random.`, `threading.` in reachable code | grep, unranked, whole repo | yes, scoped to this test |
| output shaped as `NavResult` chunks for an LLM bundle | no | yes, that is the contract |

Measured end to end on a **held-out** set of 8 tests the navigator was never
built against: precision 0.58, recall 0.38, F1 0.46, correct answer in the top
3 for 8 of 8, median 0.18 s per test. On the 10 tests it *was* tuned against it
scores 1.00 / 0.86, which is why that number is not the one quoted here. See
`nav-results.md` for both, the protocol, and the bug the held-out set caught.

The capability table above is about what each tool can express, not about
accuracy. A row marked "yes" means the navigator attempts it and the output
shape supports it, not that it succeeds every time — recall 0.38 says plainly
that it often does not.

## Honest limits of this comparison

- We ran Sourcegraph **without** a `scip-python` index. With one, its precise
  navigation would be much stronger and would likely resolve dunder dispatch.
  We did not try, because building and uploading SCIP from CI is its own work
  package and the 45-minute box does not fit it. Anyone who says "Sourcegraph
  cannot do this" is overclaiming. The accurate claim is: not out of the box,
  and not without a second pipeline.
- Even with a perfect index, Sourcegraph still would not answer the fixture,
  shared-state and smell questions, because those are pytest semantics rather
  than general code-graph facts. That part of the argument does not depend on
  indexing at all.
- Version tested was `6.10.3349`, which was already on the laptop from an
  earlier attempt. `6.12.5040` was also pulled and is available if we want to
  re-check on the current release.

## Where this leaves us for Eval 2

Sourcegraph is worth keeping as a demo of the course's named tool and as a
human-facing browser over the same repos. It is not on the critical path. If we
want to revisit it, the one experiment worth running is `scip-python` plus an
upload, and then re-running this comparison table.

## Cleanup

```bash
docker stop sg-trial && docker rm sg-trial   # data stays in ./sourcegraph-trial
```
