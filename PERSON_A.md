# Person A: data and CI (laptop 3)

Read `README.md` first. This file is only your part.

**You own, end to end:** how raw CI test runs become clean, versioned, labeled data. That covers the repo itself, the GitHub Actions workflows, the parser, the run table, and later the baselines. If the data is wrong, every result downstream is wrong, so you are the owner of "can we trust the numbers".

**Laptop 3:** 16 GB RAM, 135 GB free disk, CPU and GPU unknown. Your work is mostly Git, Python and Actions, so model speed does not block you. Use the disk for run artifacts and the Chroma index later.

**Branch prefix:** `a/`. **Your reviewer:** B reviews your PRs. **You review:** B's PRs.

---

## 1. Setup checklist (do once, tick as you go)

- [ ] Install Python 3.12 and confirm: `python --version` shows 3.12.x
- [ ] Install Git and the GitHub CLI, then `gh auth login`
- [ ] Create the venv
  - Windows (PowerShell): `py -3.12 -m venv .venv` then `.venv\Scripts\Activate.ps1`
  - Linux or macOS: `python3.12 -m venv .venv` then `source .venv/bin/activate`
- [ ] `pip install pytest pytest-randomly pytest-repeat ruff pydantic pandas pyarrow`
- [ ] Find and send the team your laptop's CPU and GPU (Task Manager, Performance tab)
- [ ] Write the exact commands you used in `docs/eval1/setup-laptop3.md`. This feeds the root README

---

## 2. Eval 1 tasks (finish by Sunday night)

Do them in this order. Tasks A1 and A2 block B and C, so do them first.

### A1. Repo skeleton (target: Saturday evening, about 1 hour)

1. Create the public repo `flakeguard` on GitHub (owner and name: **TODO**, share them with B and C). Add an MIT `LICENSE`.
2. Add the layout from `README.md` section 4 (empty packages with `__init__.py`).
3. Add `pyproject.toml` (Python `>=3.12,<3.13`, dev dependencies above, a `[tool.ruff]` section) and `.python-version` containing `3.12`.
4. Commit `flakeguard/contracts.py` **exactly** as written in `README.md` section 3.
5. Add `.github/CODEOWNERS` and a PR template containing the PR checklist.
6. Add `.github/workflows/ci.yml`:

```yaml
name: ci
on:
  pull_request:
    branches: [develop, main]
  push:
    branches: [develop]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: pytest -q
```

   Add a trivial test (for example, import `contracts`) so `pytest` has something to run. **Verify** the action versions are current when you write this.
7. Create `develop` from `main`. Invite B and C as collaborators with write access.

**Done when:** a PR from a branch into `develop` shows the `ci` check running green, and B and C can clone and install.

### A2. Branch protection (about 15 minutes)

In the repo settings, protect `main` and `develop`: require a PR, require 1 approval, require the `ci` check, block force pushes. **Verify** the menu names.

**Done when:** you cannot push directly to `develop`.

### A3. `collect.yml` on cachetools (about 2 hours)

Goal: prove the collection loop works on a small, fast suite. Start with 10 runs.

```yaml
name: collect
on:
  workflow_dispatch:
    inputs:
      target:
        description: "Target repo name label"
        default: "cachetools"
jobs:
  run:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        run_id: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    steps:
      - uses: actions/checkout@v4
        with:
          repository: tkem/cachetools
          ref: 3c082c654c2804b9354e4b62dbd2994f1aac464d
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e . pytest pytest-randomly
      - name: Run tests
        run: |
          mkdir -p out
          pytest tests -q --randomly-seed=${{ matrix.run_id }} --junitxml=out/junit-${{ matrix.run_id }}.xml > out/log-${{ matrix.run_id }}.txt 2>&1 || true
      - uses: actions/upload-artifact@v4
        with:
          name: run-${{ matrix.run_id }}
          path: out/
```

The `|| true` is deliberate: a failing run must still upload its results. Run it with `gh workflow run collect.yml`, watch it, then `gh run download <run-id> -D artifacts/`.

**Done when:** you have 10 JUnit files and 10 logs from one workflow run.

**Note:** an injected-flakiness branch of cachetools is Eval 2 work. Keep injected changes on a separate branch, never on the original.

### A4. Parser to run table (about 2 hours)

