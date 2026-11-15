from flakeguard.gen.fix import propose_teardown_fix


def test_propose_teardown_fix(tmp_path):
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_polluter(): pass\n", encoding="utf-8")

    res = propose_teardown_fix(
        polluter_test_id="test_polluter",
        leaked_state_var="GLOBAL_REGISTRY",
        test_file_path=test_file,
    )
    assert res["status"] == "ready_for_review"
    assert "GLOBAL_REGISTRY.clear()" in res["proposed_fixture"]
    assert "@pytest.fixture(autouse=True)" in res["proposed_fixture"]

