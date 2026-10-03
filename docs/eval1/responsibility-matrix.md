# flakeguard – Responsibility Matrix

Legend: **O** = Owner, **R** = Reviewer, – = not involved

| Work Package | Description | A | B | C |
| --- | --- | --- | --- | --- |
| WP1 | Repo skeleton, CI, branch protection | **O** | R | – |
| WP2 | collect.yml on cachetools (10 runs) | **O** | R | – |
| WP3 | Parser → run_table.parquet | **O** | R | – |
| WP4 | Navigator v0 | R | **O** | – |
| WP5 | LLM adapter | – | – | **O** |
| WP6 | Synthetic project (5 planted flakes) | R | – | **O** |
| WP7 | Charter, timeline, matrix | **O** | R | R |
| WP8 | Root README | **O** | R | R |
| WP9 | Labeler | **O** | R | – |
| WP10 | Baselines B1, B2, B3 | **O** | R | – |
| WP11 | Retrieval pipeline (Chroma) | R | **O** | – |
| WP12 | Prompt engineering v1–v3 | R | – | **O** |
| WP13 | Inject-flakiness branch | **O** | R | – |
| WP14 | order_dep / shared_state reproducer | **O** | R | – |
| WP15 | Evaluation harness | – | R | **O** |
| WP16 | triage.yml, quarantine workflows | **O** | R | – |
| WP17 | Data cards | **O** | R | R |
| WP18 | Full pipeline demo | **O** | **O** | **O** |
| WP19 | Final report | **O** | **O** | **O** |

---
*B and C: please read and comment. If you disagree with any assignment, open a PR with changes.*
