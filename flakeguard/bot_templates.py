"""Text the FlakeGuard bot posts on GitHub. Wording follows section 5.7 of the plan
(``console/src/pages/BotText.tsx`` is the reference page).

Pure Python and standard library only, so the workflow's posting script can load this file
without installing anything. Inputs are plain dictionaries (the ``findings.json`` rows).

Deliberate differences from the reference page, recorded in ``docs/DECISIONS.md`` (M4-12):

* A footnote names the scanned commit, the shuffled seeds and the Actions run, so the numbers
  in the comment can be traced.
"""

from __future__ import annotations

import re

MARKER_PR = "<!-- flakeguard-pr-comment -->"
MARKER_POST_MERGE = "<!-- flakeguard-post-merge -->"

_SHUFFLED = re.compile(r"^Shuffled order: failed in (\d+) of (\d+) runs?")
_VERDICT_LABEL = {"flaky": "Flaky", "real": "Real failure", "unknown": "Unknown, too few failures"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _rule_of_three(n: int) -> str:
    return (
        f"With 0 failures in {_plural(n, 'run')} the failure rate could still be as high as about "
        f"{round(300 / n)}% (the rule of three)."
    )


def _evidence_cell(f: dict) -> str:
    if f["verdict"] == "flaky":
        for bullet in f.get("evidence", []):
            m = _SHUFFLED.match(bullet)
            if m:
                return f"Failed {m.group(1)} of {m.group(2)} shuffled runs"
    m = re.search(r"failed in (\d+) of (\d+) runs?", f.get("summaryLine", ""))
    if m:
        return f"Failed {m.group(1)} of {m.group(2)} runs"
    return f.get("summaryLine", "")


def _verdict_cell(f: dict) -> str:
    label = _VERDICT_LABEL[f["verdict"]]
    if f["verdict"] == "flaky" and f.get("subtype"):
        return f"{label}, {f['subtype']}"
    return label


def _where(f: dict) -> str:
    plain = [c["text"] for c in f.get("lives", []) if c["tone"] == "plain"]
    read = [c["text"] for c in f.get("lives", []) if c["tone"] == "read"]
    write = [c["text"].removeprefix("written by ") for c in f.get("lives", []) if c["tone"] == "write"]
    text = " › ".join(plain + read)
    if write:
        text += f" ← {write[0]}"
    return text


def _footnote(commit: str | None, seeds: str | None, run_url: str | None, updated: bool) -> str:
    parts = []
    if commit:
        parts.append(f"Scanned commit {commit[:7]}")
    if seeds:
        parts.append(f"shuffled seeds {seeds}")
    if run_url:
        parts.append(f"[Actions run]({run_url})")
    lines = []
    if updated:
        lines.append("This comment is updated in place on every push.")
    if parts:
        lines.append(" · ".join(parts))
    return "\n\n".join(lines)


def _title(findings: list[dict]) -> str:
    counts = {v: sum(1 for f in findings if f["verdict"] == v) for v in ("flaky", "real", "unknown")}
    parts = []
    if counts["flaky"]:
        parts.append(_plural(counts["flaky"], "flaky test"))
    if counts["real"]:
        parts.append(_plural(counts["real"], "real failure"))
    if counts["unknown"]:
        parts.append(_plural(counts["unknown"], "test") + " that needs more evidence")
    title = "FlakeGuard · " + ", ".join(parts)
    return title + " found" if parts == [_plural(counts["flaky"], "flaky test")] else title


def pr_comment(
    findings: list[dict], *, shuffled_runs: int, commit: str | None = None,
    seeds: str | None = None, run_url: str | None = None,
) -> str:
    """The single comment on a pull request. Edited in place on every push."""
    foot = _footnote(commit, seeds, run_url, updated=True)
    if not findings:
        return (
            f"{MARKER_PR}\n## FlakeGuard · No evidence of flakiness in {_plural(shuffled_runs, 'shuffled run')}\n\n"
            f"This is not proof the tests are stable. {_rule_of_three(shuffled_runs)}\n\n{foot}\n"
        )
    rows = "\n".join(
        f"| `{f['test']}` | {_verdict_cell(f)} | {_evidence_cell(f)} |" for f in findings
    )
    out = [f"{MARKER_PR}\n## {_title(findings)}", "", "| Test | Verdict | Evidence |", "|---|---|---|", rows]
    for f in findings:
        if f["verdict"] == "flaky":
            out += ["", f"**{f['test']}**", "",
                    f"- **Why:** {f['why']}", f"- **Where:** {_where(f)}", f"- **Limits:** {f['limits']}"]
        elif f["verdict"] == "unknown":
            out += ["", f"**{f['test']}**", "", f"- **Why:** {f['why']}", f"- **Limits:** {f['limits']}"]
        else:
            out += ["", f"**{f['test']}**", "", f"- **Why:** {f['why']}",
                    f"- **Quarantine:** {f['quarantine']['reason'] or 'refused'}"]
    out += ["", commands_block(findings), "", foot, ""]
    return "\n".join(out)


def commands_block(findings: list[dict]) -> str:
    """The commands the comment offers. Only commands that can act on a finding here are listed."""
    flaky = [f for f in findings if f["verdict"] == "flaky"]
    lines = []
    if any(f.get("fix") for f in flaky):
        lines.append("/flakeguard fix")
    asked = (flaky or findings or [{"test": "this_test"}])[0]["test"]
    lines.append(f"/flakeguard ask why does {asked} fail?")
    quarantinable = [f for f in findings if f["quarantine"]["allowed"]]
    if quarantinable:
        lines.append(f"/flakeguard quarantine {quarantinable[0]['test']}")
    note = ""
    if lines[0] == "/flakeguard fix":
        note = ("\n\n`fix` checks the fix again and shows the diff in a reply. It does not open a pull request; "
                "the console's Propose fix PR button does.")
    return "**Reply to this comment with**\n\n```\n" + "\n".join(lines) + "\n```" + note


def did_not_finish(*, run_url: str | None, reason: str | None = None, post_merge: bool = False) -> str:
    """Posted when the scan did not finish. It states no verdict."""
    marker = MARKER_POST_MERGE if post_merge else MARKER_PR
    head = "FlakeGuard post-merge check · The scan stopped early" if post_merge else "FlakeGuard · The scan stopped early"
    text = "No verdict is shown because the run did not finish."
    if reason:
        text += f" {reason}"
    text += " Open the run on GitHub to see why."
    link = f"\n\n[Open the Actions run]({run_url})" if run_url else ""
    return f"{marker}\n## {head}\n\n{text}{link}\n"


def post_merge_comment(
    findings: list[dict], *, shuffled_runs: int, commit: str | None = None,
    seeds: str | None = None, run_url: str | None = None,
) -> str:
    """Posted after a merge. Never says 'fixed' or 'stable'."""
    foot = _footnote(commit, seeds, run_url, updated=False)
    if not findings:
        return (
            f"{MARKER_POST_MERGE}\n## FlakeGuard post-merge check\n\n"
            f"No evidence of flakiness in {_plural(shuffled_runs, 'run')} after this change.\n\n"
            "This is not proof it is fixed. If the scan does not finish, this comment says so and shows no verdict.\n\n"
            f"{_rule_of_three(shuffled_runs)}\n\n{foot}\n"
        )
    rows = "\n".join(f"| `{f['test']}` | {_verdict_cell(f)} | {_evidence_cell(f)} |" for f in findings)
    return (
        f"{MARKER_POST_MERGE}\n## FlakeGuard post-merge check\n\n"
        f"The scan after this change found {_plural(len(findings), 'test')} that failed.\n\n"
        f"| Test | Verdict | Evidence |\n|---|---|---|\n{rows}\n\n{foot}\n"
    )



def fix_pr(
    *, test: str, state: str, file: str, lines: int, existed: bool, runs: int, seeds: list[int],
    victim_failed_after: int, polluter: str, upstream: str, commit: str, base: str, log: list[str],
) -> str:
    """Description of a fix pull request opened on the fork. Sections follow the reference page."""
    verb = "Appends" if existed else "Adds"
    seed_text = f"seeds {seeds[0]} to {seeds[-1]}" if len(seeds) > 1 else f"seed {seeds[0]}"
    detail = "\n".join(log)
    return (
        f"## Fix order dependence in {test}\n\n"
        f"**What this changes**\n{verb} a fixture in `{file}` ({_plural(lines, 'line')}) that puts `{state}` back to "
        f"the value it had before each test, so no test can leave state behind.\n\n"
        f"**How it was checked**\n{_plural(runs, 'shuffled run')} ({seed_text}) with this change: `{test}` failed "
        f"in {victim_failed_after} of them, and no test that had not failed in the scan failed. The two-test repro "
        f"(`{polluter}` then `{test}`) failed before this change and passes now.\n\n"
        f"<details><summary>Validation log</summary>\n\n```\n{detail}\n```\n\n</details>\n\n"
        "**What it does not prove**\nThat the code is correct in orders that were not run.\n\n"
        "**How to undo**\nRevert this pull request. Nothing else is touched.\n\n"
        "**Who merges**\nA person. FlakeGuard opened this on the fork and will not merge it.\n\n"
        f"Base branch `{base}` is a copy of `{upstream}` at `{commit[:7]}`, the commit that was scanned.\n"
    )


def quarantine_issue(
    *, test: str, file: str, line: int, why: str, evidence: list[str], requester: str, run_url: str | None,
) -> str:
    """Body of the tracking issue. Nothing is skipped or deleted; a person decides what to do."""
    bullets = "\n".join(f"- {e}" for e in evidence)
    link = f"\n\n[FlakeGuard run]({run_url})" if run_url else ""
    return (
        f"FlakeGuard was asked by @{requester} to quarantine `{test}` (`{file}:{line}`).\n\n"
        f"**Why:** {why}\n\n**Evidence**\n{bullets}\n\n"
        "This issue only tracks the test. No test was skipped, marked or deleted." + link + "\n"
    )


def quarantine_refused(*, test: str, reason: str) -> str:
    return (
        f"## Not quarantined: {test}\n\n{reason}\n\n"
        "Quarantine also needs write access to the repository. Requests from anyone without it are declined.\n"
    )


def declined_no_write_access(*, login: str, command: str) -> str:
    return (
        f"## FlakeGuard declined `{command}`\n\n"
        f"@{login} does not have write access to this repository, so nothing was run and nothing was changed.\n"
    )


def ask_reply(*, question: str, text: str, citations: list[str], chunks: int) -> str:
    """Answer to ``/flakeguard ask``. With nothing retrieved it says so and answers nothing."""
    if chunks == 0:
        return (
            "## FlakeGuard\n\n"
            f"No code matching this question was found, so there is no answer. Question: {question}\n"
        )
    cites = ", ".join(f"`{c}`" for c in citations)
    return (
        f"## FlakeGuard\n\n{text}\n\nCode cited: {cites}\n\n"
        f"Answered from {_plural(chunks, 'retrieved code chunk')}. If nothing relevant is found, the answer says so.\n"
    )


def fix_validated_reply(*, test: str, file: str, diff: list[str], checked: str) -> str:
    """Answer to ``/flakeguard fix`` when the fix passed validation. No pull request is opened from CI."""
    code = "\n".join(diff)
    return (
        f"## FlakeGuard · A fix for {test} passed validation\n\n"
        f"**Checked before showing it:** {checked}\n\n"
        f"Proposed change to `{file}`:\n\n```diff\n{code}\n```\n\n"
        "No pull request was opened. A fix pull request is opened on the fork of the person asking, which needs "
        "that person's own credential, and this workflow does not have one. Open it with **Propose fix PR** in the "
        "FlakeGuard console, or apply the change above by hand. A person merges it; FlakeGuard never does.\n"
    )


def fix_unavailable_reply(*, test: str, reason: str) -> str:
    return f"## FlakeGuard · No fix for {test}\n\n{reason}\n\nNothing was changed.\n"


def unknown_command_reply(*, command: str) -> str:
    return (
        f"## FlakeGuard did not understand `{command}`\n\n"
        "Commands: `/flakeguard fix`, `/flakeguard ask <question>`, `/flakeguard quarantine <test name>`.\n"
    )


def no_scan_reply(*, command: str) -> str:
    return (
        f"## FlakeGuard could not run `{command}`\n\n"
        "No finished FlakeGuard scan was found for the latest commit of this pull request, so there are no findings "
        "to act on. Nothing was changed.\n"
    )
