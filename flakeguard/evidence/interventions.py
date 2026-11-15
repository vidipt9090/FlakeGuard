"""Targeted intervention engine to reproduce and confirm root-cause flakiness."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from flakeguard.contracts import InterventionRecord
from flakeguard.runner.matrix import parse_junit_xml
from flakeguard.runner.sandbox import LocalProcessSandbox, Sandbox

# Universal sitecustomize hook template supporting timezone, clock freeze, and delay interventions
_HOOK_SCRIPT = """# Auto-generated FlakeGuard intervention hook
import os
import sys

# 1. Clock freeze intervention (freezegun hook)
target_time = os.environ.get("FLAKEGUARD_TARGET_TIME")
if target_time:
    try:
        import freezegun
        _orig_freeze = freezegun.freeze_time
        def _hooked_freeze(time_to_freeze_str=None, *args, **kwargs):
            return _orig_freeze(target_time, *args, **kwargs)
        freezegun.freeze_time = _hooked_freeze
    except ImportError:
        pass

# 2. Timezone intervention (simulates timezone on all platforms)
target_tz = os.environ.get("FLAKEGUARD_TZ")
if target_tz:
    try:
        import datetime
        import zoneinfo
        zi = zoneinfo.ZoneInfo(target_tz)
        _orig_now = datetime.datetime.now
        datetime.datetime.now = lambda tz=zi: _orig_now(tz).replace(tzinfo=None)
    except Exception:
        pass

# 3. Delay intervention (timing / race condition stress)
delay_add = os.environ.get("FLAKEGUARD_DELAY_ADD")
if delay_add:
    try:
        import threading
        import time
        add_sec = float(delay_add)
        _orig_sleep = time.sleep
        def _delayed_sleep(secs):
            if threading.current_thread() is threading.main_thread():
                _orig_sleep(secs + add_sec)
            else:
                _orig_sleep(secs)
        time.sleep = _delayed_sleep
    except Exception:
        pass
