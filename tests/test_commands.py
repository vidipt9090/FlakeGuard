"""Slash commands and the GitHub-facing helpers, with GitHub replaced by a mock transport."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter

from flakeguard.console import commands, forge
from flakeguard.console import models as m

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "data" / "demo_inventory"
RECORDED = REPO / "recorded" / "run-2026-11-21-002"
SOURCE = m.SourceRef(repo="vidipt9090/flakeguard-demo", ref="cfd9e3612364b50021699ac8536248c740720cce")


@pytest.fixture(scope="module")
def findings() -> list[m.Finding]:
    return TypeAdapter(list[m.Finding]).validate_json((RECORDED / "findings.json").read_text(encoding="utf-8"))


def gh(handler) -> forge.GitHub:
    return forge.GitHub("test-token", transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------------- parsing


def test_parse_command_reads_only_the_first_line():
    assert commands.parse_command("/flakeguard fix\nthanks").name == "fix"
    c = commands.parse_command("/flakeguard ask why is this order-dependent?")
    assert (c.name, c.arg) == ("ask", "why is this order-dependent?")
    c = commands.parse_command("/flakeguard quarantine test_report_total")
    assert (c.name, c.arg) == ("quarantine", "test_report_total")


def test_parse_command_ignores_other_comments_and_flags_unknown_commands():
    assert commands.parse_command("looks good") is None
    assert commands.parse_command("") is None
    assert commands.parse_command("please /flakeguard fix") is None
    assert commands.parse_command("/flakeguardx fix") is None
    with pytest.raises(ValueError):
        commands.parse_command("/flakeguard merge")


# ----------------------------------------------------------------------------- permissions


def test_can_write_follows_the_collaborator_permission():
    def answer(permission: str):
        return gh(lambda r: httpx.Response(200, json={"permission": permission}))

    assert forge.can_write(answer("admin"), "o/r", "u") and forge.can_write(answer("write"), "o/r", "u")
    assert not forge.can_write(answer("read"), "o/r", "u") and not forge.can_write(answer("none"), "o/r", "u")
    assert not forge.can_write(gh(lambda r: httpx.Response(404, json={"message": "Not Found"})), "o/r", "u")
    with pytest.raises(forge.ForgeError):
        forge.can_write(gh(lambda r: httpx.Response(500, json={})), "o/r", "u")


def test_authorize_declines_a_commenter_without_write_access_and_runs_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMENT_BODY", "/flakeguard quarantine test_report_total")
    monkeypatch.setenv("ACTOR", "stranger")
    monkeypatch.setenv("REPO", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    client = gh(lambda r: httpx.Response(200, json={"permission": "read"}))  # built before the patch
    monkeypatch.setattr(forge, "GitHub", lambda token: client)
    reply = tmp_path / "reply.md"
    assert commands.main(["authorize", "--reply", str(reply)]) == 0
    text = reply.read_text(encoding="utf-8")
    assert "@stranger does not have write access" in text and "nothing was run and nothing was changed" in text


def test_handle_refuses_to_run_when_a_token_is_in_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMENT_BODY", "/flakeguard ask why")
    monkeypatch.setenv("GH_TOKEN", "t")
    code = commands.main(["handle", "--findings", str(tmp_path / "none.json"), "--reply", str(tmp_path / "r.md")])
    assert code == 2 and not (tmp_path / "r.md").exists()


# ------------------------------------------------------------------------------- decisions


def test_quarantine_is_refused_for_real_and_unknown_findings_and_allowed_for_flaky(findings):
    real = commands.decide(commands.Command("quarantine", "test_reserve_negative", ""), findings, None)
    assert "A real failure cannot be quarantined" in real.reply and real.issue_for is None
    unknown = commands.decide(commands.Command("quarantine", "test_sync_timeout", ""), findings, None)
    assert "Too few failures" in unknown.reply and unknown.issue_for is None
    flaky = commands.decide(commands.Command("quarantine", "test_report_total", ""), findings, None)
    flaky_finding = next(f for f in findings if f.test == "test_report_total")
    assert flaky.issue_for == flaky_finding.id and flaky.reply == ""
    missing = commands.decide(commands.Command("quarantine", "test_nope", ""), findings, None)
    assert "no finding for that test" in missing.reply and missing.issue_for is None


def test_any_command_without_a_finished_scan_says_so_and_changes_nothing():
    for name, arg in (("fix", ""), ("ask", "why"), ("quarantine", "test_x")):
        d = commands.decide(commands.Command(name, arg, f"/flakeguard {name}"), [], FIXTURE)
        assert "No finished FlakeGuard scan" in d.reply and d.issue_for is None


def test_ask_answers_from_the_code_with_citations_and_says_nothing_when_nothing_matches(findings):
    answer = commands.decide(commands.Command("ask", "Why does CACHE matter here?", ""), findings, FIXTURE)
    assert "Code cited:" in answer.reply and "cache.py" in answer.reply
    nothing = commands.decide(commands.Command("ask", "xyzzy plugh frobnicate", ""), findings, FIXTURE)
    assert "there is no answer" in nothing.reply


def test_fix_without_a_validated_fix_in_the_scan_is_refused_with_a_reason(findings):
    d = commands.decide(commands.Command("fix", "", "/flakeguard fix"), findings, FIXTURE)
    assert "no validated fix" in d.reply and "```diff" not in d.reply


def test_fix_is_validated_again_and_never_opens_a_pull_request(findings):
    flaky = next(f for f in findings if f.verdict == "flaky")
    preview = m.FixPreview(summary="s", file="tests/conftest.py", diff=["+x"], checked="c", doesNotProve="d")
    with_fix = [flaky.model_copy(update={"fix": preview}), *[f for f in findings if f is not flaky]]
    d = commands.decide(commands.Command("fix", "", "/flakeguard fix"), with_fix, FIXTURE, validate_runs=2)
    assert "passed validation" in d.reply and "```diff" in d.reply and "autouse" in d.reply
    assert "No pull request was opened" in d.reply and d.issue_for is None


# -------------------------------------------------------------------------------- forge


def test_open_fix_pr_refuses_when_there_is_no_fork_or_it_is_not_a_fork_of_the_scanned_repo(findings):
    flaky = next(f for f in findings if f.verdict == "flaky")
    with pytest.raises(forge.ForgeError, match="has no fork"):
        forge.open_fix_pr(SOURCE, flaky, set(), fork_owner="someone", token="t",
                          gh=gh(lambda r: httpx.Response(404, json={"message": "Not Found"})))
    unrelated = {"fork": True, "parent": {"full_name": "other/repo"}}
    with pytest.raises(forge.ForgeError, match="is not a fork of"):
        forge.open_fix_pr(SOURCE, flaky, set(), fork_owner="someone", token="t",
                          gh=gh(lambda r: httpx.Response(200, json=unrelated)))
    not_a_fork = {"fork": False, "parent": None}
    with pytest.raises(forge.ForgeError, match="is not a fork of"):
        forge.open_fix_pr(SOURCE, flaky, set(), fork_owner="someone", token="t",
                          gh=gh(lambda r: httpx.Response(200, json=not_a_fork)))


def test_quarantine_issue_names_the_requester_and_changes_no_test(findings):
    flaky = next(f for f in findings if f.verdict == "flaky")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/9"})

    url = forge.open_quarantine_issue(gh(handler), "o/r", flaky, requester="maint", run_url="https://x/run/1")
    assert url.endswith("/issues/9") and seen["title"] == "Flaky test: test_report_total"
    assert "@maint" in seen["body"] and "No test was skipped, marked or deleted" in seen["body"]
