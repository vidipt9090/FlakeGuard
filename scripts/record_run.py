"""Record a real scan as a console run under ``recorded/<run-id>/``.

    python scripts/record_run.py tests/data/demo_inventory --shuffled-n 10 \
        --want-single-failure tests/test_sync.py::test_sync_timeout

Runs ``flakeguard scan`` as a subprocess, keeps its raw output (``raw/``), builds
``run.json``, ``findings.json`` and ``tree.json`` from it, and writes ``PROVENANCE.txt``
with the exact commands, the commit and the environment.

``--want-single-failure TEST`` repeats the scan until that test fails in exactly one run
overall, and that run is one of the shuffled runs. The fixture test it is used for fails by an unseeded random draw, so a single
scan can land on any count. The number of attempts is written to PROVENANCE.txt, because
choosing a run this way is a selection and has to be disclosed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flakeguard.console import fixer  # noqa: E402
from flakeguard.console.builder import build_run, collect_stats, load_runs, shuffled_seeds  # noqa: E402


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def next_run_id(out: Path, day: str) -> str:
    existing = [p.name for p in out.glob(f"run-{day}-*")] if out.exists() else []
    return f"run-{day}-{len(existing) + 1:03d}"


def version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "not installed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="Path to the repository to scan, relative to the FlakeGuard repo")
    ap.add_argument("--clone", metavar="OWNER/REPO", default=None,
                    help="Scan an anonymous clone of this GitHub repository instead of a local path")
    ap.add_argument("--shuffled-n", type=int, default=10)
    ap.add_argument("--out", default="recorded")
    ap.add_argument("--want-single-failure", metavar="TEST_ID", default=None)
    ap.add_argument("--max-attempts", type=int, default=30)
    ap.add_argument("--seed-start", type=int, default=None, help="First pytest-randomly seed (engine default if omitted)")
    ap.add_argument("--allow-dirty", action="store_true", help="Record even if tracked files are modified")
    ap.add_argument("--fix-runs", type=int, default=fixer.DEFAULT_RUNS,
                    help="Shuffled orders used to validate a proposed fix on a copy (0: no fix is attempted)")
    args = ap.parse_args()

    if bool(args.target) == bool(args.clone):
        ap.error("give either a local target path or --clone OWNER/REPO")
    clone_dir = None
    target_sha = None
    if args.clone:
        clone_dir = Path(tempfile.mkdtemp(prefix="fg-record-")) / "target"
        subprocess.run(
            ["git", "-c", "credential.helper=", "clone", "--depth", "50", f"https://github.com/{args.clone}.git", str(clone_dir)],
            check=True, capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        target_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone_dir, capture_output=True, text=True, check=True).stdout.strip()
        args.target = str(clone_dir)
    target = (REPO_ROOT / args.target).resolve()
    out_root = (REPO_ROOT / args.out).resolve()
    dirty = git("status", "--porcelain", "--", ".", ":!recorded")
    if dirty and not args.allow_dirty:
        print("The working tree has uncommitted or untracked files; commit first so PROVENANCE.txt names a real commit.\n" + dirty)
        return 2
    commit = git("rev-parse", "HEAD")

    now = datetime.now(timezone.utc)
    run_id = next_run_id(out_root, now.strftime("%Y-%m-%d"))
    run_dir = out_root / run_id
    raw = run_dir / "raw"
    shown_target = f"<clone of {args.clone} at {target_sha}>" if args.clone else args.target
    scan_cmd = [
        "python", "-m", "flakeguard", "scan", shown_target, "--shuffled-n", str(args.shuffled_n),
        "--output-events", f"{args.out}/{run_id}/raw/events.jsonl",
        "--output-artifacts", f"{args.out}/{run_id}/raw/artifacts",
    ]
    if args.seed_start is not None:
        scan_cmd += ["--seed-start", str(args.seed_start)]

    attempts = 0
    while True:
        attempts += 1
        if run_dir.exists():
            shutil.rmtree(run_dir)
        raw.mkdir(parents=True)
        proc = subprocess.run(
            [sys.executable, "-m", "flakeguard", "scan", args.target, *scan_cmd[5:]],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        (raw / "scan_stdout.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if proc.returncode != 0:
            print(f"Scan failed (exit {proc.returncode}); see {raw / 'scan_stdout.txt'}")
            return 1
        if not args.want_single_failure:
            break
        stats = collect_stats(load_runs(target, raw / "artifacts"))
        s = stats.get(args.want_single_failure)
        if s is not None and s.failures == 1 and s.count("shuffled")[0] == 1:
            break
        print(f"Attempt {attempts}: {args.want_single_failure} did not fail exactly once across all runs, in a shuffled one; retrying")
        if attempts >= args.max_attempts:
            print("Gave up: no scan matched.")
            return 1

    if args.clone:
        label = f"{args.clone} @ {target_sha[:7]}"
        built = build_run(
            repo=target, artifacts=raw / "artifacts", events_path=raw / "events.jsonl", run_id=run_id,
            target_label=label, shuffled_n=args.shuffled_n,
            stage_text={
                "checkout": f"Cloned {args.clone} at {target_sha[:7]} (anonymous, shallow).",
                "install": "Not run. A local scan uses this machine's Python environment.",
                "pr-comment": "Not run. This is a saved scan of a repository, not a pull request.",
            },
            notice_detail="Replay of a saved scan of a cloned GitHub repository, not a pull request and not a GitHub Actions run.",
            fix_runs=args.fix_runs,
            did="Nothing was posted or changed. This run was a saved scan of a cloned repository, not a pull request.",
        )
        shutil.copytree(target, run_dir / "target", ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        meta_target = f"{args.out}/{run_id}/target"
    else:
        built = build_run(
            repo=target, artifacts=raw / "artifacts", events_path=raw / "events.jsonl", run_id=run_id,
            target_label=f"{args.target} (local fixture)", shuffled_n=args.shuffled_n, fix_runs=args.fix_runs,
        )
        meta_target = args.target
    (run_dir / "run.json").write_text(built.run.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "findings.json").write_text(
        "[" + ",".join(f.model_dump_json(indent=2) for f in built.findings) + "]", encoding="utf-8"
    )
    (run_dir / "tree.json").write_text(built.tree.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps({"target": meta_target, "source_repo": args.clone, "source_commit": target_sha}, indent=2),
        encoding="utf-8",
    )

    record_cmd = ["python", "scripts/record_run.py", *(["--clone", args.clone] if args.clone else [args.target]),
                  "--shuffled-n", str(args.shuffled_n)]
    if args.seed_start is not None:
        record_cmd += ["--seed-start", str(args.seed_start)]
    if args.fix_runs != fixer.DEFAULT_RUNS:
        record_cmd += ["--fix-runs", str(args.fix_runs)]
    with_fix = [f for f in built.findings if f.fix is not None]
    if args.fix_runs <= 0:
        fix_line = "Fix preview: not attempted (--fix-runs 0)."
    elif with_fix:
        fix_line = (
            "Fix preview: present for " + ", ".join(f"{f.test} ({f.fix.file})" for f in with_fix) + ". It was computed when this was recorded, "
            f"by flakeguard/console/fixer.py on a copy of the repository: the suite in {args.fix_runs} shuffled orders with the fix, plus the polluter-then-victim repro without and with it. "
            "The 'checked' text on the finding states the counts. It is a preview; nothing was applied to the repository or pushed."
        )
    else:
        fix_line = (
            f"Fix preview: null. A fix was attempted for order-dependent findings (validation in {args.fix_runs} shuffled orders) and none passed, or no finding "
            "has shared module-level dict/list/set state the fixer handles. Where a fix was tried and failed, the finding's evidence says so."
        )
    seeds = shuffled_seeds(raw / "events.jsonl")
    seed_line = (
        f"{', '.join(str(x) for x in seeds)} (read from raw/events.jsonl, one per shuffled run)"
        if seeds else "not recorded"
    )
    if args.want_single_failure:
        record_cmd += ["--want-single-failure", args.want_single_failure]
    selection = (
        f"Scan repeated until {args.want_single_failure} failed in exactly 1 run overall, and that run was one of\n"
        f"  the {args.shuffled_n} shuffled runs.\n"
        f"  Attempts: {attempts}. This is a selection of the run, not an average. The test fails by an\n"
        "  unseeded random draw (os.urandom), so the count varies from scan to scan."
        if args.want_single_failure else (
            f"None. One scan, one attempt (attempts: {attempts}), with fixed seeds {seed_line.split(' (')[0]}.\n"
            "  The seeds make the outcome reproducible, so there was nothing to select: scanning the same commit with\n"
            "  the same seeds gives the same shuffled-run results. (Bisection and the pair runs are also deterministic.)"
        )
    )
    if args.clone:
        header = (
            "TARGET IS A GITHUB REPOSITORY CLONED ON THIS MACHINE (anonymous clone), NOT A PULL REQUEST AND NOT A GITHUB ACTIONS RUN.\n"
            f"  Repository: https://github.com/{args.clone}\n"
            f"  Commit scanned: {target_sha}\n"
            "  Nothing was posted to GitHub. The console shows no PR links and no PR comment for this run."
        )
        repro_dir = f"git clone https://github.com/{args.clone} && cd {args.clone.split('/')[-1]} && git checkout {target_sha}"
    else:
        header = (
            "TARGET IS A LOCAL FIXTURE, NOT A GITHUB PULL REQUEST.\n"
            f"  Path: {args.target}\n"
            "  Nothing was posted to GitHub. The console shows no PR links and no PR comment for this run."
        )
        repro_dir = f"cd {args.target}"
    (run_dir / "PROVENANCE.txt").write_text(
        f"""Recorded run {run_id}

