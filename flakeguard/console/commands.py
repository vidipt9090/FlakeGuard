"""Slash commands on a pull request (CI-7): ``/flakeguard fix``, ``ask <question>``, ``quarantine <test>``.

Run by ``.github/workflows/commands.yml`` in small steps so that no step that runs the pull
request's code holds a write token:

* ``authorize``  checks that the commenter has write access (the only step that must decide before anything else);
* ``handle``     reads the findings of the latest finished scan and writes ``reply.md`` (no token is set);
* ``open-issue`` opens the quarantine tracking issue, only when ``handle`` decided one is allowed.

The reply is posted by the workflow. Nothing here merges, pushes or opens a pull request.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from flakeguard import bot_templates
from flakeguard.console import fixer, forge
from flakeguard.console import models as m
from flakeguard.console.ask import answer_question

PREFIX = "/flakeguard"
_COMMAND = re.compile(r"^/flakeguard[ \t]+(fix|ask|quarantine)\b[ \t]*(.*)$")


@dataclass
class Command:
    name: str  # fix, ask or quarantine
    arg: str
    text: str  # the first line, as typed


def parse_command(body: str) -> Command | None:
    """The command on the first line of a comment, or None when the comment is not addressed to FlakeGuard.

    ``ValueError`` means the comment starts with ``/flakeguard`` but is not a command we know.
    """
    first = (body or "").strip().splitlines()[0].strip() if (body or "").strip() else ""
    if first != PREFIX and not first.startswith(PREFIX + " ") and not first.startswith(PREFIX + "\t"):
        return None
    found = _COMMAND.match(first)
    if found is None:
        raise ValueError(first[:200])
    return Command(found.group(1), found.group(2).strip(), first[:200])


@dataclass
class Decision:
    reply: str
    issue_for: str | None = None  # finding id to open a quarantine issue for


def decide(
    cmd: Command, findings: list[m.Finding], repo: Path | None, *, validate_runs: int = fixer.DEFAULT_RUNS,
    source: m.SourceRef | None = None,
) -> Decision:
    """Turn a command and the scan's findings into the reply. Quarantine only says whether an issue may be opened."""
    if cmd.name == "ask":
        if not cmd.arg:
            return Decision(bot_templates.ask_reply(question="", text="", citations=[], chunks=0))
        if not findings or repo is None:
            return Decision(bot_templates.no_scan_reply(command=cmd.text))
        target = next((f for f in findings if f.verdict == "flaky"), findings[0])
        answer = answer_question(repo, target, cmd.arg)
        return Decision(bot_templates.ask_reply(
            question=cmd.arg, text=answer.text, citations=[c.label for c in answer.citations], chunks=answer.chunks))

    if not findings:
        return Decision(bot_templates.no_scan_reply(command=cmd.text))

    if cmd.name == "quarantine":
        match = next((f for f in findings if f.test == cmd.arg), None)
        if match is None:
            names = ", ".join(f"`{f.test}`" for f in findings)
            return Decision(bot_templates.fix_unavailable_reply(
                test=cmd.arg or "(no test named)", reason=f"The latest scan has no finding for that test. Findings: {names}."))
        refusal = forge.quarantine_refusal(match)
        if refusal:
            return Decision(bot_templates.quarantine_refused(test=match.test, reason=refusal))
        return Decision("", issue_for=match.id)

    # fix
    target = next((f for f in findings if f.verdict == "flaky" and f.fix is not None), None)
    if target is None or target.fix is None:
        flaky = next((f for f in findings if f.verdict == "flaky"), None)
        name = flaky.test if flaky else "this pull request"
        return Decision(bot_templates.fix_unavailable_reply(
            test=name, reason="The latest scan has no validated fix. FlakeGuard only proposes a fix for an "
                              "order-dependent test, and only after the fix passed validation."))
    if repo is None:
        return Decision(bot_templates.no_scan_reply(command=cmd.text))
    try:
        located = forge.locate_fix(repo, target)
        known = {f"{f.file}::{f.test}" for f in findings}
        test_dir = target.file.split("/")[0] if "/" in target.file else "."
        result = fixer.validate_fix(
            repo, located.plan, polluter=located.polluter_id, victim=located.victim_id, known_failing=known,
            test_dir=test_dir, runs=validate_runs)
    except forge.ForgeError as e:
        return Decision(bot_templates.fix_unavailable_reply(test=target.test, reason=str(e)))
    if not result.passed:
        return Decision(bot_templates.fix_unavailable_reply(
            test=target.test, reason=f"The fix was tried again on this commit and did not pass validation: {result.reason()}."))
    return Decision(bot_templates.fix_validated_reply(
        test=target.test, file=located.plan.file, diff=[f"+{x}" for x in located.plan.added_lines],
        checked=f"{result.victim_failed_after} failures of {target.test} in {len(result.seeds)} shuffled runs "
                f"(seeds {result.seeds[0]} to {result.seeds[-1]}) with the fix, and the two-test repro that failed "
                "before now passes."))


