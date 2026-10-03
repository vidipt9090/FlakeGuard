# flakeguard: team execution guide (shared)

Read this file first, then your own file: `PERSON_A.md`, `PERSON_B.md` or `PERSON_C.md`.

Last updated: 2026-10-03. Eval 1 is on Monday 2026-10-05. Anything marked **TODO** or **verify** is not confirmed yet. Do not treat it as settled.

The full plan, with diagrams, is in the plan document (section numbers below refer to it).

---

## 1. Who does what

| Person | Laptop | Role | Owns these packages | Reviews PRs from |
| --- | --- | --- | --- | --- |
| A: Name TODO | Laptop 3 (16 GB RAM, 135 GB free disk; CPU and GPU unknown) | Data and CI | `collector/`, `parser/`, `baselines/`, `.github/`, `docs/` | B |
| B: Name TODO | Laptop 1 (RTX 3050, about 12 GB RAM free) | Retrieval and navigation | `navigator/`, `retrieval/`, `cluster/` | C |
| C: Name TODO | Laptop 2 (Core Ultra 7, 32 GB RAM) | LLM and evaluation | `llm/`, `classify/`, `evidence/`, `eval/`, `synthetic/` | A |

Shared, built in phase 2 by root-cause family: `reproduce/`, `actions/`, `monitor/`, `app/`.

Review rotation is A reviews B, B reviews C, C reviews A. Whoever owns a laptop runs the part that fits it.

**Why this split also matters for marks:** individual contribution and understanding are scored at every eval (C5, C10, C15). Each person must be able to explain their part from raw data to output, and run the whole pipeline on their own laptop.

---

## 2. Decisions that are frozen

| Item | Decision |
| --- | --- |
| Python | **3.12** on every machine and every workflow. Pin in `.python-version`, `pyproject.toml` and `actions/setup-python`. |
| Repo | One public monorepo named `flakeguard`. Owner and name: **TODO**. MIT license. |
| Targets | Emma (branch `emma-accuracy-and-listening`, SHA **TODO** after it is pushed). cachetools, pinned to `3c082c654c2804b9354e4b62dbd2994f1aac464d` (MIT, 337 tests). The synthetic project in `synthetic/`. |
| LLM | Ollama locally, temperature 0, JSON output validated with Pydantic. Model tags: **TODO verify** in the Ollama library. |
| Verdicts | `flaky`, `real`, `uncertain` |
| Root causes | `order_dep`, `shared_state`, `timing`, `network`, `randomness`, `time_tz`, `filesystem`, `none` |
| Quarantine | Version 1 never quarantines on its own. A person approves every quarantine. |
| Dev tools | `pytest`, `pytest-randomly`, `ruff`, `pydantic` |

Measured in a sandbox on 2026-10-03 (Python 3.13, not 3.12): cachetools has 337 tests, about 4.4 s per run, and passed 15 of 15 random-order runs. Re-measure on 3.12 on your own laptop.

---

## 3. Contracts (frozen)

Person A commits these in `flakeguard/contracts.py` as the very first change. **Nobody changes them without all three agreeing.** A change needs a PR labeled `contract-change` and two approvals.

```python
# flakeguard/contracts.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Chunk:
    chunk_id: str        # "<repo>@<sha>:<path>:<start>-<end>"
    path: str
    start_line: int
    end_line: int
    kind: str            # "function" | "class" | "test" | "fixture" | "log"
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class NavResult:
    test_id: str                                   # "tests/test_x.py::TestA::test_b"
    code_under_test: list[Chunk] = field(default_factory=list)
    fixtures: list[Chunk] = field(default_factory=list)
    shared_state: list[Chunk] = field(default_factory=list)  # module-level mutable globals touched
    smells: list[str] = field(default_factory=list)          # e.g. "time.sleep", "random.random"


class LLMProvider(Protocol):
    def generate(self, prompt: str, schema: dict) -> dict: ...


class Retriever(Protocol):
    def retrieve(self, test_id: str, k: int) -> list[Chunk]: ...


class Navigator(Protocol):
    def related(self, test_id: str) -> NavResult: ...
```

### Data schemas

**`run_table`** (Parquet, one row per test per run):
`repo, sha, run_id, test_id, outcome, duration_s, order_index, seed, py_version, log_path`

**`labels`** (CSV):
`test_id, stability, label, root_cause, source`
where `label` is `stable | flaky | real_fail` and `source` is `natural | injected | mutant`.

**LLM output** (validated JSON):

```json
{
  "verdict": "flaky",
  "root_cause": "shared_state",
  "confidence": 0.8,
  "evidence": [{"id": "E3", "type": "static", "strength": "strong"}],
  "explanation": "...",
  "fix_hint": "..."
}
```

Every `evidence.id` must exist in the evidence bundle. The reproduction result is attached by flakeguard after the LLM call, not produced by the LLM.

---

## 4. Repo layout

```
flakeguard/
  .github/workflows/   ci.yml, collect.yml, (later) triage.yml, eval.yml, monitor.yml
  .github/CODEOWNERS
  docs/                eval1/, eval2/, eval3/
  flakeguard/
    contracts.py
    collector/  parser/  evidence/  navigator/  retrieval/
    llm/  classify/  cluster/  baselines/  reproduce/
    actions/  eval/  monitor/  app/
  synthetic/           planted flaky and real-failure project, with gold.json
  tests/               tests for flakeguard itself
  pyproject.toml  .python-version  README.md  LICENSE
```

---

