# FlakeGuard

[![ci](https://github.com/vidipt9090/FlakeGuard/actions/workflows/test.yml/badge.svg)](https://github.com/vidipt9090/FlakeGuard/actions/workflows/test.yml)
[![GitHub Actions Run](https://img.shields.io/badge/GitHub_Actions-Green_Build-success?logo=github)](https://github.com/vidipt9090/FlakeGuard/actions/workflows/test.yml)

> Detect and triage flaky tests using LLM-assisted analysis.

FlakeGuard collects shuffled test runs, detects instability statistically, retrieves relevant source code via semantic navigation, and asks a local LLM to explain the root cause — all without requiring a developer to reproduce the failure manually.

**CI Status & Workflow Run:** [GitHub Actions Test Workflow Run](https://github.com/vidipt9090/FlakeGuard/actions/workflows/test.yml)

**Eval 1 deadline:** Monday 2026-10-05. Full plan and diagrams are in the plan document.
<!-- test: quarantine-approve workflow verification -->


---

## Quick start (any laptop)

```bash
# 1. Clone
git clone https://github.com/vidipt9090/FlakeGuard.git
cd FlakeGuard

# 2. Virtual environment — Python 3.12 required
py -3.12 -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# 3. Install
pip install -e ".[dev]"

# 4. Verify
ruff check .
pytest -q
```

Expected: `All checks passed!` from ruff and all tests passing (30+ passing).

> **Gotcha (Windows):** If `Activate.ps1` is blocked, run once:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

## Repository layout

```
FlakeGuard/
├── .github/
│   ├── CODEOWNERS                        # code ownership per package
│   ├── pull_request_template.md          # PR checklist
│   └── workflows/
│       ├── cicd.yml                      # the delivery pipeline (see docs/cicd.md)
│       ├── ci.yml                        # lint + test on every PR
│       ├── test.yml                      # broader test run incl. baselines
│       └── collect.yml                   # 10-run shuffled matrix on cachetools
├── docs/
│   ├── cicd.md                           # testing → CI/CD: the transition
│   ├── knowledge-tree.md                 # the tree, its edges, the trace
│   ├── limitations.md
│   └── eval1/                            # charter, timeline, setup notes, results
├── flakeguard/
│   ├── contracts.py                      # FROZEN shared data types
│   ├── collector/                        # (A) CI data collection
│   ├── parser/                           # (A) JUnit XML → Parquet + redaction
│   ├── baselines/                        # (A) B1–B3 baseline classifiers
│   ├── navigator/                        # (B) AST + jedi code navigator
│   │   ├── ast_nav.py                    #     the navigator itself
│   │   ├── trace.py                      #     step-by-step instrumentation
│   │   └── knowledge_tree.py             #     the tree built from it
│   ├── retrieval/                        # (B) vector retrieval / Chroma
│   ├── cluster/                          # (B) test clustering
│   ├── llm/                              # (C) Ollama LLM adapter
│   ├── classify/prompts/                 # (C) prompt versions v1–v3
│   ├── evidence/                         # (C) evidence bundle builder
│   ├── eval/                             # (C) evaluation harness
│   └── app/                              # the dashboards
│       ├── api.py                        #     JSON API + static server (Starlette)
│       ├── dashboard.py                  #     Streamlit UI, 9 pages
│       ├── pages_nav.py                  #     its knowledge tree + trace pages
│       ├── pages_cicd.py                 #     its pipeline page
│       └── viz.py                        #     its chart tokens and loaders
├── frontend/                             # the React dashboard (the one to demo)
│   ├── src/
│   │   ├── App.tsx                       #     shell, rail, theme
│   │   ├── NavigatorView.tsx             #     the centrepiece: source + tree + replay
│   │   ├── TreeCanvas.tsx                #     the tree, growing in step with the trace
│   │   ├── SourcePane.tsx                #     the test, highlighted as the AST reads it
│   │   ├── TracePlayer.tsx               #     transport, phase raster, step detail
│   │   ├── tree.ts                       #     tidy-tree layout + replay maths
│   │   └── theme.css                     #     design tokens (dark + light)
│   └── package.json
├── synthetic/                            # (C) planted-flaky project + gold.json
├── scripts/                              # pipeline stages, runnable standalone
├── tests/                                # flakeguard's own test suite
├── pyproject.toml
├── .python-version                       # 3.12
└── LICENSE                               # MIT
```

---

## The dashboard

A React app served by a small Starlette API. Two commands:

```bash
# one-off: build the UI
cd frontend && npm install && npm run build && cd ..

# run it
python -m flakeguard.app.api            # http://127.0.0.1:8000
```

For UI work, run the Vite dev server alongside it — it proxies `/api` to the
Python process and hot-reloads:

```bash
python -m flakeguard.app.api            # terminal 1
cd frontend && npm run dev              # terminal 2 -> http://localhost:5173
```

Four views:

| View | What it shows |
| --- | --- |
| **Knowledge tree** | the centrepiece. The test's source on the left with each line highlighted as the AST walk reads it, the tree on the right growing one node per step, and a transport underneath. **Press play and watch the navigation happen.** |
| **Results** | detection scores with bootstrap CIs, and the false-quarantine caveat as part of the result rather than a footnote. |
| **Benchmark** | the 31 planted cases, their root causes, their real flip rates, and what the navigator reached for each. |
| **CI/CD** | the pipeline's stages grouped by which side of the gate they sit on, the gate's real verdict with every check and its reasoning, and the workflows read off disk. |

### The replay

The thing worth demonstrating. Every node appears on the step that actually
produced it — the navigator records which chunks each step added
(`TraceEvent.produced`), so this is the real sequence, not an animation
approximating one. On `cachetools::test_ttl`:

```
step 328  jedi_goto   TTLCache       -> adds TTLCache        (the test names it)
step 329  jedi_goto   Timer          -> adds Timer
step 416  jedi_infer  cache.timer    -> adds _Timer          (operator use: the TYPE is the target)
step 466  expand      hop 2          -> adds _TimedCache     (TTLCache's base class)
step 469  smell       time.monotonic -> adds the smell
```

18 of those 470 steps add a node, so the transport has **jump-to-next-discovery**
buttons and the scrub bar is ticked at each one.

**Live run** navigates a repository when you press the button — nothing is read
from `results/`. The repository box takes either a local path **or a repo URL**:

```
https://github.com/owner/project.git        → cloned, then navigated
../cachetools                               → used as-is
```

A URL is cloned shallow (`--depth 1 --single-branch --no-tags`) into
`.cache/repos/` and reused afterwards. **Find tests** then lists every test id
in it, with a filter box — click to select, double-click to navigate. On a
real project this is 800+ tests across 50+ files, so the filter is the point.

The clone is **parsed, never run**: `ast.parse` plus jedi's static resolution.
Nothing is imported, no `conftest.py` or `setup.py` executes, and the clone
directory never joins this process's `sys.path`. git is called with an argument
list (never a shell) with user input after `--`, and `GIT_TERMINAL_PROMPT=0` so
a private repo fails in seconds instead of hanging on a credential prompt.
`tests/test_repos.py` pins those properties, including that discovery cannot be
made to execute a planted file.

The Streamlit dashboard (`streamlit run flakeguard/app/dashboard.py`) is still
in the repo and still tested; the React UI is the one to demo.

### API

`flakeguard/app/api.py`, built on Starlette (already a dependency, so the web
UI adds no new Python package).

```
GET  /api/sets                      exported tree sets + per-case summaries
GET  /api/sets/{set}/tree?test_id=  one tree, its trace, and the test's source
POST /api/navigate                  run the navigator now  {repo, repo_name, test_id}
POST /api/discover                  clone if needed, list the test ids in a repo
GET  /api/cached                    repositories already cloned
GET  /api/pipeline                  gate verdict + the workflow files
GET  /api/results                   metrics, labels, navigator summaries
GET  /api/runs                      per-test flip rates
```

`tests/test_api.py` pins the fields the UI reads, because a renamed field here
breaks a chart there with no type error on either side.

## The knowledge tree and the trace

Full write-up: **[`docs/knowledge-tree.md`](docs/knowledge-tree.md)**.

`NavResult` is four flat lists, which loses how far from the test each thing
is. The knowledge tree puts that back — the root is the test, every other node
hangs under whatever reached it, and the edge names the mechanism:

```
TEST  tests/test_ttl.py::TTLCacheTest::test_ttl
|- [calls]           TTLCache  src/cachetools/__init__.py:451  score 13.00
|  `- [expands]      _TimedCache  src/cachetools/__init__.py:373  score 0.45
|- [calls]           Timer  tests/test_ttl.py:9  score 1.00
|- [infers]          _Timer  src/cachetools/__init__.py:376  score 2.00
`- [smells]          time.monotonic  src/cachetools/__init__.py:451
```

```python
from flakeguard.navigator.ast_nav import AstNavigator

nav = AstNavigator("../cachetools", repo="cachetools", sha="3c082c6")
explained = nav.explain("tests/test_ttl.py::TTLCacheTest::test_ttl")

print(explained.tree.render())       # the text tree above
print(explained.tree.stats())        # nodes, depth, edges by type
print(explained.trace.summary())     # ast names, jedi calls, hit rate, ms
print(explained.result)              # the unchanged NavResult
```

Tracing is off unless asked for, and `related()` is untouched — the
instrumented and contract paths are asserted to agree on every chunk.

```bash
# export a tree + trace per benchmark case (the pipeline does this on push)
python scripts/export_knowledge_trees.py --with-text

# and for a repo that is not ours
python scripts/export_knowledge_trees.py \
    --repo ../cachetools --repo-name cachetools --sha 3c082c6 \
    --gold docs/eval1/nav-gold.json --out results/cachetools --with-text
```

---

## CI/CD

Full reasoning: **[`docs/cicd.md`](docs/cicd.md)**. Pipeline:
`.github/workflows/cicd.yml`.

```
 static ─┐                                          ┌─> deploy
 build  ─┼─> test ─> navigate ──────────┬─> gate ───┼─> report ─┐
         │                              │           │           └─> release
         └────────> navigate-external ──┘           └───────────────┘

 └──────────── CI: does it work? ───────┘  ↑gate↑  └──── CD: ship it ────┘
```

The stage that makes it a delivery pipeline is **`gate`**. It reads the
artifacts the earlier stages uploaded and checks measured thresholds —
navigator resolution rate, jedi hit rate, tree depth, prompt F1 against the
baseline, benchmark size. `report` and `release` both `needs: [gate]`, so a
failed check does not warn: it makes them unreachable.

Every stage is also a plain command:

```bash
ruff check . && pytest -q                    # stages 1a, 2
(cd frontend && npm ci && npm run typecheck && npm run build)   # stage 1c
python scripts/validate_neutralization.py    # stage 3a
python scripts/run_navigator_eval.py
python scripts/export_knowledge_trees.py --with-text
python eval/run_baselines.py
python scripts/quality_gate.py               # stage 4 — the gate
python scripts/quality_gate.py --strict      #   warnings fail too
python scripts/build_static_report.py --out site   # stage 5 — the deliverable
```

The gate writes `results/pipeline_status.json`, which the dashboard's CI/CD
page reads — so a local gate run changes what the dashboard reports, and the
page never claims a verdict nobody produced.

> **Reproducibility note.** The navigator resolves names with jedi, and jedi
> resolves against what is *importable*. The same test id gave 3 chunks under
> jedi 0.20.0 and 1 chunk under 0.19.1 (which could not see `freezegun`), with
> no repository change between the runs. `jedi>=0.20.0` is pinned, and the
> `test` stage records `jedi --version` plus a full `pip freeze` beside the
> numbers.

---

## Who owns what

| Person | GitHub | Role | Laptop | Packages |
| --- | --- | --- | --- | --- |
| A (Vidipt) | @vidipt9090 | Data and CI | Laptop 3 — 16 GB RAM, 135 GB disk | `collector/`, `parser/`, `baselines/`, `.github/`, `docs/` |
| B (Samarth) | @sam2126 | Retrieval and navigation | Laptop 1 — AMD Ryzen 7 6800H, RTX 3050 4 GB, 15.2 GB RAM | `navigator/`, `retrieval/`, `cluster/` |
| C (Priyal) | @priyalkhullar | LLM and evaluation | Laptop 2 — Core Ultra 7, 32 GB RAM, Intel Arc GPU | `llm/`, `classify/`, `evidence/`, `eval/`, `synthetic/` |

Shared, built in phase 2 by root-cause family: `reproduce/`, `actions/`, `monitor/`, `app/`.

Review rotation: **A reviews B, B reviews C, C reviews A.**

---

## Git workflow

```
main        ← protected; only tagged milestones (eval1, eval2, eval3) land here
develop     ← protected integration branch; must always be green
a/<topic>   ← A's feature branches
b/<topic>   ← B's feature branches
c/<topic>   ← C's feature branches
```

**Daily loop:**

```bash
git checkout develop && git pull
git checkout -b a/my-feature       # use your prefix

# ...work...

ruff check . && pytest -q          # must pass locally first
git add -A
git commit -m "feat(parser): describe what and why"
git push -u origin a/my-feature
gh pr create --base develop --title "feat(parser): ..." --body "What, why, how to test."
```

**Commit message format:** `type(scope): summary`
Types: `feat`, `fix`, `docs`, `test`, `ci`, `refactor`

**PR rules:**
- Small — one work package or less
- Reviewer is the next person in rotation; nobody merges their own PR
- `ci.yml` must be green; squash merge
- Never commit secrets, tokens, `.env` files, or raw logs

**PR checklist (paste into every PR):**
```
- [ ] ruff check . and pytest -q pass locally
- [ ] New code has a test, or a note on why not
- [ ] No secrets, personal data or large files
- [ ] I can run the new thing with the command in the PR description
- [ ] README or docs updated if setup or commands changed
```

---

## Hardware & versions (verified)

### Laptop 1 — B (@sam2126)

| Item | Value |
| --- | --- |
| CPU | AMD Ryzen 7 6800H, 8 cores / 16 threads |
| GPU | **RTX 3050 Laptop GPU, 4 GB VRAM** (driver 592.27) |
| RAM | 15.2 GB |
| OS | Windows 11, build 26300 |
| Python | 3.12.2 |
| jedi | 0.20.0 |
| Ollama | 0.21.0 (installed, not needed until Eval 2) |
| Docker | 29.8.0, Compose v5.5.1 |

> **Note:** 4 GB VRAM fits a 3B model quantised to 4-bit (~2 GB). A 7B model spills to CPU.
> Plan retriever work around 3B on this laptop; leave the 7B comparison to Laptop 2.

### Laptop 2 — C (@priyalkhullar)

| Item | Value |
| --- | --- |
| CPU | Intel Core Ultra 7 |
| GPU | Intel Arc Graphics |
| RAM | 32 GB |
| Python | 3.12.10 |
| Ollama models | `llama3.2:3b` (~4.4 s/call CPU), `codellama:latest` (~10.6 s/call CPU) |

### Laptop 3 — A (@vidipt9090)

| Item | Value |
| --- | --- |
| CPU | TODO (check Task Manager → Performance → CPU) |
| GPU | TODO (check Task Manager → Performance → GPU) |
| RAM | 16 GB |
| Free disk | 135 GB |
| Python | 3.12.6 |
| Git | 2.47.0.windows.1 |
| GitHub CLI | 2.102.0 |

---

## Additional setup for B's tools (navigator)

```bash
# Clone cachetools as a SIBLING of FlakeGuard (not inside it)
cd ..
git clone https://github.com/tkem/cachetools.git
cd cachetools
git checkout 3c082c654c2804b9354e4b62dbd2994f1aac464d   # pinned SHA
cd ../FlakeGuard

# Run the navigator demo
python -m flakeguard.navigator.demo \
    "tests/test_ttl.py::TTLCacheTest::test_ttl" \
    --repo ../cachetools --repo-name cachetools --sha 3c082c6

# Score against the gold set
python -m flakeguard.navigator.evaluate \
    --repo ../cachetools --gold docs/eval1/nav-gold.json --markdown
```

> **Gotcha:** Clone cachetools as a *sibling* of FlakeGuard. If you clone it
> *inside*, its 337 test files get picked up by our `pytest` run.

## Additional setup for C's tools (LLM)

```bash
# Install Ollama from https://ollama.com and pull the models
ollama pull llama3.2:3b
ollama pull codellama:latest

# Extra Python deps for C's work
pip install ollama freezegun

# Run the prompt evaluation
python scripts/run_prompt_eval.py

# Run synthetic suite 20 times
python scripts/run_synthetic_20_times.py
```

## Embeddings / retrieval (Eval 2 only — do not install yet)

```bash
pip install chromadb sentence-transformers
pip install llama-index llama-index-llms-ollama \
    llama-index-embeddings-huggingface llama-index-vector-stores-chroma
```

> Package names above are on the verify list and have not been confirmed by
> installing. Do not quote them as settled until Eval 2.

---

## Collecting cachetools runs

```bash
# Trigger 10 shuffled runs (requires gh auth login)
gh workflow run collect.yml --repo vidipt9090/FlakeGuard

# Watch progress
gh run list --limit 5 --repo vidipt9090/FlakeGuard
gh run watch <run-id> --repo vidipt9090/FlakeGuard

# Download artifacts when done
gh run download <run-id> -D artifacts/ --repo vidipt9090/FlakeGuard

# Parse to Parquet
python -m flakeguard.parser.junit artifacts/ data/run_table.parquet
```

---

## Decisions that are frozen

| Item | Decision |
| --- | --- |
| Python | **3.12** on every machine and every workflow |
| Repo | One public monorepo `FlakeGuard`. MIT license |
| Targets | cachetools pinned to `3c082c654c2804b9354e4b62dbd2994f1aac464d`; Emma (SHA TBD); synthetic project in `synthetic/` |
| LLM | Ollama locally, temperature 0, JSON output validated with Pydantic |
| Verdicts | `flaky`, `real`, `uncertain` |
| Root causes | `order_dep`, `shared_state`, `timing`, `network`, `randomness`, `time_tz`, `filesystem`, `none` |
| Quarantine | v1 never quarantines on its own — a person approves every quarantine |

---

## contracts.py (frozen)

`flakeguard/contracts.py` defines the shared data types used across all packages. **Nobody changes it without all three agreeing.** A change needs a PR labelled `contract-change` and two approvals.

---

## Eval 1 documents

All in `docs/eval1/`:

| File | Description |
| --- | --- |
| `charter.md` | Problem, pipeline, personas, research question, metrics, baselines |
| `timeline.md` | WP1–WP19 across Eval 1/2/3 |
| `responsibility-matrix.md` | Owner/reviewer per work package |
| `setup-laptop1.md` | B's exact setup steps |
| `setup-laptop2.md` | C's exact setup steps |
| `setup-laptop3.md` | A's exact setup steps |
| `nav-results.md` | Navigator accuracy results on gold sets |
| `../knowledge-tree.md` | The knowledge tree, its edges, and the navigation trace |
| `../cicd.md` | Software testing → CI/CD: the transition and its reasoning |
| `sourcegraph-vs-navigator.md` | Sourcegraph evaluation and justification |
| `prompt-results.md` | Prompt v1–v3 comparison table |
| `prompt-findings.md` | Prompt findings and refactor check |
| `synthetic-notes.md` | Synthetic project notes |

## Planted-Test Benchmark Neutralization & Clock Freezing Choice

The synthetic benchmark in `synthetic/tests/` has been expanded to 31 neutralized test cases (`test_case_01` through `test_case_31`) spanning 5 root causes (`order_dep`, `shared_state`, `timing`, `randomness`, `time_tz`), 6 real failure cases (bugs in `synthetic/src/shop.py`), and 10 stable test cases.

- **Neutralization**: All test names and fixture references use neutral identifiers (`test_case_XX`), with zero comments or docstrings revealing root causes.
- **Labels**: Benchmark metadata is stored separately in `labels/labels.json`.
- **Clock Freezing for Time Cases**: To ensure time/timezone tests fail deterministically under test execution regardless of system execution time (e.g. running daytime vs night-time), `freezegun` (`@freeze_time`) is utilized in `test_case_19`, `test_case_20`, and `test_case_21` to freeze mock time to off-hours/night time (e.g. `23:30:00`, `02:00:00`). This guarantees test failure when validating time-of-day and business-hour logic.

---

## Not yet verified

- Laptop 3's CPU and GPU
- LlamaIndex package names for Ollama + HuggingFace embeddings + Chroma
- Whether the Emma branch can be public, and which modules to exclude
- Eval 2 and Eval 3 dates
- `gh` CLI installation on Laptop 1 (needed for scripted workflow in Eval 2)

