# flakeguard – Timeline

## Phase 1 – Eval 1 (2026-10-05)

| Work Package | Description | Owner | Reviewer |
| --- | --- | --- | --- |
| WP1 | Repo skeleton, CI, branch protection | A | B |
| WP2 | collect.yml on cachetools (10 runs) | A | B |
| WP3 | Parser → run_table.parquet | A | B |
| WP4 | Navigator v0 (code-under-test resolution) | B | C |
| WP5 | LLM adapter (Ollama, JSON output, Pydantic) | C | A |
| WP6 | Synthetic project (5 planted flakes) | C | A |
| WP7 | Charter, timeline, responsibility matrix | A (leads) | B, C |
| WP8 | Root README | A (leads) | B, C |

**Milestone:** `eval1` tag on `main` by 2026-10-05 morning.

---

## Phase 2 – Eval 2 (date: TODO)

| Work Package | Description | Owner | Reviewer |
| --- | --- | --- | --- |
| WP9 | Labeler (stable / flaky / real_fail + root cause) | A | B |
| WP10 | Baselines B1, B2, B3 | A | B |
| WP11 | Retrieval pipeline (Chroma index, embeddings) | B | C |
| WP12 | Prompt engineering v1–v3 | C | A |
| WP13 | inject-flakiness branch (cachetools) | A | B |
| WP14 | order_dep / shared_state reproducer | A | B |
| WP15 | Evaluation harness | C | A |

**Milestone:** `eval2` tag on `main` by TODO.

---

## Phase 3 – Eval 3 (date: TODO)

| Work Package | Description | Owner | Reviewer |
| --- | --- | --- | --- |
| WP16 | triage.yml, quarantine-approve.yml, monitor.yml | A | B |
| WP17 | Data cards for all datasets | A | B, C |
| WP18 | Full pipeline demo end-to-end | All | All |
| WP19 | Final report | All | All |

**Milestone:** `eval3` tag on `main` by TODO.
