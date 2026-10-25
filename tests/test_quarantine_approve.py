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