"""


def _run_single_test_with_env(
    repo_path: Path,
    test_id: str,
    extra_env: dict[str, str],
    extra_pytest_args: list[str] | None = None,
    sandbox: Sandbox | None = None,
    timeout: float = 30.0,
) -> tuple[str, str]:
    """Execute a single test with modified environment and return (outcome, message)."""
    sb = sandbox or LocalProcessSandbox(default_timeout=timeout)

    with tempfile.TemporaryDirectory(prefix="flakeguard_intervene_") as tmpdir:
        hook_dir = Path(tmpdir)
        sitecustomize_path = hook_dir / "sitecustomize.py"
        sitecustomize_path.write_text(_HOOK_SCRIPT, encoding="utf-8")
        junit_path = hook_dir / "junit_intervene.xml"

        env = os.environ.copy()
        env.update(extra_env)
        # Inject hook_dir at the beginning of PYTHONPATH
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{str(hook_dir.resolve())}{os.pathsep}{existing_pp}" if existing_pp else str(hook_dir.resolve())

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--junitxml={str(junit_path.resolve())}",
            *(extra_pytest_args or []),
            test_id,
        ]

        sb.run(cmd, cwd=repo_path, env=env, timeout=timeout)
        if not junit_path.exists():
            return "ERROR", "JUnit XML not generated"

        outcomes = parse_junit_xml(junit_path)
        for out in outcomes:
            if out.test_id == test_id or out.test_id.endswith(f"::{test_id.split('::')[-1]}"):
                return out.outcome, out.message

        return "PASS", ""


class InterventionEngine:
    """Orchestrates interventions: seed pinning, timezone shifts, clock freeze, and delays."""

    def __init__(self, sandbox: Sandbox | None = None) -> None:
        self.sandbox = sandbox

    def pin_seed(
        self,
        repo_path: Path,
        test_id: str,
        base_outcome: str,
        seeds: list[int] | None = None,
        timeout: float = 30.0,
    ) -> InterventionRecord:
        """Run test under pinned seeds using pytest-randomly and PYTHONHASHSEED."""
        test_seeds = seeds or [1, 2, 4, 42, 100]
        flipped_seed: int | None = None
        final_outcome = base_outcome

        for seed in test_seeds:
            outcome, _ = _run_single_test_with_env(
                repo_path=repo_path,
                test_id=test_id,
                extra_env={"PYTHONHASHSEED": str(seed)},
                extra_pytest_args=[f"--randomly-seed={seed}"],
                sandbox=self.sandbox,
                timeout=timeout,
            )
            if outcome != base_outcome and outcome != "ERROR":
                flipped_seed = seed
                final_outcome = outcome
                break

        if flipped_seed is not None:
            return InterventionRecord(
                kind="pin_seed",
                parameters={"seeds_tested": test_seeds, "confirmed_seed": flipped_seed},
                flipped=True,
                outcome=final_outcome,
                details=f"Outcome flipped from {base_outcome} to {final_outcome} when seed pinned to {flipped_seed}",
            )

        return InterventionRecord(
            kind="pin_seed",
            parameters={"seeds_tested": test_seeds},
            flipped=False,
            outcome=base_outcome,
            details=f"Outcome remained {base_outcome} across all tested seeds",
        )

    def vary_tz(
        self,
        repo_path: Path,
        test_id: str,
        base_outcome: str,
        timezones: list[str] | None = None,
        timeout: float = 30.0,
    ) -> InterventionRecord:
        """Run test under varied timezones."""
        test_tzs = timezones or ["UTC", "America/New_York", "Asia/Tokyo", "Pacific/Honolulu"]
        flipped_tz: str | None = None
        final_outcome = base_outcome

        for tz in test_tzs:
            outcome, _ = _run_single_test_with_env(
                repo_path=repo_path,
                test_id=test_id,
                extra_env={"TZ": tz, "FLAKEGUARD_TZ": tz},
                sandbox=self.sandbox,
                timeout=timeout,
            )
            if outcome != base_outcome and outcome != "ERROR":
                flipped_tz = tz
                final_outcome = outcome
                break

        if flipped_tz is not None:
            return InterventionRecord(
                kind="vary_tz",
                parameters={"timezones_tested": test_tzs, "confirmed_tz": flipped_tz},
                flipped=True,
                outcome=final_outcome,
                details=f"Outcome flipped from {base_outcome} to {final_outcome} under timezone {flipped_tz}",
            )

        return InterventionRecord(
            kind="vary_tz",
            parameters={"timezones_tested": test_tzs},
            flipped=False,
            outcome=base_outcome,
            details=f"Outcome remained {base_outcome} across timezones",
        )

    def freeze_clock(
        self,
        repo_path: Path,
        test_id: str,
        base_outcome: str,
        target_times: list[str] | None = None,
        timeout: float = 30.0,
    ) -> InterventionRecord:
        """Run test with frozen or shifted clock."""
        test_times = target_times or [
            "2026-10-04 12:00:00",  # midday
            "2026-10-05 10:00:00",  # Monday business hours
            "2026-10-03 23:30:00",  # nighttime
        ]
        flipped_time: str | None = None
        final_outcome = base_outcome

        for t in test_times:
            outcome, _ = _run_single_test_with_env(
                repo_path=repo_path,
                test_id=test_id,
                extra_env={"FLAKEGUARD_TARGET_TIME": t},
                sandbox=self.sandbox,
                timeout=timeout,
            )
            if outcome != base_outcome and outcome != "ERROR":
                flipped_time = t
                final_outcome = outcome
                break

        if flipped_time is not None:
            return InterventionRecord(
                kind="freeze_clock",
                parameters={"times_tested": test_times, "confirmed_time": flipped_time},
                flipped=True,
                outcome=final_outcome,
                details=f"Outcome flipped from {base_outcome} to {final_outcome} when clock set to {flipped_time}",
            )

        return InterventionRecord(
            kind="freeze_clock",
            parameters={"times_tested": test_times},
            flipped=False,
            outcome=base_outcome,
            details=f"Outcome remained {base_outcome} across tested clock times",
        )

    def add_delay(
        self,
        repo_path: Path,
        test_id: str,
        base_outcome: str,
        delay_sec: float = 0.08,
        timeout: float = 30.0,
    ) -> InterventionRecord:
        """Run test with injected timing delay / CPU jitter."""
        outcome, msg = _run_single_test_with_env(
            repo_path=repo_path,
            test_id=test_id,
            extra_env={"FLAKEGUARD_DELAY_ADD": str(delay_sec)},
            sandbox=self.sandbox,
            timeout=timeout,
        )

        flipped = (outcome != base_outcome and outcome != "ERROR")
        return InterventionRecord(
            kind="add_delay",
            parameters={"delay_add_seconds": delay_sec},
            flipped=flipped,
            outcome=outcome,
            details=(
                f"Outcome flipped from {base_outcome} to {outcome} with +{delay_sec}s delay"
                if flipped
                else f"Outcome remained {outcome} with +{delay_sec}s delay"
            ),
        )

    def run_all(
        self,
        repo_path: Path,
        test_id: str,
        base_outcome: str,
        category_hint: str | None = None,
        timeout: float = 30.0,
    ) -> list[InterventionRecord]:
        """Run interventions prioritizing the suspect category."""
        records: list[InterventionRecord] = []

        # Order interventions to check likely cause first
        order = ["pin_seed", "freeze_clock", "vary_tz", "add_delay"]
        if category_hint in ("randomness", "random"):
            order = ["pin_seed", "add_delay", "freeze_clock", "vary_tz"]
        elif category_hint in ("time_tz", "timezone", "time"):
            order = ["freeze_clock", "vary_tz", "pin_seed", "add_delay"]
        elif category_hint in ("timing", "concurrency"):
            order = ["add_delay", "pin_seed", "freeze_clock", "vary_tz"]

        for action in order:
            if action == "pin_seed":
                rec = self.pin_seed(repo_path, test_id, base_outcome, timeout=timeout)
            elif action == "freeze_clock":
                rec = self.freeze_clock(repo_path, test_id, base_outcome, timeout=timeout)
            elif action == "vary_tz":
                rec = self.vary_tz(repo_path, test_id, base_outcome, timeout=timeout)
            elif action == "add_delay":
                rec = self.add_delay(repo_path, test_id, base_outcome, timeout=timeout)
            else:
                continue

            records.append(rec)
            # If confirmed flipped, we found the causal factor
            if rec.flipped:
                break

        return records