Write `flakeguard/parser/junit.py`:
- Read a JUnit XML file with `xml.etree.ElementTree`.
- For each test case, produce a row with the `run_table` fields from `README.md` section 3 (take `seed` and `run_id` from the file name or an argument).
- Write the combined table to `data/run_table.parquet`.
- Add `flakeguard/parser/redact.py` with a stub `redact(text: str) -> str` that masks emails, phone-number-like strings and long token-like strings. It must run before any log is stored. A first version with a few regexes and a unit test is enough for Monday.
- Add unit tests in `tests/test_parser.py`, using one small JUnit file saved under `tests/data/`.

**Done when:** `python -m flakeguard.parser.junit artifacts/ data/run_table.parquet` prints a per-test pass rate summary, and `pytest` passes.

### A5. Charter, timeline, responsibility matrix (about 2 hours)

Create these in `docs/eval1/`. Draft from the plan document and let everyone edit.

- `charter.md`: one page. Problem, worked example, pipeline sentence, personas, research question, metrics, baselines, the substitutions and why.
- `timeline.md`: three phases that match Eval 1, 2 and 3, with the work packages from the plan (WP1-11). Eval 2 and 3 dates are unknown, so write them as TODO.
- `responsibility-matrix.md`: a table of work package by person (A, B, C), marking owner and reviewer.

**Done when:** B and C have each read and commented on all three.

### A6. Root README (about 1 hour, last)

Merge setup steps from `docs/eval1/setup-laptop3.md` and from B's and C's setup notes into the root `README.md`. Then ask someone to follow it from a clean folder on their laptop.

**Done when:** a teammate reproduces the setup using only the README.

### A7. Only if you hold the Emma local branch

Push the 28 local commits to a branch (for example `emma-accuracy-and-listening`) and share the commit SHA. Before making it public, check for secrets and decide which modules to exclude (WhatsApp code especially). If you do not hold it, ask whoever does.

### Stretch (only if everything above is done)

Scale `collect.yml` to 30 runs by extending the matrix. Add the injection branch plan to `docs/eval2/`.

---

## 3. Later phases (Eval 2 and 3), so you know where this goes

- `collect.yml` for Emma and for the synthetic project, 30-50 shuffled runs, plus isolated single-test reruns for failing tests.
- Labeler: `stable | flaky | real_fail` and the root cause, from natural flips, injected flakes and mutants (mutmut, limited to 1-2 modules).
- Baselines B1-B3: rerun-based, coverage-based (DeFlaker-style, check the method before citing it), and a scikit-learn classifier on run features.
- `triage.yml`, `quarantine-approve.yml`, `monitor.yml`.
- Data cards for every dataset (source, SHA, date, labeling method).
- Your phase-2 slice: **order_dep and shared_state**, end to end (reproducer, smell checks, prompts, evaluation, demo).

---

## 4. Commands you will use

```bash
git checkout develop && git pull
git checkout -b a/collect-workflow
git add -A && git commit -m "ci(collect): matrix of 10 shuffled runs"
git push -u origin a/collect-workflow
gh pr create --base develop --title "ci(collect): matrix of 10 shuffled runs" --body "How to run: gh workflow run collect.yml"
gh workflow run collect.yml
gh run list --limit 5
gh run watch <run-id>
gh run view <run-id> --log-failed
gh run download <run-id> -D artifacts/
```

Local test of pytest options before you put them in a workflow:
```bash
pytest tests -q --randomly-seed=3 --junitxml=out/junit-3.xml
pytest tests -q -p no:randomly          # fixed order, for comparison
```

---

## 5. Be able to explain (viva)

- Why runs are shuffled with a seed, and how a seed reproduces an order.
- Why the split is by test and by repo, never by run (leakage).
- What a flaky test is in your labels, and what is natural, injected and mutant data.
- Why `|| true` is in the collect step, and what `fail-fast: false` does.
- What the redaction step is for, and why it comes before storage.
- How the run table becomes the evidence bundle that C's prompts read.

---

## 6. Verify list (yours)

- Action versions in the workflows are current.
- Branch protection menu names and what is free on your account.
- cachetools still passes on Python 3.12 in Actions.
- Laptop 3's CPU and GPU.
- Whether Emma can be public.
