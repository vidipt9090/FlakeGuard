"""The parts of M6 that talk to GitHub: fix pull request on a fork, quarantine issue, permission check.

Two credentials exist and they are never mixed up:

* the backend token (``GITHUB_TOKEN``, ``GH_TOKEN`` or the ``gh`` login) reads runs, checks write
  permission and opens the quarantine tracking issue on the repository that was scanned;
* the fork token belongs to the fork owner and is used for one thing only: to push the fix branch to
  that person's fork and open the fix pull request there. It comes from ``FLAKEGUARD_FORK_TOKEN``,
  or from ``gh auth token --user <fork owner>``. It is passed to git through the environment, so it
  appears in no command line, log, comment or file.

FlakeGuard never merges anything. Fixes are opened on the fork (BOT-2).
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from flakeguard import bot_templates
from flakeguard.console import fixer
from flakeguard.console import models as m
from flakeguard.console.analysis import analyse_repo, shared_links

API = "https://api.github.com"
WRITE_PERMISSIONS = {"admin", "write", "maintain"}
BOT_NAME, BOT_EMAIL = "FlakeGuard", "flakeguard@users.noreply.github.com"


class ForgeError(Exception):
    """Something the person using the console should read. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class GitHub:
    """A tiny REST client. One token, one purpose."""

    def __init__(self, token: str, *, base: str = API, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(
            base_url=base, timeout=20, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        return self._http.request(method, path, **kw)

    def json(self, method: str, path: str, ok: tuple[int, ...] = (200, 201), **kw) -> dict:
        resp = self.request(method, path, **kw)
        if resp.status_code not in ok:
            raise ForgeError(_api_message(resp), 502 if resp.status_code >= 500 else 409)
        return resp.json()


def _api_message(resp: httpx.Response) -> str:
    try:
        text = resp.json().get("message", "")
    except ValueError:
        text = ""
    return f"GitHub answered HTTP {resp.status_code}" + (f": {text}" if text else "")


# ------------------------------------------------------------------ write permission and quarantine


def permission_of(gh: GitHub, repo: str, login: str) -> str:
    """The collaborator permission of ``login`` on ``repo``: admin, write, read or none."""
    resp = gh.request("GET", f"/repos/{repo}/collaborators/{login}/permission")
    if resp.status_code == 404:
        return "none"
    if resp.status_code != 200:
        raise ForgeError(_api_message(resp), 502)
    return resp.json().get("permission", "none")


def can_write(gh: GitHub, repo: str, login: str) -> bool:
    return permission_of(gh, repo, login) in WRITE_PERMISSIONS


def quarantine_refusal(finding: m.Finding) -> str | None:
    """Why this finding may not be quarantined, or None when it may. Same rule as the console."""
    return None if finding.quarantine.allowed else (finding.quarantine.reason or "Quarantine is refused for this test.")


def open_quarantine_issue(gh: GitHub, repo: str, finding: m.Finding, *, requester: str, run_url: str | None) -> str:
    """The tracking issue. Quarantine here means a person-visible issue; no test is skipped or deleted."""
    body = bot_templates.quarantine_issue(
        test=finding.test, file=finding.file, line=finding.line, why=finding.why,
        evidence=finding.evidence, requester=requester, run_url=run_url,
    )
    issue = gh.json("POST", f"/repos/{repo}/issues", json={"title": f"Flaky test: {finding.test}", "body": body})
    return issue["html_url"]


# --------------------------------------------------------------------------------- fix pull request


def fork_token(owner: str) -> str:
    """The fork owner's token, never printed. ``FLAKEGUARD_FORK_TOKEN`` wins, then ``gh auth token --user``."""
    token = os.environ.get("FLAKEGUARD_FORK_TOKEN", "").strip()
    if token:
        return token
    try:
        proc = subprocess.run(["gh", "auth", "token", "--user", owner], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        raise ForgeError(
            f"There is no credential for the fork owner {owner}. Set FLAKEGUARD_FORK_TOKEN or sign in with "
            f"`gh auth login` as {owner}.", 503)
    return proc.stdout.strip()


def _git(args: list[str], cwd: Path, token: str | None = None) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if token:
        header = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {header}")
    proc = subprocess.run(["git", "-c", "credential.helper=", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        err = (proc.stderr.strip().splitlines() or ["git failed"])[-1]
        raise ForgeError(f"git {args[0]} failed: {err}", 502)
    return proc.stdout


def fetch_source(source: m.SourceRef, dest: Path) -> None:
    """Anonymous clone of the scanned repository, checked out at the scanned commit."""
    dest.mkdir(parents=True, exist_ok=True)
    _git(["clone", "--quiet", "--no-tags", f"https://github.com/{source.repo}.git", "."], dest)
    have = subprocess.run(["git", "cat-file", "-e", f"{source.ref}^{{commit}}"], cwd=dest, capture_output=True)
    if have.returncode != 0:
        _git(["fetch", "--quiet", "origin", source.ref], dest)
    _git(["checkout", "--quiet", "--detach", source.ref], dest)


@dataclass
class FixTarget:
    plan: fixer.FixPlan
    polluter_id: str
    victim_id: str
    polluter_name: str
    victim_name: str


def locate_fix(repo: Path, finding: m.Finding) -> FixTarget:
    """Find the shared state, polluter and victim for ``finding`` in the checked-out code."""
    analysis = analyse_repo(repo)
    victim = next((t for t in analysis.tests if t.name == finding.test and t.file == finding.file), None)
    if victim is None:
        raise ForgeError(f"{finding.test} is not in {finding.file} at the scanned commit, so no fix can be made.")
    written_by = next((c.text.removeprefix("written by ") for c in finding.lives if c.tone == "write"), None)
    for link in shared_links(analysis):
        if victim.id not in link.readers:
            continue
        writers = [t for t in analysis.tests if t.id in link.writers and (written_by is None or t.name == written_by)]
        if len(writers) != 1:
            continue
        plan = fixer.plan_fix(repo, link.state)
        if plan is None:
            raise ForgeError(f"{link.state.name} is not a plain dict, list or set, so FlakeGuard has no fix for it.")
        return FixTarget(plan, writers[0].id, victim.id, writers[0].name, victim.name)
    raise ForgeError("No single polluter and shared value were found for this test, so no fix can be made.")


@dataclass
class FixResult:
    pr_url: str
    branch: str
    base: str
    validation: fixer.Validation


def open_fix_pr(
    source: m.SourceRef, finding: m.Finding, known_failing: set[str], *, fork_owner: str, token: str,
    runs: int = fixer.DEFAULT_RUNS, gh: GitHub | None = None, validated: list[str] | None = None,
) -> FixResult:
    """Validate the fix on a fresh checkout, and only if it passes push it to the fork and open the pull request."""
    name = source.repo.split("/", 1)[1]
    fork = f"{fork_owner}/{name}"
    gh = gh or GitHub(token)
    info = gh.request("GET", f"/repos/{fork}")
    if info.status_code == 404:
        raise ForgeError(f"{fork_owner} has no fork of {source.repo}. Create the fork first; FlakeGuard does not create it.")
    if info.status_code != 200:
        raise ForgeError(_api_message(info), 502)
    parent = (info.json().get("parent") or {}).get("full_name")
    if not info.json().get("fork") or parent != source.repo:
        raise ForgeError(f"{fork} is not a fork of {source.repo}, so no pull request was opened.")

    work = Path(tempfile.mkdtemp(prefix="flakeguard-forge-"))
    try:
        repo = work / "repo"
        fetch_source(source, repo)
        target = locate_fix(repo, finding)
        log: list[str] = []
        test_dir = finding.file.split("/")[0] if "/" in finding.file else "."
        result = fixer.validate_fix(repo, target.plan, polluter=target.polluter_id, victim=target.victim_id,
                                    known_failing=known_failing, test_dir=test_dir, runs=runs, log=log)
        if not result.passed:
            raise ForgeError(f"The fix did not pass validation, so no pull request was opened: {result.reason()}.")
        if validated is not None:
            validated.extend(log)

        short = source.ref[:7]
        base = f"flakeguard/base-{short}"
        branch = f"flakeguard/fix-{finding.test}-{short}"
        fixer.apply_fix(repo, target.plan)
        _git(["-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "checkout", "--quiet", "-b", branch], repo)
        _git(["add", target.plan.file], repo)
        _git(["-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "commit", "--quiet", "-m",
              f"Reset {target.plan.state} after each test (FlakeGuard fix for {finding.test})"], repo)
        url = f"https://github.com/{fork}.git"
        # Plain pushes, no force. The base branch is a copy of the scanned commit so the pull request
        # has something on the fork to target; the upstream default branch is never touched.
        _git(["push", "--quiet", url, f"{source.ref}:refs/heads/{base}"], repo, token)
        _git(["push", "--quiet", url, f"HEAD:refs/heads/{branch}"], repo, token)

        body = bot_templates.fix_pr(
            test=finding.test, state=target.plan.state, file=target.plan.file,
            lines=len(target.plan.added_lines), existed=target.plan.existed, runs=runs, seeds=result.seeds,
            victim_failed_after=result.victim_failed_after, polluter=target.polluter_name,
            upstream=source.repo, commit=source.ref, base=base, log=log,
        )
        pr = gh.json("POST", f"/repos/{fork}/pulls", json={
            "title": f"Fix order dependence in {finding.test}", "head": branch, "base": base, "body": body})
        return FixResult(pr["html_url"], branch, base, result)
    finally:
        shutil.rmtree(work, ignore_errors=True)
