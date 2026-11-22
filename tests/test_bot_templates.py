"""Snapshots of the text the bot posts. Inputs are real findings from the recorded demo-repo run.

If the wording changes on purpose, regenerate: ``python tests/test_bot_templates.py --update``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from flakeguard import bot_templates as bt

DATA = Path(__file__).parent / "data" / "bot_snapshots"
FINDINGS = json.loads((DATA / "findings_input.json").read_text(encoding="utf-8"))
URL = "https://github.com/vidipt9090/flakeguard-demo/actions/runs/1"
COMMIT = "cfd9e3612364b50021699ac8536248c740720cce"

CASES = {
    "pr_comment": lambda: bt.pr_comment(FINDINGS, shuffled_runs=10, commit=COMMIT, seeds="1 to 10", run_url=URL),
    "pr_comment_flaky_only": lambda: bt.pr_comment(
        [f for f in FINDINGS if f["verdict"] == "flaky"], shuffled_runs=10, commit=COMMIT, seeds="1 to 10", run_url=URL),
    "pr_comment_no_findings": lambda: bt.pr_comment([], shuffled_runs=10, commit=COMMIT, seeds="1 to 10", run_url=URL),
    "pr_comment_did_not_finish": lambda: bt.did_not_finish(run_url=URL),
    "post_merge_no_findings": lambda: bt.post_merge_comment([], shuffled_runs=10, commit=COMMIT, seeds="1 to 10", run_url=URL),
    "post_merge_findings": lambda: bt.post_merge_comment(FINDINGS, shuffled_runs=10, commit=COMMIT, seeds="1 to 10", run_url=URL),
    "post_merge_did_not_finish": lambda: bt.did_not_finish(run_url=URL, post_merge=True),
}  # the commands block is part of "pr_comment" and "pr_comment_flaky_only"


def test_every_snapshot_matches():
    for name, make in CASES.items():
        expected = (DATA / f"{name}.md").read_text(encoding="utf-8")
        assert make() == expected, f"{name} changed; run `python tests/test_bot_templates.py --update` if intended"


def test_every_comment_carries_its_marker_on_the_first_line():
    for name, make in CASES.items():
        first = make().splitlines()[0]
        assert first in (bt.MARKER_PR, bt.MARKER_POST_MERGE), name


def test_the_scan_that_did_not_finish_shows_no_verdict():
    text = bt.did_not_finish(run_url=URL)
    for word in ("Flaky", "Real failure", "No evidence", "stable"):
        assert word not in text


def test_never_says_fixed_stable_or_safe_as_a_claim():
    for name, make in CASES.items():
        text = make().lower()
        assert "is fixed" not in text.replace("not proof it is fixed", ""), name
        assert "tests are stable" not in text.replace("not proof the tests are stable", ""), name
        assert " safe" not in text, name


def test_rule_of_three_wording_uses_the_real_run_count():
    assert "about 30%" in bt.pr_comment([], shuffled_runs=10)
    assert "about 15%" in bt.pr_comment([], shuffled_runs=20)


def test_the_commands_block_lists_only_commands_that_can_act():
    flaky = [f for f in FINDINGS if f["verdict"] == "flaky"]
    with_fix = [{**flaky[0], "fix": {"summary": "x"}}]
    assert "/flakeguard fix" not in bt.commands_block(flaky)  # no validated fix, so none is offered
    assert "/flakeguard fix" in bt.commands_block(with_fix)
    assert "/flakeguard quarantine test_report_total" in bt.commands_block(flaky)
    real_only = [f for f in FINDINGS if f["verdict"] == "real"]
    assert "quarantine" not in bt.commands_block(real_only)
    assert "/flakeguard ask" in bt.commands_block(real_only)


def test_the_fix_command_is_described_as_showing_a_diff_not_opening_a_pull_request():
    flaky = [f for f in FINDINGS if f["verdict"] == "flaky"]
    block = bt.commands_block([{**flaky[0], "fix": {"summary": "x"}}])
    assert "shows the diff in a reply" in block and "does not open a pull request" in block
    assert "does not open a pull request" not in bt.commands_block(flaky)  # no fix offered, so no note


def test_no_findings_and_post_merge_comments_offer_no_commands():
    for name in ("pr_comment_no_findings", "post_merge_no_findings", "post_merge_findings", "pr_comment_did_not_finish"):
        assert "/flakeguard " not in CASES[name](), name  # the trailing space skips the repository name in links
    assert "/flakeguard ask" in CASES["pr_comment"]()


def test_fix_pr_description_has_the_reference_sections_and_no_overclaim():
    text = bt.fix_pr(test="test_report_total", state="CACHE", file="tests/conftest.py", lines=10, existed=True,
                     runs=20, seeds=list(range(1, 21)), victim_failed_after=0, polluter="test_cache_warm",
                     upstream="o/r", commit=COMMIT, base="flakeguard/base-cfd9e36", log=["with the fix, seed 1: exit 1"])
    for head in ("What this changes", "How it was checked", "What it does not prove", "How to undo", "Who merges"):
        assert f"**{head}**" in text
    assert "20 shuffled runs (seeds 1 to 20)" in text and "failed in 0 of them" in text
    assert "A person. FlakeGuard opened this on the fork and will not merge it." in text
    assert "is fixed" not in text and "stable" not in text and " safe" not in text


if __name__ == "__main__":
    if "--update" in sys.argv:
        DATA.mkdir(parents=True, exist_ok=True)
        for name, make in CASES.items():
            (DATA / f"{name}.md").write_text(make(), encoding="utf-8", newline="\n")
        print(f"wrote {len(CASES)} snapshots to {DATA}")
