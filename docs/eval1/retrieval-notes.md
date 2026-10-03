# Embeddings smoke test (work package B5)

Author: B. Date: 2026-10-03. Laptop 1 (Ryzen 7 6800H, 15.2 GB RAM, RTX 3050 4 GB).

B5 is the optional task and the first thing on the cut list, so this is a
smoke test and nothing more: does semantic search over code chunks return
anything a person would call relevant, on this laptop? It is the seed of the
Eval 2 retriever, not the retriever.

## What was built

| piece | where |
| --- | --- |
| chunker, one chunk per function / class / method | `flakeguard/retrieval/chunker.py` |
| embed into Chroma, query it | `flakeguard/retrieval/embed.py` |
| tests | `tests/test_retrieval.py` |

```bash
pip install -e ".[rag]"      # optional extra, NOT in dev
python -m flakeguard.retrieval.embed --repo ../cachetools \
    --repo-name cachetools --sha 3c082c6 --query "cache eviction" -k 3
```

**The heavy dependencies are deliberately not in `dev`.** `chromadb` and
`sentence-transformers` pull in PyTorch, about 2.5 GB. `ci.yml` installs
`.[dev]`, so CI never downloads it; the chunker underneath is pure `ast` and is
fully tested there. The one test that needs a real model is skipped unless the
extra is installed. Running CI should not cost three minutes of wheel
downloads to test code that does not use them.

## Versions, verified by installing

| package | version | note |
| --- | --- | --- |
| chromadb | 1.5.9 | |
| sentence-transformers | 6.1.0 | |
| embedding model | `BAAI/bge-small-en-v1.5` | **the exact name, now confirmed.** 384 dimensions, ~130 MB |

Two things that are easy to get wrong with this model family, both handled in
`embed.py`:

- **bge wants an instruction prefix on the query and not on the documents.**
  `Represent this sentence for searching relevant passages: ` goes in front of
  the query only. Skipping it costs real accuracy.
- **Chroma defaults to squared L2.** Embeddings are compared by direction, so
  the collection is created with `hnsw:space: cosine`.

## Does it work

cachetools at the pinned sha: **372 chunks indexed, about 45 s end to end on
CPU** including loading the model. The 3050's 4 GB is not a constraint; this
model is small enough that the CPU path is fine and no GPU work was needed.

Six queries, with the acceptable answers written down before running:

| query | relevant answer in top 3 |
| --- | --- |
| cache eviction | yes |
| least recently used eviction policy | yes, `LRUCache` at `__init__.py:287` is top 1 |
| expire items after a time to live | yes, `TLRUCache.ttu` is top 1 |
| decorator that memoizes a function | yes, `cached` at `__init__.py:738` is top 1 |
| hash the arguments to build a cache key | yes, `keys.hashkey` is top 1 |
| wait on a lock from several threads | yes |

**6 of 6**, by reading the results. A crude automated matcher scored it 5 of 6,
because it looked for class names and a method chunk does not contain the name
of its class — the "miss" was `TLRUCache.ttu`, which is the correct answer.
Worth recording because it is the same failure mode that broke the navigator's
gold set: the scoring harness being wrong, not the thing being scored.

Six queries is a smoke test. It is not an evaluation and no claim here should
be repeated as one.

## One change that did not help

The first version embedded raw source. On the single query "cache eviction"
the top 3 came back as `test_clear`, `cache_lock` and a test helper — every
function in cachetools mentions "cache", so the ranking looked close to
arbitrary. The obvious fix is to give the model the context the source text
does not carry, so `embedding_text()` prefixes the module path and the kind.

Measured across the six queries: **no difference, 6 of 6 either way.** The
single-query impression that motivated it was noise. It is kept, behind
`--raw` to turn it off, on the argument that a multi-repo index will need the
path to disambiguate — but it should not be described as an improvement,
because nothing here shows that it is.

## A bug the smoke test found

Chroma collection names must be 3 to 512 characters from `[a-zA-Z0-9._-]`,
starting and ending alphanumeric. A repo label of `ct` crashed the client, and
so would any `owner/name` label, because of the slash. `collection_name()` now
sanitises, with a parametrised test. Emma will be labelled with a slash, so
this would have surfaced later and less conveniently.

## What this says about Eval 2

- The CPU path is good enough for indexing a library this size, so the 4 GB of
  VRAM on laptop 1 is not the constraint for retrieval. It will matter for the
  3B model, not for the embeddings.
- Chunking by function already gives usable results with a small general
  purpose text model. A code-specific embedding model is worth trying, but it
  is not obviously required.
- The real work is the `Retriever` contract: `retrieve(test_id, k)` takes a
  test id, not a sentence. Turning a failing test into a query is the open
  question, and the navigator already produces a much better starting point
  than a hand-typed phrase.
- The top-k sweep over 2, 4 and 8 in the plan needs a gold set for retrieval,
  in the way `nav-gold-*.json` exists for navigation. That does not exist yet
  and is the first thing to build.
