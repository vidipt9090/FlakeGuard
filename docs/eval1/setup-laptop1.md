# Laptop 1 setup (person B, retrieval and navigation)

Author: B. Date: 2026-10-03. Everything below was actually run, not copied from
the plan. Hand this to A for the root README (work package A6).

## Hardware, verified

Two items on B's verify list are now settled.

| item | plan said | measured |
| --- | --- | --- |
| GPU | RTX 3050, "4 GB or 6 GB, check in Task Manager" | **RTX 3050 Laptop GPU, 4096 MiB (4 GB)**, driver 592.27 |
| CPU | unknown | AMD Ryzen 7 6800H, 8 cores / 16 threads |
| RAM | "about 12 GB free" | 15.2 GB total |
| OS | - | Windows 11, build 26300 |

4 GB of VRAM is the binding constraint for Eval 2: a 3B model quantized to 4
bits (about 2 GB) fits on the GPU with room for context. A 7B model will spill
to system RAM and run on the CPU. Plan the retriever work around a 3B model on
this laptop and leave the 7B comparison to laptop 2.

## Versions installed

| tool | version |
| --- | --- |
| Python | 3.12.2 |
| jedi | 0.20.0 |
| pytest | 9.1.1 |
| pydantic | 2.13.5 |
| ruff | 0.16.10 |
| git | 2.51.0.windows.1 |
| Docker | 29.8.0, Compose v5.5.1 |
| Ollama | 0.21.0 (installed, not needed before Eval 2) |

GitHub CLI is **not** installed on this laptop. Plain `git push` works; PRs were
opened in the browser. Install `gh` before Eval 2 if we want the scripted flow
in the team README.

## Commands, in order

```bash
# 1. the repo, on the integration branch
git clone https://github.com/vidipt9090/FlakeGuard.git
cd FlakeGuard
git checkout develop
git checkout -b b/navigator-v0

# 2. virtual environment (Windows; .venv/ is already gitignored)
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1

# 3. dependencies
pip install pytest pytest-randomly pytest-repeat ruff pydantic jedi
pip install -e ".[dev]"

# 4. the navigation target, pinned to the sha frozen in the root README.
#    Clone it NEXT TO FlakeGuard, not inside it, so it can never be committed.
cd ..
git clone https://github.com/tkem/cachetools.git
cd cachetools
git checkout 3c082c654c2804b9354e4b62dbd2994f1aac464d   # v7.2.0
cd ../FlakeGuard

# 5. check it all works
ruff check .
pytest -q
```

Expected result: `All checks passed!` and 34 passed.

## A deviation from PERSON_B.md, and why

The setup list in `PERSON_B.md` also asks for `chromadb`,
`sentence-transformers` and the LlamaIndex integrations. Those were **not**
installed. They pull in PyTorch, roughly 2.5 GB, and they are only needed for
B5, the embeddings smoke test, which is first on the cut list in the root
README. B1 to B4 do not import them. Install them when the Eval 2 retriever
work actually starts:

```bash
pip install chromadb sentence-transformers
pip install llama-index llama-index-llms-ollama \
    llama-index-embeddings-huggingface llama-index-vector-stores-chroma
```

The LlamaIndex package names are still on the verify list. They have not been
confirmed by installing, so do not quote them as settled.

## Run the navigator

```bash
# demo on the pinned cachetools checkout
python -m flakeguard.navigator.demo \
    "tests/test_ttl.py::TTLCacheTest::test_ttl" \
    --repo ../cachetools --repo-name cachetools --sha 3c082c6

# add --preview 5 to print the first 5 lines of each chunk
# score it against the hand-written gold set
python -m flakeguard.navigator.evaluate \
    --repo ../cachetools --gold docs/eval1/nav-gold.json --markdown
```

The demo exits 1 when nothing was found, so it can be used in a script.

## Sourcegraph

Tried and running on this laptop; see `sourcegraph-vs-navigator.md` for the
full result and the resource numbers. One gotcha worth repeating here because
it wastes ten minutes: **there is no `latest` tag** for `sourcegraph/server`.
Name a version, for example `6.10.3349`.

## Gotchas for whoever repeats this

1. Clone cachetools as a **sibling** of `FlakeGuard`. Inside it, the 337 test
   files get picked up by our own `pytest` run.
2. `tests/data/navsample` contains files named `test_*.py` that must not be
   collected as our tests. `norecursedirs = ["tests/data"]` in `pyproject.toml`
   handles it; do not remove that line.
3. `pytest-randomly` is installed, so local test order changes every run. That
   is deliberate. Use `-p no:randomly` to compare a fixed order.
