"""High-level Orchestrator for `flakeguard scan <repo-url|path>`."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from flakeguard.runner.detector import detect_repository
from flakeguard.runner.events import EventLogger
from flakeguard.runner.matrix import PerturbationMatrix, SliceResult
from flakeguard.runner.sandbox import DockerSandbox, LocalProcessSandbox, Sandbox


@dataclass
class ScanConfig:
    target: str
    sha: str | None = None
    shuffled_n: int = 5
    timeout: float = 60.0
    use_docker: bool = False
    output_events: str | None = None
    output_artifacts: str | None = None
    base_image: str = "python:3.12-slim"


@dataclass
class ScanResult:
    run_id: str
    success: bool
    outcome: str  # "completed", "could not build", "failed"
    reason: str | None = None
    pinned_sha: str = ""
    event_log_path: str = ""
    total_slices: int = 0
    total_tests: int = 0
    flaky_tests: list[str] = field(default_factory=list)
    test_summaries: dict[str, dict] = field(default_factory=dict)


def _resolve_target(
    target: str, temp_dir: Path
) -> tuple[Path, str, bool]:
    """Resolve target to a local path and extract/pin commit SHA.

    Returns: (repo_path, sha, is_cloned_temp)
    """
    target_path = Path(target)
    if target_path.is_dir():
        repo_path = target_path.resolve()
        # Query local git SHA if git is present
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            sha = res.stdout.strip() if res.returncode == 0 else "unknown"
        except Exception:
            sha = "unknown"
        return repo_path, sha, False

    # Check if target looks like a git URL
    if target.startswith("http://") or target.startswith("https://") or target.startswith("git@"):
        clone_dest = temp_dir / "repo"
        try:
            res = subprocess.run(
                ["git", "clone", "--depth", "50", target, str(clone_dest)],
                capture_output=True,
                text=True,
                timeout=120.0,
            )
            if res.returncode != 0:
                raise RuntimeError(f"git clone failed: {res.stderr}")
            res_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(clone_dest),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            sha = res_sha.stdout.strip() if res_sha.returncode == 0 else "unknown"
            return clone_dest, sha, True
        except Exception as exc:
            raise RuntimeError(f"Could not clone repository {target}: {exc}") from exc

    raise ValueError(f"Target '{target}' is neither an existing directory nor a recognized Git URL.")


def scan(config: ScanConfig) -> ScanResult:
    """Execute end-to-end repository scan and perturbation matrix."""
    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"scan_{ts_slug}_{uuid.uuid4().hex[:6]}"
    event_logger = EventLogger(run_id, output_path=config.output_events)

    # 1. Ingest Stage
    event_logger.log(
        "ingest",
        "started",
        data={"target": config.target, "requested_sha": config.sha},
    )

    temp_clone_dir = Path(tempfile.mkdtemp(prefix="flakeguard_clone_"))
    try:
        try:
            repo_path, current_sha, is_cloned = _resolve_target(
                config.target, temp_clone_dir
            )
        except Exception as exc:
            event_logger.log(
                "ingest",
                "error",
                data={"outcome": "could not build", "reason": str(exc)},
            )
            return ScanResult(
                run_id=run_id,
                success=False,
                outcome="could not build",
                reason=str(exc),
                event_log_path=str(event_logger.path),
            )

        # Pin requested SHA if provided
        pinned_sha = current_sha
        if config.sha and config.sha != current_sha:
            try:
                sub_res = subprocess.run(
                    ["git", "checkout", config.sha],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                )
                if sub_res.returncode == 0:
                    pinned_sha = config.sha
                else:
                    reason = f"could not build: failed to checkout requested SHA {config.sha}: {sub_res.stderr}"
                    event_logger.log(
                        "ingest",
                        "error",
                        data={"outcome": "could not build", "reason": reason},
                    )
                    return ScanResult(
                        run_id=run_id,
                        success=False,
                        outcome="could not build",
                        reason=reason,
                        event_log_path=str(event_logger.path),
                    )
            except Exception as exc:
                reason = f"could not build: git checkout exception: {exc}"
                event_logger.log(
                    "ingest",
                    "error",
                    data={"outcome": "could not build", "reason": reason},
                )
                return ScanResult(
                    run_id=run_id,
                    success=False,
                    outcome="could not build",
                    reason=reason,
                    event_log_path=str(event_logger.path),
                )

        event_logger.log(
            "ingest",
            "result",
            data={"repo_path": str(repo_path), "pinned_sha": pinned_sha},
        )

        # 2. Discover Stage
        event_logger.log("discover", "started")
        framework_info = detect_repository(repo_path)
        if not framework_info.can_build:
            reason = framework_info.reason or "could not build: detection failed"
            event_logger.log(
                "discover",
                "error",
                data={"outcome": "could not build", "reason": reason},
            )
            return ScanResult(
                run_id=run_id,
                success=False,
                outcome="could not build",
                reason=reason,
                pinned_sha=pinned_sha,
                event_log_path=str(event_logger.path),
            )

        event_logger.log(
            "discover",
            "result",
            data={
                "framework": framework_info.framework,
                "test_dir": framework_info.test_dir,
                "test_files_count": framework_info.test_files_count,
            },
        )

        # 3. Setup Sandbox
        sandbox: Sandbox
        if config.use_docker:
            docker_sb = DockerSandbox(
                repo_path=repo_path,
                base_image=config.base_image,
                default_timeout=config.timeout,
            )
            if docker_sb.is_available():
                sandbox = docker_sb
                event_logger.log(
                    "discover",
                    "progress",
                    data={"sandbox": "docker", "base_image": config.base_image},
                )
            else:
                event_logger.log(
                    "discover",
                    "progress",
                    data={
                        "sandbox": "local_process",
                        "note": "Docker requested but unreachable; falling back to LocalProcessSandbox",
                    },
                )
                sandbox = LocalProcessSandbox(default_timeout=config.timeout)
        else:
            sandbox = LocalProcessSandbox(default_timeout=config.timeout)

        # Artifacts destination
        if config.output_artifacts:
            artifacts_dir = Path(config.output_artifacts)
        else:
            artifacts_dir = Path("data") / "artifacts" / run_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # 4. Run Stage (Perturbation Matrix)
        event_logger.log(
            "run",
            "started",
            data={
                "slices": [
                    "baseline",
                    "shuffled",
                    "reversed",
                    "isolated",
                    "repeated",
                    "parallel",
                ],
                "shuffled_n": config.shuffled_n,
            },
        )

        # Find current python executable
        python_exe = sys.executable or "python"

        matrix = PerturbationMatrix(
            sandbox=sandbox,
            repo_path=repo_path,
            shuffled_n=config.shuffled_n,
            test_dir=framework_info.test_dir,
            timeout=config.timeout,
            python_exe=python_exe,
        )

        matrix_results: list[SliceResult] = matrix.run_matrix(
            artifacts_dir=artifacts_dir,
            event_logger=event_logger,
        )

        # 5. Aggregate Results & Identify Flakes
        test_stats: dict[str, dict] = {}
        for slice_res in matrix_results:
            for outcome in slice_res.outcomes:
                tid = outcome.test_id
                if tid not in test_stats:
                    test_stats[tid] = {
                        "total": 0,
                        "pass": 0,
                        "fail": 0,
                        "skip": 0,
                        "error": 0,
                        "durations": [],
                        "messages": [],
                    }
                test_stats[tid]["total"] += 1
                outcome_key = outcome.outcome.lower()
                if outcome_key in test_stats[tid]:
                    test_stats[tid][outcome_key] += 1
                test_stats[tid]["durations"].append(outcome.duration_s)
                if outcome.message:
                    test_stats[tid]["messages"].append(outcome.message)

        flaky_tests: list[str] = []
        for tid, stats in test_stats.items():
            tot = stats["total"]
            pas = stats["pass"]
            fal = stats["fail"] + stats["error"]
            stats["failure_rate"] = (fal / tot) if tot > 0 else 0.0
            # Test is flaky if it both passes and fails across perturbation matrix
            is_flaky = pas > 0 and fal > 0
            stats["is_flaky"] = is_flaky
            if is_flaky:
                flaky_tests.append(tid)

        event_logger.log(
            "run",
            "result",
            data={
                "total_slices": len(matrix_results),
                "total_tests": len(test_stats),
                "flaky_tests_count": len(flaky_tests),
                "flaky_tests": flaky_tests,
            },
        )

        return ScanResult(
            run_id=run_id,
            success=True,
            outcome="completed",
            pinned_sha=pinned_sha,
            event_log_path=str(event_logger.path),
            total_slices=len(matrix_results),
            total_tests=len(test_stats),
            flaky_tests=flaky_tests,
            test_summaries=test_stats,
        )

    finally:
        # Clean up temporary clone directory if created
        if temp_clone_dir.exists():
            shutil.rmtree(temp_clone_dir, ignore_errors=True)
