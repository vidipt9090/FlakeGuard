"""Text the FlakeGuard bot posts on GitHub. Wording follows section 5.7 of the plan
(``console/src/pages/BotText.tsx`` is the reference page).

Pure Python and standard library only, so the workflow's posting script can load this file
without installing anything. Inputs are plain dictionaries (the ``findings.json`` rows).

Deliberate differences from the reference page, recorded in ``docs/DECISIONS.md`` (M4-12):

* The "Reply to this comment with /flakeguard ..." block is left out. Those commands do not
  exist yet, and the comment must not promise them.
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
    out += ["", foot, ""]
    return "\n".join(out)


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
