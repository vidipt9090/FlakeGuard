"""The analysis half of the GitHub Actions scan, one subcommand per workflow step.

The per-seed jobs of ``scan.yml`` run the baseline and the shuffled runs and upload their JUnit
files. The ``analyze`` job downloads them into one directory and runs, as separate steps named
after the stage ids:

    isolated    the remaining runs (reversed, isolated, repeated, parallel); baseline and
                shuffled are read from the downloaded JUnit files, not run again
    bisection   bisect every test that both passed and failed
    retrieval   AST + Jedi: tests, shared state, who reads and writes it
    verdict     rules, then ``run.json``, ``findings.json``, ``tree.json`` and ``comment.md``

Each step leaves its result in ``--work`` so the next one can use it.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

from flakeguard import bot_templates
from flakeguard.console.analysis import analyse_repo
from flakeguard.console.builder import (
    build_run,
    collect_stats,
    compute_diagnoses,
    load_runs,
    shuffled_seeds,
)
from flakeguard.runner.orchestrator import ScanConfig, scan


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    return Path(args.repo).resolve(), Path(args.artifacts), work, Path(args.out)


def isolated(args: argparse.Namespace) -> int:
    repo, artifacts, work, _ = _paths(args)
    result = scan(ScanConfig(
        target=str(repo), shuffled_n=args.shuffled_n, seed_start=args.seed_start,
        output_events=str(work / "events.jsonl"), output_artifacts=str(artifacts),
        preloaded_dir=str(artifacts),
    ))
    if not result.success:
        print(f"The scan could not run: {result.reason}", file=sys.stderr)
        return 1
    print(f"{result.total_slices} runs in all, {result.total_tests} tests")
    return 0


def bisection(args: argparse.Namespace) -> int:
    repo, artifacts, work, _ = _paths(args)
    runs = load_runs(repo, artifacts)
    diagnoses, seconds = compute_diagnoses(repo, runs, collect_stats(runs))
    (work / "diagnoses.pkl").write_bytes(pickle.dumps((diagnoses, seconds)))
    named = sum(1 for d in diagnoses.values() if d.reproduced)
    print(f"{len(diagnoses)} mixed tests bisected, {named} polluter pair(s) reproduced, {seconds:.0f} s")
    return 0


def retrieval(args: argparse.Namespace) -> int:
    repo, _, work, _ = _paths(args)
    analysis = analyse_repo(repo)
    (work / "analysis.pkl").write_bytes(pickle.dumps(analysis))
    print(f"{len(analysis.tests)} tests, {len(analysis.states)} shared names, {len(analysis.accesses)} accesses")
    return 0


def verdict(args: argparse.Namespace) -> int:
    repo, artifacts, work, out = _paths(args)
    out.mkdir(parents=True, exist_ok=True)
    analysis = pickle.loads((work / "analysis.pkl").read_bytes())
    diagnoses, seconds = pickle.loads((work / "diagnoses.pkl").read_bytes())
    events = work / "events.jsonl"
    built = build_run(
        repo, artifacts, events, args.run_id, args.label, args.shuffled_n, live=True,
        analysis=analysis, diagnoses=diagnoses, bisection_seconds=seconds,
        stage_text={
            "checkout": f"Checked out {args.commit[:7]}" if args.commit else "Checked out the target",
            "install": "Installed the project and pytest in the runner",
            "pr-comment": "Posted by the comment job",
        },
    )
    findings = [json.loads(f.model_dump_json()) for f in built.findings]
    (out / "run.json").write_text(built.run.model_dump_json(indent=2), encoding="utf-8")
    (out / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (out / "tree.json").write_text(built.tree.model_dump_json(indent=2), encoding="utf-8")

    seeds = shuffled_seeds(events)
    seed_text = (f"{seeds[0]} to {seeds[-1]}" if len(seeds) > 1 else str(seeds[0])) if seeds else None
    (out / "meta.json").write_text(json.dumps({
        "commit": args.commit, "seeds": seeds, "shuffled_runs": len(seeds), "mode": args.mode,
        "run_url": args.run_url,
    }, indent=2), encoding="utf-8")
    post_merge = args.mode == "post-merge"
    if not analysis.tests:  # a scan that found no tests must not claim "no evidence of flakiness"
        comment = bot_templates.did_not_finish(
            run_url=args.run_url, reason="No tests were found in the repository.", post_merge=post_merge)
    elif post_merge:
        comment = bot_templates.post_merge_comment(
            findings, shuffled_runs=len(seeds), commit=args.commit, seeds=seed_text, run_url=args.run_url)
    else:
        comment = bot_templates.pr_comment(
            findings, shuffled_runs=len(seeds), commit=args.commit, seeds=seed_text, run_url=args.run_url)
    (out / "comment.md").write_text(comment, encoding="utf-8")
    print(f"{len(findings)} finding(s); comment {len(comment)} characters")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["isolated", "bisection", "retrieval", "verdict"])
    ap.add_argument("--repo", required=True, help="Checked-out repository to analyse")
    ap.add_argument("--artifacts", required=True, help="Directory holding junit_baseline.xml and junit_shuffled_<i>.xml")
    ap.add_argument("--work", default="flakeguard-work")
    ap.add_argument("--out", default="flakeguard-out")
    ap.add_argument("--shuffled-n", type=int, required=True)
    ap.add_argument("--seed-start", type=int, required=True)
    ap.add_argument("--run-id", default="gh-run")
    ap.add_argument("--label", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--mode", choices=["pr", "post-merge"], default="pr")
    args = ap.parse_args(argv)
    return {"isolated": isolated, "bisection": bisection, "retrieval": retrieval, "verdict": verdict}[args.step](args)


if __name__ == "__main__":
    raise SystemExit(main())