## 5. Git workflow (everyone follows this)

**Branches**
- `main`: protected. Only tagged milestones (`eval1`, `eval2`, `eval3`) are merged here, by PR.
- `develop`: protected integration branch. It must always run. Merges only by PR with CI green.
- Feature branches: `a/<topic>`, `b/<topic>`, `c/<topic>`. Branch from `develop`.

**Daily loop**
```bash
git clone https://github.com/<OWNER>/flakeguard.git      # once
git checkout develop && git pull
git checkout -b b/navigator-v0
# ...work...
ruff check . && pytest -q                                 # must pass locally first
git add -A
git commit -m "feat(navigator): resolve code under test with jedi"
git push -u origin b/navigator-v0
gh pr create --base develop --title "feat(navigator): resolve code under test" --body "What and why. How to test."
```

**Commit messages:** `type(scope): summary`, with types `feat`, `fix`, `docs`, `test`, `ci`, `refactor`. Your commits and PRs are your contribution evidence, so commit under your own account, in small pieces, often.

**PR rules**
1. Small. One work package or less. Under about 400 changed lines where you can.
2. Reviewer is the person next in the rotation. Nobody merges their own PR.
3. `ci.yml` must be green. Squash merge.
4. Keep `develop` runnable. If you break it, fix it first.
5. Never commit secrets, tokens, `.env` files or raw logs from Emma. Redaction happens in `parser/` before anything is stored.

**PR checklist (paste in every PR)**
- [ ] `ruff check .` and `pytest -q` pass locally
- [ ] New code has a test, or a note on why not
- [ ] No secrets, personal data or large files
- [ ] I can run the new thing with the command written in the PR description
- [ ] README or docs updated if setup or commands changed

**`CODEOWNERS`** (person A creates it; replace the handles with your GitHub usernames):
```
/flakeguard/collector/     @A-handle
/flakeguard/parser/        @A-handle
/flakeguard/baselines/     @A-handle
/.github/                  @A-handle
/flakeguard/navigator/     @B-handle
/flakeguard/retrieval/     @B-handle
/flakeguard/cluster/       @B-handle
/flakeguard/llm/           @C-handle
/flakeguard/classify/      @C-handle
/flakeguard/evidence/      @C-handle
/flakeguard/eval/          @C-handle
/synthetic/                @C-handle
/flakeguard/contracts.py   @A-handle @B-handle @C-handle
```

**Branch protection (person A, Settings, Branches)** for `main` and `develop`: require a pull request, require 1 approval, require the `ci` status check, block force pushes. These are available on public repos. **Verify** the exact menu names on your GitHub account.

---

## 6. GitHub Actions in this repo

- Workflows live in `.github/workflows/*.yml`.
- Manual run: `gh workflow run collect.yml -f target=cachetools`
- Watch: `gh run list --limit 5`, then `gh run watch <run-id>`
- Logs: `gh run view <run-id> --log-failed`
- Artifacts: `gh run download <run-id> -D artifacts/`
- Never put secrets in workflow files. Use the built-in `GITHUB_TOKEN` for PR comments.
- Actions is free for public repos. Keep matrices small while testing, then scale up.

---

## 7. Eval 1 timeline (Monday 2026-10-05)

| When | A | B | C |
| --- | --- | --- | --- |
| Sat evening | Repo skeleton, `contracts.py`, `ci.yml`, protection, invite B and C | Environment setup per README. Start the Sourcegraph check | Environment setup. Start the synthetic project |
| Sunday morning | `collect.yml` on cachetools, 10 runs | Navigator v0 | LLM adapter, 5 planted tests ready |
| Sunday afternoon | Parser to run table. Charter, timeline, matrix drafts | Gold set and navigation measure | Prompts v1-v3 run, results table |
| Sunday evening | Root README merged from everyone's setup notes | Demo script, justification note | Findings note, refactor prompt check |
| Sunday night | **Everyone:** merge to `develop`, rehearse the demo end to end, fix breakages | | |
| Monday | Present. Each person demos their own part and answers questions on it | | |

**Cut order if you run out of time:** embeddings smoke test, then the 30-run collection (10 is enough), then the second model in the prompt table. Never cut: charter, timeline, matrix, the navigator demo, the prompt comparison, and the README.

---

## 8. What the team shows on Monday (maps to the Eval 1 rubric)

| Rubric line (weight) | Shown by | Evidence |
| --- | --- | --- |
| Synopsis, problem definition (5%) | A leads, all review | Charter, timeline, responsibility matrix in `docs/eval1/` |
| Prompt engineering (5%) | C | Prompt v1-v3 files and the comparison table |
| Source graph and semantic navigation (10%) | B | Navigator demo, gold-set measure, Sourcegraph justification |
| Tool configuration (5%) | Everyone | Each person's setup checklist ticked and reproducible |
| Documentation (5%) | A leads, all contribute | Root `README.md` that a stranger can follow |

---

## 9. Not yet verified. Check before relying on it

- Free self-hosting of Sourcegraph (B tests it, time-boxed).
- Sweep.dev and Codium/Qodo status (needed from Eval 2, not Monday).
- Ollama model tags and sizes, and whether a 7B model runs acceptably on laptop 2.
- Laptop 3's CPU and GPU.
- Exact package names for the LlamaIndex Ollama, HuggingFace-embedding and Chroma integrations. Confirm by installing them.
- Whether the Emma branch can be public, and which modules to exclude.
- Eval 2 and Eval 3 dates.
