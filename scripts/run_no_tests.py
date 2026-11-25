"""The no-tests flow on a repository without tests, recorded for the console.

    python scripts/run_no_tests.py                          # scans fixtures/no_tests_demo
    python scripts/run_no_tests.py --repo path/to/repo --k 5

Scans for risky spots, asks the local model (llama3.2:3b through Ollama) for one test per spot, and keeps a test only if it passes at
HEAD and gives the same result over k runs with different shuffle seeds (flakeguard/notest/validator.py). Everything runs on a temporary
copy of the repository. Nothing is written to GitHub. The result goes to ``recorded_no_tests/<id>/`` (state.json and no_tests.json) and
the console serves it at ``GET /api/runs/<id>/no-tests``. If Ollama does not answer the script stops; it never replays a cached answer.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from flakeguard.console import no_tests  # noqa: E402
from flakeguard.notest.orchestrator import generate_tests_for_repo  # noqa: E402
from flakeguard.notest.provider import NUM_CTX, SEED, OllamaUnavailable, PlainOllamaProvider  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def next_id() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    taken = [int(p.name[-3:]) for p in no_tests.NO_TESTS_DIR.glob(f"notests-{today}-*")] if no_tests.NO_TESTS_DIR.is_dir() else []
    return f"notests-{today}-{max(taken, default=0) + 1:03d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="fixtures/no_tests_demo")
    ap.add_argument("--k", type=int, default=5, help="runs with different shuffle seeds (validator default 5)")
    ap.add_argument("--max-tests", type=int, default=5)
    args = ap.parse_args(argv)
    source = (REPO / args.repo).resolve()
    if any((source / "tests").glob("*.py")) or any(source.glob("test_*.py")):
        print(f"{args.repo} already has tests; this flow is for a repository without any.", file=sys.stderr)
        return 2

    provider = PlainOllamaProvider()
    try:
        ollama_version = provider.version()
    except OllamaUnavailable as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2

    command = "python " + " ".join(["scripts/run_no_tests.py", *(argv if argv is not None else sys.argv[1:])])
    dirty_at_start = bool(_git("status", "--porcelain", "--untracked-files=no"))
    with tempfile.TemporaryDirectory(prefix="flakeguard_notests_") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(source, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        summary = generate_tests_for_repo(work, output_test_file=None, max_tests=args.max_tests, k_shuffled_runs=args.k, provider=provider)
        cands = []
        for site, test, val in summary.candidates:
            rel = Path(site.file_path).resolve().relative_to(work.resolve())
            real = source / rel
            cands.append({
                "test": test.test_name, "where": f"{rel.as_posix()}:{site.line_number}", "category": site.risk_category,
                "what": site.explanation, "kept": val.kept, "droppedByUser": False, "reason": val.rejection_reason,
                "fromTemplate": test.from_template, "testCode": test.test_code,
                "checks": {"passedAtHead": val.passed_at_head, "deterministic": val.deterministic_over_k, "kRunsExecuted": val.k_runs},
                "risky": {"file": rel.as_posix(), "lines": no_tests.snippet_lines(real, site.line_number)},
                "testFile": {"file": f"tests/test_{rel.stem}.py", "lines": no_tests.code_lines(test.test_code)},
            })
        state = {
            "id": next_id(), "repo": args.repo, "candidates": cands,
            "provenance": {
                "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "command": command, "commit": _git("rev-parse", "HEAD"),
                # true if a tracked file differed from the commit when the scan started or when it ended
                "tracked_files_modified": dirty_at_start or bool(_git("status", "--porcelain", "--untracked-files=no")),
                "model": provider.model_name, "seed": SEED, "num_ctx": NUM_CTX, "temperature": 0, "ollama_version": ollama_version,
                "k_shuffled_runs": args.k, "sandbox": "local process on a temporary copy, not Docker", "python": platform.python_version(),
                "risky_sites_found": summary.risky_sites_count,
            },
        }
        no_tests.write_plan(state["id"], state)
    print(f"id {state['id']}: {summary.risky_sites_count} risky sites, {summary.tests_generated_count} tests written, "
          f"{summary.tests_kept_count} kept, {summary.tests_rejected_count} dropped")
    for c in cands:
        print(f"  {c['test']:32} {'kept   ' if c['kept'] else 'dropped'} {'(template) ' if c['fromTemplate'] else '(model)    '}{c['reason'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
