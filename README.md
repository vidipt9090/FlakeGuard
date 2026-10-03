# FlakeGuard

> Detect and triage flaky tests using LLM-assisted analysis.

FlakeGuard collects shuffled test runs, detects instability statistically, retrieves relevant source code via semantic navigation, and asks a local LLM to explain the root cause — all without requiring a developer to reproduce the failure manually.

**Eval 1 deadline:** Monday 2026-10-05. Full plan and diagrams are in the plan document.

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
│       ├── ci.yml                        # lint + test on every PR
│       └── collect.yml                   # 10-run shuffled matrix on cachetools
├── docs/eval1/                           # charter, timeline, setup notes, results
├── flakeguard/
│   ├── contracts.py                      # FROZEN shared data types
│   ├── collector/                        # (A) CI data collection
│   ├── parser/                           # (A) JUnit XML → Parquet + redaction
│   ├── baselines/                        # (A) B1–B3 baseline classifiers
│   ├── navigator/                        # (B) AST + jedi code navigator
│   ├── retrieval/                        # (B) vector retrieval / Chroma
│   ├── cluster/                          # (B) test clustering
│   ├── llm/                              # (C) Ollama LLM adapter
│   ├── classify/prompts/                 # (C) prompt versions v1–v3
│   ├── evidence/                         # (C) evidence bundle builder
│   └── eval/                             # (C) evaluation harness
├── synthetic/                            # (C) planted-flaky project + gold.json
├── scripts/                              # one-off helper scripts
├── tests/                                # flakeguard's own test suite
├── pyproject.toml
├── .python-version                       # 3.12
└── LICENSE                               # MIT
```

---

## Who owns what

| Person | GitHub | Laptop | Packages |
| --- | --- | --- | --- |
| A (Vidip) | @vidipt9090 | Laptop 3 — 16 GB RAM, 135 GB disk | `collector/`, `parser/`, `baselines/`, `.github/`, `docs/` |
| B (Sam) | @sam2126 | Laptop 1 — AMD Ryzen 7 6800H, RTX 3050 4 GB, 15.2 GB RAM | `navigator/`, `retrieval/`, `cluster/` |
| C (Priyal) | @priyalkhullar | Laptop 2 — Core Ultra 7, 32 GB RAM, Intel Arc GPU | `llm/`, `classify/`, `evidence/`, `eval/`, `synthetic/` |

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
| `sourcegraph-vs-navigator.md` | Sourcegraph evaluation and justification |
| `prompt-results.md` | Prompt v1–v3 comparison table |
| `prompt-findings.md` | Prompt findings and refactor check |
| `synthetic-notes.md` | Synthetic project notes |

---

## Not yet verified

- Laptop 3's CPU and GPU
- LlamaIndex package names for Ollama + HuggingFace embeddings + Chroma
- Whether the Emma branch can be public, and which modules to exclude
- Eval 2 and Eval 3 dates
- `gh` CLI installation on Laptop 1 (needed for scripted workflow in Eval 2)