{header}

Recorded (UTC): {now.isoformat(timespec='seconds')}
Commit: {commit}   (FlakeGuard repository HEAD when this was recorded; working tree clean: {not dirty})

Command that produced the scan (run from the repository root):
  {' '.join(scan_cmd)}
Command that recorded and converted it:
  {' '.join(record_cmd)}

Selection:
  {selection}

Environment:
  Python {platform.python_version()} on {platform.platform()}
  pytest {version('pytest')}, pytest-randomly {version('pytest-randomly')}, jedi {version('jedi')}
  Shuffled seeds: {seed_line}

Files:
  raw/                 what flakeguard scan wrote: events.jsonl, one JUnit XML per run, scan_stdout.txt
  run.json             RunStatus (console contract)
  findings.json        Finding[]
  tree.json            TreeData
  Every count in these files is computed from raw/artifacts/junit_*.xml by flakeguard/console/builder.py.

Do not read these as results:
  raw/artifacts/findings.json and raw/artifacts/tree.json are written by the older scan
  orchestrator. Its findings.json states "confirmed_by_intervention" for every flaky test
  without running any intervention, and its tree has one node. The console does not use them.
  Only the JUnit XML and events.jsonl in raw/ feed run.json, findings.json and tree.json.

What is not in this run (shown as dashes, pending, or absent in the console):
  - {fix_line}
  - Pull request and PR comment: none. Install and PR comment stages are shown as pending ("not run").
  - Evidence tier "intervention-confirmed": not used. No change was made that removed a failure.

How to reproduce the order-dependence finding on a clean checkout of the commit above:
  {repro_dir}
  pytest tests/test_warmup.py::test_cache_warm tests/test_report.py::test_report_total -p no:randomly
  (expected: test_report_total fails; run test_report_total alone and it passes)

Counter definitions (Live screen):
  runsDone / runsTotal  shuffled runs completed / requested
  failures              shuffled runs in which the highlighted test failed
  flagged               number of findings (tests with at least one failure)
""",
        encoding="utf-8",
    )
    print(f"Recorded {run_dir}  ({attempts} attempt(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
