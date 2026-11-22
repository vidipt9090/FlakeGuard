"""Re-verify a finding: five more shuffled runs of the suite, appended to the finding's evidence.

The old evidence stays. The new line is stored next to the run (``reverify.json``), never in a
recorded run, and is merged into the findings when they are served.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from flakeguard.console import fixer
from flakeguard.console import models as m

RUNS = 5
SEED_START = 1001  # the engine's default seeds; the demo scans use 1 to 10, so these are new orders
FILE = "reverify.json"
_running: set[str] = set()
_lock = threading.Lock()


def read(run_dir: Path) -> dict[str, list[str]]:
    path = run_dir / FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def with_evidence(run_dir: Path, findings: list[m.Finding]) -> list[m.Finding]:
    extra = read(run_dir)
    return [f.model_copy(update={"evidence": [*f.evidence, *extra[f.id]]}) if f.id in extra else f for f in findings]


def claim(finding_id: str) -> bool:
    """True if this finding was not already being re-verified."""
    with _lock:
        if finding_id in _running:
            return False
        _running.add(finding_id)
        return True


def release(finding_id: str) -> None:
    with _lock:
        _running.discard(finding_id)


def run_reverify(repo: Path, run_dir: Path, finding: m.Finding, *, runs: int = RUNS, seed_start: int = SEED_START) -> str:
    """Run the suite ``runs`` times in new shuffled orders and record how often the finding's test failed."""
    test_id = f"{finding.file}::{finding.test}"
    test_dir = finding.file.split("/")[0] if "/" in finding.file else "."
    failed = ran = 0
    seeds = list(range(seed_start, seed_start + runs))
    with tempfile.TemporaryDirectory(prefix="flakeguard-reverify-") as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(repo, copy, ignore=fixer._IGNORE)
        for seed in seeds:
            try:
                _, outcomes = fixer._pytest(
                    copy, ["-p", "randomly", f"--randomly-seed={seed}", test_dir], Path(tmp) / f"{seed}.xml", 120)
            except subprocess.TimeoutExpired:
                continue
            if test_id in outcomes:
                ran += 1
                failed += outcomes[test_id] in ("FAIL", "ERROR")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ran == 0:
        line = f"Re-verify on {day}: no result. None of the {runs} shuffled runs produced an outcome for {finding.test}."
    else:
        line = (f"Re-verified on {day}: {finding.test} failed in {failed} of {ran} new shuffled runs "
                f"(seeds {seeds[0]} to {seeds[-1]}).")
    extra = read(run_dir)
    extra.setdefault(finding.id, []).append(line)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / FILE
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(extra, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return line
