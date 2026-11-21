"""Entry point for one live scan, run as a subprocess by the console backend.

    python -m flakeguard.console.live_scan --run-dir runs/live-... --run-id live-... \
        --target <dir|owner/repo|https url> --label "..." --shuffled-n 10 --seed-start 1001

Writes ``progress.json`` after every individual run, then ``findings.json`` and ``tree.json``,
and finally the finished ``progress.json``. If anything goes wrong it writes a ``failed``
progress with the ``scan-incomplete`` notice and exits 1. If the process is killed, nothing
more is written; the backend notices the dead process and marks the run as stopped early.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from flakeguard.console.builder import build_run
from flakeguard.console.live import LiveRun, write_atomic
from flakeguard.runner.orchestrator import ScanConfig, scan

_SHORTHAND = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def prepare_target(target: str, run_dir: Path) -> tuple[Path, str]:
    """Return (local repository path, text for the Checkout stage).

    An existing directory is used in place. ``owner/repo`` and https URLs are cloned
    anonymously (no stored credentials are used) into ``run_dir/repo``. Nothing else is
    accepted, and in particular no sibling-folder guessing.
    """
    target = target.strip()
    if Path(target).is_dir():
        return Path(target).resolve(), "Local folder, used in place. No clone was needed."
    url = target
    if _SHORTHAND.match(target):
        url = f"https://github.com/{target}.git"
    if not url.startswith("https://"):
        raise ValueError(f"'{target}' is not a folder on this machine, an owner/repo name or an https URL.")
    dest = run_dir / "repo"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", "-c", "credential.helper=", "clone", "--depth", "50", url, str(dest)],
        capture_output=True, text=True, timeout=180, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"could not clone {url}: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'git failed'}")
    return dest, f"Cloned {url} (anonymous, shallow)."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--shuffled-n", type=int, required=True)
    ap.add_argument("--seed-start", type=int, required=True)
    ap.add_argument("--docker", action="store_true")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    live = LiveRun(run_dir, args.run_id, args.label, args.shuffled_n, args.seed_start)
    try:
        repo, checkout_text = prepare_target(args.target, run_dir)
        (run_dir / "meta.json").write_text(
            json.dumps({"target": str(repo), "pid": os.getpid(), "seed_start": args.seed_start}, indent=2),
            encoding="utf-8",
        )
        events, artifacts = run_dir / "events.jsonl", run_dir / "artifacts"
        result = scan(
            ScanConfig(
                target=str(repo), shuffled_n=args.shuffled_n, seed_start=args.seed_start,
                use_docker=args.docker, output_events=str(events), output_artifacts=str(artifacts),
            ),
            observer=live,
        )
        if not result.success:
            live.fail(f"The scan could not run: {result.reason}. No verdict is shown.")
            return 1
        built = build_run(
            repo, artifacts, events, args.run_id, args.label, args.shuffled_n, live=True,
            progress=live.phase,
            stage_text={
                "checkout": checkout_text,
                "install": "Not run. A local scan uses this machine's Python environment.",
                "pr-comment": "Not run. A local scan does not post to GitHub.",
            },
        )
        write_atomic(run_dir / "findings.json", "[" + ",".join(f.model_dump_json() for f in built.findings) + "]")
        write_atomic(run_dir / "tree.json", built.tree.model_dump_json())
        live.complete(built.run)
        return 0
    except Exception as exc:  # report it on screen; a half-finished scan must not look finished
        live.fail(f"The scan stopped early: {exc}. No verdict is shown.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
