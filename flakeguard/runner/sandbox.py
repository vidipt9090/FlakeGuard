"""Sandbox abstractions for isolated test execution (Docker and Local Process)."""

from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of a sandboxed execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Sandbox(ABC):
    """Abstract interface for running commands in an isolated environment."""

    @abstractmethod
    def run(
        self,
        cmd: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Run a command inside the sandbox."""
        raise NotImplementedError


class LocalProcessSandbox(Sandbox):
    """Executes commands in isolated local subprocesses with resource limits and timeouts."""

    def __init__(self, default_timeout: float = 60.0) -> None:
        self.default_timeout = default_timeout

    def run(
        self,
        cmd: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        eff_timeout = timeout if timeout is not None else self.default_timeout
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=eff_timeout,
            )
            duration = time.perf_counter() - start
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=duration,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - start
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            return ExecutionResult(
                exit_code=124,  # Standard timeout exit status
                stdout=stdout,
                stderr=stderr + f"\n[ERROR] Command timed out after {eff_timeout:.1f}s",
                duration=duration,
                timed_out=True,
            )
        except Exception as exc:
            duration = time.perf_counter() - start
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"[ERROR] Subprocess launch failed: {exc}",
                duration=duration,
                timed_out=False,
            )


class DockerSandbox(Sandbox):
    """Executes commands inside an isolated Docker container with cpu and memory bounds."""

    def __init__(
        self,
        repo_path: Path,
        base_image: str = "python:3.12-slim",
        cpus: float = 2.0,
        memory: str = "2g",
        default_timeout: float = 120.0,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.base_image = base_image
        self.cpus = cpus
        self.memory = memory
        self.default_timeout = default_timeout

    def is_available(self) -> bool:
        """Check if Docker CLI and daemon are reachable."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def run(
        self,
        cmd: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        eff_timeout = timeout if timeout is not None else self.default_timeout
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            f"--cpus={self.cpus}",
            f"--memory={self.memory}",
            "-v",
            f"{self.repo_path}:/workspace",
            "-w",
            "/workspace",
        ]

        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.append(self.base_image)
        docker_cmd.extend(cmd)

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=eff_timeout,
            )
            duration = time.perf_counter() - start
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=duration,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - start
            return ExecutionResult(
                exit_code=124,
                stdout=str(exc.stdout or ""),
                stderr=f"[ERROR] Docker container timed out after {eff_timeout:.1f}s",
                duration=duration,
                timed_out=True,
            )
        except Exception as exc:
            duration = time.perf_counter() - start
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"[ERROR] Docker execution failed: {exc}",
                duration=duration,
                timed_out=False,
            )
