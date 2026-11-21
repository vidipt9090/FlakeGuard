"""Live runs: start a scan subprocess, track it, and report what it is doing.

One scan at a time. Each run gets a fresh directory ``runs/<live-id>/``, so a stale file from
an earlier run can never be read as the current one. The truth about a run is its
``progress.json``, except when the process behind it has died while the file still says
``running``: then the run is marked as stopped early and no verdict is shown.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flakeguard.console import models as m
from flakeguard.console.live import STAGES, stopped_early, write_atomic
from flakeguard.console.store import REPO_ROOT, NotFound

RUNS_DIR = REPO_ROOT / "runs"
LIVE_ID = re.compile(r"^live-\d{4}-\d{2}-\d{2}-\d{3}$")
DEMO_REPOS = {"vidipt9090/flakeguard-demo"}  # code we wrote, vetted to run without Docker
SAMPLE_TARGET = "tests/data/demo_inventory"


class Refused(Exception):
    """The request cannot be served. The message is shown to the person using the console."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def is_live_id(run_id: str) -> bool:
    return bool(LIVE_ID.match(run_id))


class RunManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else RUNS_DIR
        self.processes: dict[str, subprocess.Popen] = {}

    # ----------------------------------------------------------------- queries

    def dir(self, run_id: str) -> Path:
        if not is_live_id(run_id) or not (self.root / run_id).is_dir():
            raise NotFound(f"There is no run called {run_id}.")
        return self.root / run_id

    def active_id(self) -> str | None:
        for run_id, proc in self.processes.items():
            if proc.poll() is None:
                return run_id
        return None

    def next_id(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        taken = [p.name for p in self.root.glob(f"live-{day}-*")] if self.root.is_dir() else []
        return f"live-{day}-{len(taken) + 1:03d}"

    def status(self, run_id: str) -> m.RunStatus:
        """The run's progress, with a dead process turned into 'stopped early'."""
        path = self.dir(run_id) / "progress.json"
        if not path.is_file():
            raise NotFound(f"Run {run_id} has no progress yet.")
        run = m.RunStatus.model_validate_json(path.read_text(encoding="utf-8"))
        if run.status != "running":
            return run
        proc = self.processes.get(run_id)
        if proc is not None and proc.poll() is None:
            return run
        # The process is gone. Look again: it may have finished between our read and the check.
        run = m.RunStatus.model_validate_json(path.read_text(encoding="utf-8"))
        if run.status != "running":
            return run
        if proc is not None:
            detail = f"The scan process ended before it finished (exit code {proc.returncode}). No verdict is shown."
        else:
            detail = "The scan was interrupted before it finished (this server restarted). No verdict is shown."
        stopped = stopped_early(run, detail)
        write_atomic(path, stopped.model_dump_json(indent=2))
        return stopped

    def _complete_file(self, run_id: str, name: str) -> str:
        run = self.status(run_id)
        if run.status == "running":
            raise Refused("The scan has not finished, so there is no verdict yet.", 409)
        if run.status != "complete":
            raise Refused("The scan stopped early, so there is no verdict.", 409)
        return (self.dir(run_id) / name).read_text(encoding="utf-8")

    def findings_json(self, run_id: str) -> str:
        return self._complete_file(run_id, "findings.json")

    def tree_json(self, run_id: str) -> str:
        return self._complete_file(run_id, "tree.json")

    # ------------------------------------------------------------------- start

    @staticmethod
    def resolve_target(req: m.StartRunRequest) -> tuple[str, str]:
        """(target for the scanner, label shown on screen). Raises Refused."""
        if req.source == "pull-request":
            raise Refused(
                "Pull request scans run on GitHub Actions, which is not built yet. "
                "Pick 'Paste a repo' or 'Sample repo' to scan on this machine.", 422)
        if req.source == "sample":
            return str(REPO_ROOT / SAMPLE_TARGET), f"{SAMPLE_TARGET} (sample repo)"
        target = req.target.strip()
        if not target:
            raise Refused("Type a repository first.", 422)
        if Path(target).is_dir():
            return target, f"{target} (local folder)"
        if target.removesuffix(".git").removeprefix("https://github.com/") in DEMO_REPOS or req.docker:
            return target, target
        raise Refused(
            "FlakeGuard runs the tests of the repository you give it. Only the demo repository "
            "and folders on this machine run without Docker. Tick 'Isolate in Docker' for others.", 422)

    def refuse_docker(self, req: m.StartRunRequest, label: str) -> str:
        """Docker was requested but is not running: record that, and run nothing."""
        run_id = self.next_id()
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True)
        stages = [
            m.Stage(id=sid, name=name, detail="Not run", tool="not run", time=None, state="pending")
            for sid, name, _tool, _detail in STAGES
        ]
        run = m.RunStatus(
            id=run_id, target=label, mode="local", status="failed", pr=None, stages=stages, current=None,
            counters=m.Counters(runsDone=0, runsTotal=req.runs, failures=0, flagged=0), matrix=[],
            notice=m.Notice(kind="docker-not-running"),
        )
        write_atomic(run_dir / "progress.json", run.model_dump_json(indent=2))
        return run_id

    def start(self, req: m.StartRunRequest, target: str, label: str, seed_start: int) -> str:
        active = self.active_id()
        if active is not None:
            raise Refused(f"A scan is already running ({active}). Wait for it to finish.", 409)
        run_id = self.next_id()
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True)
        cmd = [
            sys.executable, "-m", "flakeguard.console.live_scan",
            "--run-dir", str(run_dir), "--run-id", run_id, "--target", target, "--label", label,
            "--shuffled-n", str(req.runs), "--seed-start", str(seed_start),
        ]
        if req.docker:
            cmd.append("--docker")
        log = open(run_dir / "scan.log", "wb")  # noqa: SIM115 - handed to the child process
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)
        log.close()
        self.processes[run_id] = proc
        (run_dir / "pid.txt").write_text(str(proc.pid), encoding="utf-8")
        return run_id


_manager: RunManager | None = None


def manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager


def set_manager(value: RunManager | None) -> None:
    global _manager
    _manager = value


def seed_start_from_env() -> int | None:
    raw = os.environ.get("FLAKEGUARD_SEED_START")
    return int(raw) if raw else None
