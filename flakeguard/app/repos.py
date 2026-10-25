"""Resolve a repository spec to a directory on disk, cloning it if it is a URL.

The live panel asks for "a repository". Typing a GitHub URL there is the
obvious thing to do, so it works: a URL is cloned (shallow, into a cache) and
a path is used as-is.

What this deliberately does *not* do:

* **run anything from the cloned repo.** The navigator only parses it --
  ``ast.parse`` plus jedi's static resolution. Nothing is imported, no
  ``setup.py`` or ``conftest.py`` is executed, and the clone directory is
  never added to this process's ``sys.path``.
* **shell out.** Every git call is an argument list with ``--`` before
  user-supplied values, so a URL cannot smuggle in a flag.
* **prompt.** ``GIT_TERMINAL_PROMPT=0`` makes a private repo fail in seconds
  with a readable message instead of hanging on a credential prompt.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / ".cache" / "repos"

# Schemes we will clone. Anything else (file://, ext::, a bare path that only
# looks like a URL) is refused rather than handed to git to interpret.
URL_RE = re.compile(
    r"^(?:https?://|git@)"            # https, http, or ssh shorthand
    r"[A-Za-z0-9._~%-]+"              # host
    r"[:/][A-Za-z0-9._~%/+-]+?"       # owner/name
    r"(?:\.git)?/?$"
)

CLONE_TIMEOUT = 180
TEST_FILE_RE = re.compile(r"(^test_.*\.py$)|(.*_test\.py$)")

# Directories never worth walking for tests.
SKIP_DIRS = frozenset(
    {
        ".git", ".venv", "venv", "env", ".tox", ".nox", "node_modules",
        "__pycache__", "site-packages", "dist-packages", ".eggs", "build",
        "dist", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    }
)


class RepoError(Exception):
    """Something the user can act on, phrased for them."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass
class Resolved:
    path: Path
    kind: str          # "local" | "clone"
    url: str = ""
    sha: str = ""
    name: str = ""
    cached: bool = False

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "url": self.url,
            "sha": self.sha,
            "name": self.name,
            "cached": self.cached,
        }


def looks_like_url(spec: str) -> bool:
    return bool(URL_RE.match(spec.strip()))


def slug_for(url: str) -> tuple[str, str]:
    """(cache subdirectory, display name) for a clone URL."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.replace("git@", "").replace(":", "/")
    parts = [p for p in cleaned.split("/") if p]
    safe = []
    for part in parts:
        cleaned_part = re.sub(r"[^A-Za-z0-9._-]", "_", part)
        # A part of nothing but dots is "." or ".." -- the sanitiser above
        # lets those through, because dots are legal in a repository name,
        # and they would walk the clone out of the cache directory.
        if not cleaned_part.strip("."):
            continue
        safe.append(cleaned_part)
    safe = safe[-3:]
    return "/".join(safe) if safe else "repo", safe[-1] if safe else "repo"


def _git(args: list[str], cwd: Path | None = None, timeout: int = 60) -> str:
    env = dict(os.environ)
    # Fail fast on a private repo instead of blocking on a credential prompt.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepoError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepoError(
            f"git timed out after {timeout}s.",
            "A very large repository, or no network.",
        ) from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"git exited {done.returncode}"
        hint = ""
        blob = " ".join(detail).lower()
        if "authentication" in blob or "could not read" in blob or "403" in blob:
            hint = "If the repository is private, clone it yourself and give the local path."
        elif "not found" in blob or "repository not found" in blob:
            hint = "Check the URL — a typo, or the repository is private."
        raise RepoError(f"git: {message}", hint)
    return done.stdout.strip()


def resolve(spec: str, refresh: bool = False) -> Resolved:
    """A repository spec -- local path or clone URL -- as a directory."""
    spec = (spec or "").strip().strip('"').strip("'").strip()
    if not spec:
        raise RepoError("No repository given.")

    if not looks_like_url(spec):
        path = Path(spec)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        if not path.is_dir():
            raise RepoError(
                f"{path} is not a directory on this machine.",
                "Give a local path, or paste a repository URL to clone it.",
            )
        return Resolved(path=path, kind="local", name=path.name)

    subdir, name = slug_for(spec)
    target = CACHE / subdir

    if target.is_dir() and not refresh:
        try:
            sha = _git(["rev-parse", "--short=12", "HEAD"], cwd=target)
        except RepoError:
            shutil.rmtree(target, ignore_errors=True)
        else:
            return Resolved(
                path=target, kind="clone", url=spec, sha=sha, name=name, cached=True
            )

    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Shallow, no submodules, no checkout of history we will not read.
    _git(
        [
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--no-tags",
            "--",
            spec,
            str(target),
        ],
        timeout=CLONE_TIMEOUT,
    )
    sha = _git(["rev-parse", "--short=12", "HEAD"], cwd=target)
    return Resolved(path=target, kind="clone", url=spec, sha=sha, name=name)


# ------------------------------------------------------------- discovery


def discover_tests(root: Path, limit: int = 2000) -> list[dict]:
    """Test ids in a repository, found by parsing -- never by importing.

    Returns pytest node ids: ``path::test_name`` and
    ``path::TestClass::test_name``. A repository the user just cloned has no
    reason to be guessable, so the UI offers this list instead of asking them
    to type an id blind.
    """
    found: list[dict] = []
    for path in sorted(_test_files(root)):
        if len(found) >= limit:
            break
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, ValueError):
            continue
        rel = path.relative_to(root).as_posix()
        for node in tree.body:
            if len(found) >= limit:
                break
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test"):
                    found.append(
                        {"test_id": f"{rel}::{node.name}", "file": rel,
                         "name": node.name, "cls": "", "line": node.lineno}
                    )
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for inner in node.body:
                    if len(found) >= limit:
                        break
                    if isinstance(
                        inner, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and inner.name.startswith("test"):
                        found.append(
                            {
                                "test_id": f"{rel}::{node.name}::{inner.name}",
                                "file": rel,
                                "name": inner.name,
                                "cls": node.name,
                                "line": inner.lineno,
                            }
                        )
    return found


def _test_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith(".py") and TEST_FILE_RE.match(filename):
                yield Path(dirpath) / filename


def cache_size_mb() -> float:
    if not CACHE.is_dir():
        return 0.0
    total = 0
    for dirpath, _, filenames in os.walk(CACHE):
        for filename in filenames:
            try:
                total += (Path(dirpath) / filename).stat().st_size
            except OSError:
                continue
    return round(total / (1024 * 1024), 1)


def cached_repos() -> list[dict]:
    """What is already cloned, so the UI can offer it without a network hop."""
    if not CACHE.is_dir():
        return []
    out = []
    for path in sorted(CACHE.rglob("*")):
        if not (path / ".git").is_dir():
            continue
        try:
            url = _git(["remote", "get-url", "origin"], cwd=path)
            sha = _git(["rev-parse", "--short=12", "HEAD"], cwd=path)
        except RepoError:
            continue
        out.append(
            {"name": path.name, "path": str(path), "url": url, "sha": sha}
        )
    return out
