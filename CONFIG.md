# FlakeGuard System Configuration & Reproducibility Pinning

This document pins all environment configurations, dependency locks, model tags, random seeds, and commit SHAs required to reproduce FlakeGuard's experimental evaluation results from scratch.

---

## Environment & Runtime Pinning

| Component | Pinned Version / Value | Notes |
| :--- | :--- | :--- |
| **Python** | `3.12.10` | Enforced across all local setups and GitHub Actions CI (`.python-version`) |
| **Dependencies** | [`requirements.lock`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/requirements.lock) | Pinned versions for `pytest`, `pytest-randomly`, `jedi`, `pandas`, `ollama`, `freezegun`, `pydantic` |
| **Evaluated Commit SHA** | `8b53881d2cc0dd7ba8b836389848694798b513d3` | SHA of repository checkout at evaluation time |
| **OS Environment** | Windows 11 / Ubuntu 22.04 LTS (CI) | Execution verified on both Windows PowerShell and Linux runner |

---

## Ollama Model Pins

| Model Tag | Quantization / Family | Purpose |
| :--- | :--- | :--- |
| `llama3.2:3b` | `Q4_K_M` (3.2B parameters) | Primary local LLM evaluated across prompt versions `v1`, `v2`, `v3` |
| `codellama:latest` | `Q4_0` (7B parameters) | Secondary comparison model for code navigation and triage |

---

## Random Seed Schedule

| Component | Fixed Seed Schedule | Description |
| :--- | :--- | :--- |
| **Pytest Suite Shuffling** | `--randomly-seed=1..20` | Fixed seed integer for each of the 20 shuffled benchmark runs (`run_id = 1` to `20`) |
| **Ollama Temperature & Seed** | `temperature = 0.0`, `seed = 42` | Deterministic generation options passed to `ollama.generate` |
| **Bootstrap Confidence Intervals** | `n_bootstraps = 1000`, `seed = 42` | Non-parametric bootstrap resampling random seed in `eval/metrics.py` |

---

## Full Reproduction Pipeline

To regenerate all results and metric tables from scratch:

```powershell
python run_eval.py
```

This single command executes the complete pipeline end-to-end:
1. `scripts/validate_neutralization.py` — Validates zero root-cause leakage in test files.
2. `scripts/run_benchmark_runs.py` — Generates 20 shuffled runs $\rightarrow$ [`results/runs.csv`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/results/runs.csv).
3. `eval/run_baselines.py` — Computes rerun baseline metrics $\rightarrow$ [`results/baseline_metrics.csv`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/results/baseline_metrics.csv).
4. `llm/run_prompts.py` — Evaluates LLM prompts `v1`, `v2`, `v3` on Ollama $\rightarrow$ [`results/llm_metrics.csv`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/results/llm_metrics.csv) & [`results/llm_raw/`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/results/llm_raw/).
5. `analysis/failure_log.py` — Logs incorrect predictions $\rightarrow$ [`results/failure_log.csv`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/results/failure_log.csv).
6. `scripts/run_navigator_eval.py` — Evaluates AST call graph navigator $\rightarrow$ [`results/navigation.csv`](file:///c:/Users/khull/Desktop/IDT/FlakeGuard/results/navigation.csv).
