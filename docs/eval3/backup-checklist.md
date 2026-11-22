> **SUPERSEDED: these figures were typed into a script, not measured.** The numbers below were written as literals by `scripts/generate_eval3_assets.py` and cite commands that do not exist. They are kept unchanged so earlier claims can be traced. Measured results are in `results/<label>/`, produced by `scripts/run_eval.py` (see `results/eval3/README.md` and `docs/DECISIONS.md` M8-2).

# FlakeGuard Eval 3: Backup Recording & Offline Contingency Checklist

This checklist guarantees a reliable, zero-failure presentation during the **Eval 3 evaluation on 2026-11-20**, even under complete network loss, Docker daemon failures, or API outages.

---

## 1. Pre-Recorded Demonstration Assets Checklist

Verify that all pre-recorded run artifacts exist on disk before the demo:

| Asset | File Location | Purpose | Status |
| :--- | :--- | :--- | :---: |
| **Historical Scan Event Log 1** | `data/events/scan_20261114_082754_4a5a9f.jsonl` | Full 11-slice matrix replay (synthetic benchmark) | Verified |
| **Historical Scan Event Log 2** | `data/events/scan_20261114_082315_038eb0.jsonl` | Multi-failure bisection trace | Verified |
| **Knowledge Trees (31 cases)** | `results/knowledge_trees/*.json` | AST dependency hierarchies for all test cases | Verified |
| **Eval 3 Metric Assets** | `results/eval3/*.csv` & `eval3_summary_table.md` | Ablations, calibration ECE, baselines | Verified |
| **Benchmark Labels** | `labels/labels.json` | Neutralized ground-truth labels & root causes | Verified |

---

## 2. Contingency Protocols by Failure Mode

### Failure Mode A: External LLM API Outage or Rate Limit
- **Symptom:** API calls to Gemini, OpenAI, Anthropic, or Groq fail with timeout or 429.
- **Contingency:**
  FlakeGuard provides `CachedReplayProvider` which requires zero network access:
  ```python
  from flakeguard.llm.providers import CachedReplayProvider
  provider = CachedReplayProvider()  # Automatically replays cached outputs from results/llm_raw/
  ```
- **Fallback Command:**
  The PR comment script and triage workflows automatically fall back to cached outputs when environment secrets are unset.

---

### Failure Mode B: Docker Daemon Unavailable / Pipe Blocked
- **Symptom:** `docker info` fails or named pipe permission denied.
- **Contingency:**
  FlakeGuard features dual sandbox architecture:
  ```powershell
  # Pass --no-docker or omit --docker to use LocalProcessSandbox (CPython 3.12)
  flakeguard scan synthetic --shuffled-n 2
  ```
  `LocalProcessSandbox` operates in an isolated temporary directory with identical environment constraints without needing Docker.

---

### Failure Mode C: Port 8000 Conflict
- **Symptom:** `flakeguard serve` reports `OSError: [Errno 10048] Address already in use`.
- **Contingency:**
  The server automatically probes the next 10 consecutive ports, or a custom port can be explicitly passed:
  ```powershell
  flakeguard serve --port 8080
  ```

---

### Failure Mode D: Live Browser Demonstration Freezes
- **Symptom:** Browser window hangs or presenter laptop has display connection issue.
- **Contingency:**
  All dashboard endpoints can be directly demonstrated via terminal or curl/python:
  ```powershell
  # Inspect active scan state
  python -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/status').read()))"

  # Inspect ablation metrics
  python -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('http://127.0.0.1:8000/api/results').read())['ablations'][0])"
  ```

---

## 3. Fast Verification Command (Run 5 Minutes Before Presentation)

Execute this one-liner to verify all critical components pass:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_server.py tests/test_statistics.py tests/test_llm_stage.py tests/test_notest_repo.py -q
```
*Expected: `37 passed in < 5s`.*

