"""Unit tests for quarantine approval logic, idempotency, and safety filtering."""

from scripts.approve_quarantine import append_to_quarantine


def test_append_to_quarantine_idempotent():
    db = {"quarantined_tests": []}
    test_ids = ["test_case_02", "test_case_04"]
    allowed = {"test_case_02", "test_case_04"}

    count1, added1 = append_to_quarantine(
        db, test_ids, label_author="alice", pr_number=17, timestamp="2026-10-25T00:00:00Z", allowed_flaky_ids=allowed
    )
    assert count1 == 2
    assert len(db["quarantined_tests"]) == 2

    # Second run with same test IDs must add 0 duplicate entries
    count2, added2 = append_to_quarantine(
        db, test_ids, label_author="alice", pr_number=17, timestamp="2026-10-25T00:01:00Z", allowed_flaky_ids=allowed
    )
    assert count2 == 0
    assert added2 == []
    assert len(db["quarantined_tests"]) == 2


def test_append_to_quarantine_filters_real_failures():
    db = {"quarantined_tests": []}
    # test_case_22 and test_case_23 are real bugs in labels.json
    test_ids = ["test_case_02", "test_case_22", "test_case_23"]
    allowed_flaky = {"test_case_02"}  # only test_case_02 is flaky

    count, added = append_to_quarantine(
        db, test_ids, label_author="bob", pr_number=18, timestamp="2026-10-25T00:00:00Z", allowed_flaky_ids=allowed_flaky
    )
    assert count == 1
    assert added == ["test_case_02"]
    assert db["quarantined_tests"][0]["test_id"] == "test_case_02"


def test_build_comment_body_live_triage_table():
    from scripts.post_triage_comment import build_comment_body

    failures = [{"name": "test_case_02", "classname": "tests.test_a", "message": "assert False"}]
    triage_results = [{
        "test_id": "tests.test_a::test_case_02",
        "label": "flaky",
        "root_cause": "order_dep",
        "evidence_tier": "reproduced",
        "confidence": 0.95,
        "reasoning": "Polluter bisection isolated test_case_01.",
    }]

    body = build_comment_body(
        failures=failures,
        run_url="https://github.com/example/repo/actions/runs/123",
        failed_at="2026-11-14T10:00:00Z",
        comment_at="2026-11-14T10:01:00Z",
        triage_results=triage_results,
        is_fork=False,
        provider_name="gemini-2.0-flash",
    )

    assert "FLAKY" in body
    assert "order_dep" in body
    assert "reproduced" in body
    assert "quarantine:approve" in body
    assert "Live LLM Triage (`gemini-2.0-flash`" in body


def test_build_comment_body_fork_pr_notice():
    from scripts.post_triage_comment import build_comment_body

    failures = [{"name": "test_case_22", "classname": "tests.test_b", "message": "error"}]
    triage_results = [{
        "test_id": "test_case_22",
        "label": "real_fail",
        "root_cause": "none",
        "evidence_tier": "none",
        "confidence": 0.99,
        "reasoning": "Deterministic bug.",
    }]

    body = build_comment_body(
        failures=failures,
        run_url="https://github.com/example/repo/actions/runs/124",
        failed_at="2026-11-14T10:00:00Z",
        comment_at="2026-11-14T10:01:00Z",
        triage_results=triage_results,
        is_fork=True,
    )

    assert "Fork PR detected" in body
    assert "REAL BUG" in body
    assert "Real code regressions cannot be quarantined" in body
