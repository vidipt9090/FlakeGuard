# From software testing to a CI/CD pipeline

Author: B. Date: 2026-10-10. Pipeline: `.github/workflows/cicd.yml`.

## The distinction this document is about

We already had continuous integration. `ci.yml` ran `ruff` and `pytest` on
every pull request, and `test.yml` added the baselines and the navigator
evaluation. That is a useful thing to have and it is not a delivery pipeline.

The difference is not the number of test jobs. It is three things:

1. **Ordered stages that hand each other artifacts.** CI can be a list of
   commands. Delivery has to ship *the thing that was tested*, which means the
   build happens once and is carried forward, not rebuilt at the end.
2. **A gate.** Something has to decide whether this build is good enough to
   release, using measurements rather than "did the process exit 0".
3. **An actual delivery.** Something a person outside the team can open, and a
   release that carries the evidence it passed on.

`cicd.yml` has all three. This document is the reasoning, so the choices can
be defended rather than just pointed at.

---

## The shape

```
 static ─┐                                          ┌─> deploy
 build  ─┼─> test ─> navigate ──────────┬─> gate ───┼─> report ─┐
         │                              │           │           └─> release
         └────────> navigate-external ──┘           └───────────────┘

 └──────────── CI: does it work? ───────┘  ↑gate↑  └──── CD: ship it ────┘
```

| Stage | Job | What it proves |
| --- | --- | --- |
| 1a | `static` | `ruff` over the whole tree |
| 1b | `build` | sdist + wheel build, metadata valid, uploaded once |
| 2 | `test` | `pytest` with coverage; records the resolver environment |
| 3a | `navigate` | neutralisation holds, navigator resolves, trees export |
| 3b | `navigate-external` | the navigator works on a repo that is not ours |
| **4** | **`gate`** | **measured thresholds — blocks everything downstream** |
| 5 | `report` | static HTML built from the gated bundle; runs on every trigger |
| 5b | `deploy` | publishes it to GitHub Pages (develop / main only) |
| 6 | `release` | tagged release carrying the build *and* its evidence |

Promotion rules:

- a **pull request** runs stages 1-5: it builds the report but does not deploy it
- a push to **develop** or **main** additionally runs `deploy`
- a **tag** (`v*`, `eval*`) additionally cuts a release

`deploy` is a job of its own rather than a step inside `report`, and that is
not cosmetic: a declared `environment:` is claimed when the job *starts*, and
the Pages environment is branch-protected by default. Declaring it on `report`
would have blocked every pull-request run of the pipeline.

---

## Why each design decision

### The build happens once, in stage 1b

A release job that runs `python -m build` has shipped a *rebuild* of the
source, not the artifact the tests ran against. They are usually identical and
the one time they are not is the one time it matters. So `build` uploads
`dist/` and `release` downloads it.

### `test` records the jedi version and a full `pip freeze`

This came out of a real incident while building these changes. The navigator
resolves names with jedi, and **jedi resolves against what is importable**.
Running the same navigator evaluation under two interpreters on the same
machine gave different answers:

| | jedi 0.20.0, freezegun installed | jedi 0.19.1, freezegun missing |
| --- | --- | --- |
| `test_case_19` code under test | 3 chunks | 1 chunk |
| `test_case_19` shared state | 17 | 8 |

Nothing in the repository changed between those two runs.

That investigation later found a navigator bug underneath it: a virtualenv
sits inside the repository root, so `_is_within()` was counting every
installed package as code under test — on one case, 11 of 20 chunks were
`freezegun` internals. See the correction in `docs/eval1/nav-results.md`.
With that fixed the two interpreters agree, which is the point: the version
recording is what made an unexplainable difference explainable at all, and
it stays for exactly that reason.

### Neutralisation is checked before anything is measured

`scripts/validate_neutralization.py` runs first in the `navigate` stage. A
planted test case whose name gives away its root cause measures the label, not
the model, and every number computed afterwards would be inflated by it. A
leak has to fail the stage before it can contaminate a result.

### `navigate-external` is a pipeline stage, not an experiment

The navigator was tuned on cachetools. Scoring it on cachetools measures fit.
So the pipeline checks out `tkem/cachetools` at a pinned SHA
(`3c082c654c...`, a frozen decision) and scores against a hand-labelled gold
set, every run. Generalisation that is only ever measured once is a claim;
measured on every push, it is a regression test.

The SHA is pinned because a floating `main` would silently change what the
gold set refers to.

### The gate is the whole point

`scripts/quality_gate.py` is the boundary. It reads the artifacts the earlier
stages uploaded and checks measured thresholds:

