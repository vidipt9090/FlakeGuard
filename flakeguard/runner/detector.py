"""Framework and Dependency Detection for scanned repositories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class FrameworkInfo:
    """Detection results for a target repository."""

    can_build: bool
    reason: str | None = None
    framework: Literal["pytest", "unittest", "unknown"] = "unknown"
    test_dir: str = "tests"
    install_cmd: list[str] | None = None
    test_files_count: int = 0


def detect_repository(repo_path: str | Path) -> FrameworkInfo:
    """Inspect repository structure to determine test framework and installation method.

    Returns a FrameworkInfo with can_build=False and a clear reason if the repository
    cannot be prepared or has no recognizable tests.
    """
    path = Path(repo_path).resolve()
    if not path.is_dir():
        return FrameworkInfo(
            can_build=False,
            reason=f"could not build: target path is not a directory: {repo_path}",
        )

    # 1. Check for test files
    test_files = list(path.glob("**/test_*.py")) + list(path.glob("**/*_test.py"))
    # Exclude files inside .venv, node_modules, .git
    valid_test_files = [
        f
        for f in test_files
        if not any(
            part.startswith(".") or part in ("node_modules", "build", "dist", ".venv")
            for part in f.parts
        )
    ]

    if not valid_test_files:
        return FrameworkInfo(
            can_build=False,
            reason="could not build: no Python test files found matching 'test_*.py' or '*_test.py'",
        )

    # 2. Determine framework
    framework: Literal["pytest", "unittest", "unknown"] = "pytest"
    has_pytest_config = (
        (path / "pytest.ini").is_file()
        or (path / "pyproject.toml").is_file()
        or (path / "setup.cfg").is_file()
    )

    if not has_pytest_config:
        framework = "pytest"  # pytest is default runner for Python test files

    # 3. Determine install command
    install_cmd: list[str] | None = None
    if (path / "pyproject.toml").is_file() or (path / "setup.py").is_file():
        install_cmd = ["pip", "install", "-e", "."]
    elif (path / "requirements.txt").is_file():
        install_cmd = ["pip", "install", "-r", "requirements.txt"]
    else:
        # Minimal environment without packaging
        install_cmd = ["pip", "install", "pytest", "pytest-randomly", "pytest-repeat"]

    # 4. Determine test directory candidate
    test_dir = "tests"
    if not (path / "tests").is_dir():
        # find most common parent dir of test files
        parents = [f.parent.relative_to(path) for f in valid_test_files]
        if parents:
            test_dir = str(parents[0])

    return FrameworkInfo(
        can_build=True,
        framework=framework,
        test_dir=test_dir,
        install_cmd=install_cmd,
        test_files_count=len(valid_test_files),
    )
