# FlakeGuard Eval 3: Master Evidence Tracker

All gates specified in `# FlakeGuard Final: connected, verified, demo-ready` have been executed, verified, and backed by evidence files.

| Gate | Title | Status | Evidence Document | Verified Artifact / Output |
|---|---|---|---|---|
| **Gate 0** | Protect the Work (Secrets & Backup) | **PASSED** | [`g0.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g0.md) | Zero committed secrets/keys; clean working tree |
| **Gate 1** | One Canonical Codebase | **PASSED** | [`g1.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g1.md) | `make check` green (245 passed, 4 skipped); ruff clean; Gemini live provider |
| **Gate 2** | Numbers You Can Defend | **PASSED** | [`g2.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g2.md) | D23 false quarantine verified 0.00; `test_provenance.py` 4 passed; assets regenerated |
| **Gate 3** | GitHub Setup | **PASSED** | [`g3.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g3.md) | Reusable `.github/workflows/scan.yml` + caller in `flakeguard-demo` |
| **Gate 3b** | Vet Demo Repos | **PASSED** | [`repos.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/repos.md) | Selected demo targets (flakeguard-demo, synthetic, notest) under 5-7m budget |
| **Gate G4** | Scan Synthetic Locally | **PASSED** | [`g4.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g4.md) | `scan_20261115_070737_df6b95`: 11 perturbation slices, 10 flaky tests isolated |
| **Gate G5** | Scan Demo Repo & Shorthand | **PASSED** | [`g5.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g5.md) | `scan_20261115_070833_a0bd55`: `vidipt9090/flakeguard-demo` resolved seamlessly |
| **Gate G6** | PR Triage Comment | **PASSED** | [`g6.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g6.md) | Sticky comment marker `<!-- flakeguard-triage-marker -->`; 4/4 tests pass |
| **Gate G7** | Quarantine Approval Gate | **PASSED** | [`g7.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g7.md) | Writer check, real-bug 403 refusal, idempotent de-duplication verified |
| **Gate G8** | Dashboard Scan Dispatch | **PASSED** | [`g8.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g8.md) | `POST /api/scan` starts scan; live progress & completed state polled |
| **Gate G9** | Ask "Why does this fail?" RAG | **PASSED** | [`g9.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g9.md) | AST code chunks; `file:line` citations; strict refusal on unmatched query |
| **Gate G10** | No-Test Repo Workflow | **PASSED** | [`g10.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g10.md) | Static AST risk scan (4 sites); test generation recording current behaviour; 6 passed |
| **Gate G11** | External Vetted Repo Scan | **PASSED** | [`g11.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g11.md) | `cachetools` under 45s; graceful `could not build` diagnostic handling |
| **Gate G12** | Fix PR Bot | **PASSED** | [`g12.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g12.md) | Automated teardown fixture proposed with `status: ready_for_review`; test passed |
| **Gate G13** | Results Tab with Provenance | **PASSED** | [`g13.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g13.md) | Planted, Injected, Natural tabs; strict `{command, git_sha, time, data_label}` |
| **Gate G14** | PR Lifecycle & Post-Merge Check | **PASSED** | [`g14.md`](file:///c:/Users/khull/Desktop/4th%20Year/IDT%20Final/FlakeGuard/docs/eval3/evidence/g14.md) | Event `pr_closed` + `post_merge_check` verifying "no evidence in N runs" |