# ------------------------------------------------------------------------------------ CLI


def _output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    line = f"{name}={value}\n"
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    print(line, end="")


def cmd_authorize(args: argparse.Namespace) -> int:
    body, actor, repo = os.environ["COMMENT_BODY"], os.environ["ACTOR"], os.environ["REPO"]
    try:
        cmd = parse_command(body)
    except ValueError as e:
        Path(args.reply).write_text(bot_templates.unknown_command_reply(command=str(e)), encoding="utf-8")
        _output("command", "unknown")
        _output("allowed", "true")  # an unknown command changes nothing; the usage reply is safe for anyone with access
        return 0
    if cmd is None:
        _output("command", "")
        _output("allowed", "false")
        return 0
    _output("command", cmd.name)
    gh = forge.GitHub(os.environ["GH_TOKEN"])
    if forge.can_write(gh, repo, actor):
        _output("allowed", "true")
        return 0
    Path(args.reply).write_text(bot_templates.declined_no_write_access(login=actor, command=cmd.text), encoding="utf-8")
    _output("allowed", "declined")
    return 0


def _load_findings(path: Path) -> list[m.Finding]:
    if not path.is_file():
        return []
    return TypeAdapter(list[m.Finding]).validate_json(path.read_text(encoding="utf-8"))


def cmd_handle(args: argparse.Namespace) -> int:
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        print("handle must run without a token: it may run the pull request's code", file=sys.stderr)
        return 2
    cmd = parse_command(os.environ["COMMENT_BODY"])
    assert cmd is not None
    checkout = Path(args.checkout) if args.checkout and Path(args.checkout).is_dir() else None
    decision = decide(cmd, _load_findings(Path(args.findings)), checkout)
    Path(args.reply).write_text(decision.reply, encoding="utf-8")
    _output("issue_for", decision.issue_for or "")
    return 0


def cmd_open_issue(args: argparse.Namespace) -> int:
    repo, actor = os.environ["REPO"], os.environ["ACTOR"]
    finding = next(f for f in _load_findings(Path(args.findings)) if f.id == args.finding_id)
    gh = forge.GitHub(os.environ["GH_TOKEN"])
    url = forge.open_quarantine_issue(gh, repo, finding, requester=actor, run_url=os.environ.get("RUN_URL") or None)
    Path(args.reply).write_text(
        f"## FlakeGuard · Quarantine tracking issue opened for {finding.test}\n\n{url}\n\n"
        "No test was skipped, marked or deleted. A person decides what happens next.\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="step", required=True)
    a = sub.add_parser("authorize")
    a.add_argument("--reply", required=True)
    h = sub.add_parser("handle")
    h.add_argument("--findings", required=True)
    h.add_argument("--checkout", default="")
    h.add_argument("--reply", required=True)
    o = sub.add_parser("open-issue")
    o.add_argument("--findings", required=True)
    o.add_argument("--finding-id", required=True)
    o.add_argument("--reply", required=True)
    args = ap.parse_args(argv)
    try:
        return {"authorize": cmd_authorize, "handle": cmd_handle, "open-issue": cmd_open_issue}[args.step](args)
    except forge.ForgeError as e:
        Path(args.reply).write_text(f"## FlakeGuard could not finish\n\n{e}\n\nNothing was changed.\n", encoding="utf-8")
        return 0


if __name__ == "__main__":
    sys.exit(main())