| Check | Threshold | Why there |
| --- | --- | --- |
| navigator resolution rate | ≥ 0.95 | measured 1.00 on 31 cases. Below this, test ids have stopped resolving and the evidence bundle is silently empty |
| jedi hit rate | ≥ 0.80 | 1.00 synthetic, 0.90 cachetools. A collapse means the environment moved under us |
| mean tree size | ≥ 3 nodes | measured 12.4. A one-node tree is a test with no context |
| trees reaching hop 2 | ≥ 1 | if nothing reaches a second hop, the expansion pass has stopped working |
| navigation latency | ≤ 5000 ms | measured max 1.0 s synthetic, 1.6 s cachetools; a live demo cannot afford more |
| external resolution rate | ≥ 0.90 | 10/10 gold cases resolve on cachetools at the pinned SHA |
| external jedi hit rate | ≥ 0.75 | measured 0.90. Lower than synthetic because a container library resolves a lot of stdlib; a collapse means `jedi.infer` broke |
| external trees reach hop 2 | ≥ 8 trees | all 10 do. cachetools' API *is* its class hierarchy, so this is the real check that the expansion hop works — the synthetic set is too flat to notice |
| best prompt F1 | ≥ 0.70 | the charter's target. v3 measures 0.833 |
| parse failures, best prompt | ≤ 0 | v3 parses all 31 cleanly; any failure means the JSON contract with the model broke |
| LLM beats the baseline | strict | if the rerun baseline wins, the LLM is not earning its cost |
| benchmark size | ≥ 31 cases | shrinking the benchmark would make every rate above look better than it is |
| root-cause coverage | ≥ 5 families | fewer means a whole failure class left the benchmark |
| false quarantine rate | ≤ 0.10 | **warns, does not block — see below** |

**Thresholds sit below what we measure, deliberately.** The gate is there to
catch a regression, not to fence in today's result. A gate set at the current
number fails on noise and gets disabled, which is worse than no gate.

A failing check means `gate` exits non-zero, and `report` and `release` both
`needs: [gate]`, so they never start. That is the enforcement: not a warning
in a log, an unreachable job.

### The one check that warns instead of blocking, and why

`false_quarantine_rate` is **1.00** for all three prompt versions. The metric
is `(real failures labelled flaky) / (total real failures)`, and the benchmark
has six real bugs, so the best prompt calls **every real bug flaky**. The
rerun baseline's rate is 0.00.

This is not a measurement error; it is the direct cost of recall being 1.00.
The prompt reaches "catches every flake" by calling almost everything flaky.
Reporting F1 0.833 without this number beside it is reporting half the result,
so the dashboard and the static report both show it as a caveat on the results
page rather than a footnote.

It warns rather than blocks for one reason, and it is a frozen project
decision rather than convenience: **v1 never quarantines on its own — a person
approves every quarantine.** With a human in that loop, a false-quarantine
*rate* is a model-quality signal, not a shipped risk. If the quarantine ever
becomes automatic, this check has to become blocking on the same commit.

`--strict` makes warnings fail, and `workflow_dispatch` exposes it as a
checkbox, so the stricter gate can be run on demand without editing the
pipeline.

### The report is the deployment

`scripts/build_static_report.py` turns the gated `results/` bundle into one
self-contained HTML file with no runtime: inline SVG charts, no JavaScript, no
Python process. It deploys to GitHub Pages from `develop` and `main`.

The Streamlit dashboard remains the interactive view — it can re-run the
navigator live, which a static page cannot. The static report is the one that
can be linked to.

Anything missing from the bundle is rendered as *missing*, not omitted. A
report that hides a gap is worse than no report.

### The release carries its evidence

The `release` job attaches both `dist/*` and
`flakeguard-results-<tag>.tar.gz`. A release carrying only a wheel is a claim.
One carrying the bundle it passed the gate on can be checked.

### Operational details

- **`concurrency`** cancels superseded runs per ref, so a quick second push
  does not pay for the first run twice.
- **`permissions: contents: read`** at the top, widened per job only where a
  job genuinely publishes (`pages: write` on `report`, `contents: write` on
  `release`). Least privilege by default.
- **`fail-fast: false`** on the test matrix: one Python version failing should
  not hide whether the others do.
- **`cache: pip`** on every `setup-python`.

---

## Running the pipeline locally

Every stage is a command, on purpose — nothing important only works inside
GitHub Actions.

```bash
# stage 1a, 2 — static analysis and tests
ruff check .
pytest -q

# stage 3a — navigate our own benchmark, export trees and traces
python scripts/validate_neutralization.py
python scripts/run_navigator_eval.py
python scripts/export_knowledge_trees.py --with-text
python eval/run_baselines.py

# stage 3b — navigate a repo that is not ours (needs ../cachetools)
python scripts/export_knowledge_trees.py \
    --repo ../cachetools --repo-name cachetools --sha 3c082c6 \
    --gold docs/eval1/nav-gold.json --out results/cachetools --with-text

# stage 4 — the gate
python scripts/quality_gate.py            # warnings allowed
python scripts/quality_gate.py --strict    # warnings fail

# stage 5 — the deliverable
python scripts/build_static_report.py --out site
```

The gate writes `results/pipeline_status.json`, which is what the dashboard's
**🚀 CI/CD Pipeline** page reads — so a local gate run changes what the
dashboard shows, and the page is never claiming a verdict nobody produced.

---

## What is deliberately still missing

Being straight about the edges of this:

- **No deployment environment with a rollback.** There is no running service
  to roll back to. Pages is a static deploy; the previous version is the
  previous commit.
- **No signed artifacts or provenance attestation.** Reasonable for coursework,
  not for a real supply chain.
- **The prompt evaluation does not run in CI.** It needs a local Ollama, so
  `llm_metrics.csv` is produced on Laptop 2 and committed. The gate reads the
  committed file and reports it as a warning when absent. A self-hosted runner
  with Ollama would close this.
- **Coverage floor is 60%**, against 68% measured. It is set below where we are so it
  catches a collapse rather than blocking work, and it should ratchet up.
- **Single Python version.** The matrix exists but has one entry, because
  3.12 is a frozen decision across all three machines.
