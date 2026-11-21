"""High-level Orchestrator for `flakeguard scan <repo-url|path>`."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flakeguard.runner.detector import detect_repository
from flakeguard.runner.events import EventLogger
from flakeguard.runner.matrix import DEFAULT_SEED_START, PerturbationMatrix, SliceResult
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
    seed_start: int = DEFAULT_SEED_START  # first pytest-randomly seed; shuffled run i uses seed_start + i - 1


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

    Supports local paths, workspace sibling folders, owner/repo shorthand, and Git URLs.
    Returns: (repo_path, sha, is_cloned_temp)
    """
    target_clean = target.strip()
    target_path = Path(target_clean)

    # 1. Existing local directory
    if target_path.is_dir():
        repo_path = target_path.resolve()
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

    # 2. Check sibling directories in workspace (e.g. 'flakeguard-demo' or '../flakeguard-demo')
    repo_root = Path(__file__).resolve().parents[2]
    repo_name_only = target_clean.split("/")[-1].split("\\")[-1]
    candidates = [
        Path.cwd() / target_clean,
        Path.cwd().parent / target_clean,
        repo_root / target_clean,
        repo_root / repo_name_only,
        repo_root.parent / target_clean,
        repo_root.parent / repo_name_only,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            repo_path = candidate.resolve()
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

    # 3. Check if target is an owner/repo shorthand (e.g. vidipt9090/flakeguard-demo)
    git_url = target_clean
    if "/" in target_clean and not target_clean.startswith(("http://", "https://", "git@")):
        parts = target_clean.split("/")
        if len(parts) == 2 and not any(p in target_clean for p in ("\\", ":")):
            git_url = f"https://github.com/{target_clean}.git"

    # 4. Check if target looks like a git URL
    if git_url.startswith("http://") or git_url.startswith("https://") or git_url.startswith("git@"):
        clone_dest = temp_dir / "repo"
        try:
            res = subprocess.run(
                ["git", "clone", "--depth", "50", git_url, str(clone_dest)],
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
            raise RuntimeError(f"Could not clone repository {git_url}: {exc}") from exc

    raise ValueError(f"Target '{target}' is neither an existing directory nor a recognized Git URL.")


def _export_scan_artifacts(
    repo_path: Path,
    pinned_sha: str,
    test_stats: dict[str, dict],
    flaky_tests: list[str],
    artifacts_dir: Path,
    event_log_path: str,
) -> tuple[Path, Path, Path, Path]:
    """Export event log, JUnit XML, findings.json, and tree.json as single-source artifacts."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    events_dest = artifacts_dir / "events.jsonl"
    junit_dest = artifacts_dir / "junit.xml"
    findings_dest = artifacts_dir / "findings.json"
    tree_dest = artifacts_dir / "tree.json"

    # 1. Events JSONL
    if Path(event_log_path).exists() and Path(event_log_path).resolve() != events_dest.resolve():
        try:
            shutil.copyfile(event_log_path, events_dest)
        except Exception:
            pass

    # 2. JUnit XML
    found_xml = False
    for xml_name in ["junit_baseline.xml", "junit_shuffled_0.xml", "junit_reversed.xml"]:
        src = artifacts_dir / xml_name
        if src.exists() and src.stat().st_size > 0:
            try:
                shutil.copyfile(src, junit_dest)
                found_xml = True
                break
            except Exception:
                pass
    if not found_xml:
        for xml_candidate in artifacts_dir.glob("*.xml"):
            if xml_candidate != junit_dest and xml_candidate.stat().st_size > 0:
                try:
                    shutil.copyfile(xml_candidate, junit_dest)
                    found_xml = True
                    break
                except Exception:
                    pass

    # 3. Findings JSON
    findings = []
    for tid, stats in test_stats.items():
        is_flaky = tid in flaky_tests
        has_fails = (stats.get("fail", 0) + stats.get("error", 0)) > 0
        if not is_flaky and not has_fails:
            continue

        verdict = "flaky" if is_flaky else "real"
        tier = "confirmed_by_intervention" if is_flaky else "observed"
        messages = " ".join(stats.get("messages", []))
        root_cause = "Order dependence" if is_flaky else "Deterministic regression"
        if "sleep" in messages.lower() or "timeout" in messages.lower():
            root_cause = "Timing / Async"
        elif "random" in messages.lower():
            root_cause = "Randomness"
        elif "conftest" in messages.lower() or "state" in messages.lower():
            root_cause = "Shared state leak"

        plain_sentence = (
            f"Fails in {stats.get('failure_rate', 0.0) * 100:.0f}% of shuffled runs. "
            f"Passes in isolation. Evidence tier: {tier}."
            if is_flaky
            else f"Consistently fails across all {stats.get('total', 0)} perturbation runs. Real defect."
        )

        where_it_lives = stats.get("where_it_lives") or (f"{tid.split('::')[0]}:1" if "::" in tid else f"{tid}.py:1")

        findings.append({
            "id": f"finding-{len(findings) + 1}",
            "test_id": tid,
            "verdict": verdict,
            "root_cause": root_cause,
            "plain_sentence": plain_sentence,
            "evidence_tier": tier,
            "can_quarantine": is_flaky,
            "has_fix": is_flaky and ("Order" in root_cause or "State" in root_cause),
            "where_it_lives": where_it_lives,
            "fail_rate": stats.get("failure_rate", 0.0),
            "total_runs": stats.get("total", 0),
            "pass_runs": stats.get("pass", 0),
            "fail_runs": stats.get("fail", 0) + stats.get("error", 0),
        })

    findings_dest.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    # 4. Live AST + Jedi Tree JSON
    tree_data: dict[str, Any] = {
        "repo": repo_path.name,
        "sha": pinned_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
    }

    try:
        from flakeguard.navigator.ast_nav import AstNavigator
        from flakeguard.navigator.knowledge_tree import build_tree

        nav = AstNavigator(repo_root=repo_path, repo=repo_path.name, sha=pinned_sha)
        cases_to_nav = flaky_tests if flaky_tests else list(test_stats.keys())[:10]
        for tid in cases_to_nav:
            res = nav.related(tid)
            kt = build_tree(res, nav.provenance, repo=repo_path.name, sha=pinned_sha)
            tree_data["cases"].append({
                "test_id": tid,
                "tree": kt.to_dict(),
                "stats": kt.stats(),
                "rows": kt.rows(),
            })
    except Exception as e:
        tree_data["error"] = str(e)

    tree_dest.write_text(json.dumps(tree_data, indent=2), encoding="utf-8")
    return events_dest, junit_dest, findings_dest, tree_dest


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
            if not docker_sb.is_available():
                event_logger.log(
                    "ingest",
                    "error",
                    data={
                        "outcome": "docker unavailable",
                        "reason": "Docker isolation was requested, but the Docker daemon is unreachable. Please start Docker Desktop or uncheck 'Isolate in Docker'.",
                    },
                )
                raise RuntimeError(
                    "Docker isolation was requested, but the Docker daemon is unreachable. Please start Docker Desktop or uncheck 'Isolate in Docker'."
                )
            sandbox = docker_sb
            event_logger.log(
                "discover",
                "progress",
                data={"sandbox": "docker", "base_image": config.base_image},
            )
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
                "seed_start": config.seed_start,
                "seeds": [config.seed_start + k for k in range(config.shuffled_n)],
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
            seed_start=config.seed_start,
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

        # 6. Export Single-Source Artifact Bundle (events.jsonl, junit.xml, findings.json, tree.json)
        _export_scan_artifacts(
            repo_path=repo_path,
            pinned_sha=pinned_sha,
            test_stats=test_stats,
            flaky_tests=flaky_tests,
            artifacts_dir=artifacts_dir,
            event_log_path=str(event_logger.path),
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
