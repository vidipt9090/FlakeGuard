"""The order-dependence fix: what it writes, and that validation can say no."""

from dataclasses import replace
from pathlib import Path

from flakeguard.console import fixer
from flakeguard.console.analysis import StateDef

FIXTURE = Path(__file__).parent / "data" / "demo_inventory"
STATE = StateDef("CACHE", "src/inventory/cache.py", 3)
POLLUTER = "tests/test_warmup.py::test_cache_warm"
VICTIM = "tests/test_report.py::test_report_total"
KNOWN = {"tests/test_stock.py::test_reserve_negative", "tests/test_sync.py::test_sync_timeout"}


def test_plan_restores_a_shared_dict_from_a_conftest_autouse_fixture():
    plan = fixer.plan_fix(FIXTURE, STATE)
    assert plan is not None
    assert (plan.file, plan.kind, plan.module, plan.existed) == ("tests/conftest.py", "dict", "inventory.cache", False)
    assert "@pytest.fixture(autouse=True)" in plan.appended
    assert "before = dict(_flakeguard_cache.CACHE)" in plan.appended
    assert plan.added_lines[0] == "import pytest"


def test_plan_is_none_when_the_state_is_not_a_plain_collection(tmp_path):
    (tmp_path / "state.py").write_text("COUNTER = 3\nTABLE = {}\n", encoding="utf-8")
    assert fixer.plan_fix(tmp_path, StateDef("COUNTER", "state.py", 1)) is None
    assert fixer.plan_fix(tmp_path, StateDef("TABLE", "state.py", 2)).kind == "dict"  # type: ignore[union-attr]


def test_module_name_handles_src_layouts_and_packages():
    assert fixer.module_name("src/inventory/cache.py") == "inventory.cache"
    assert fixer.module_name("pkg/__init__.py") == "pkg"
    assert fixer.module_name("shared.py") == "shared"


def test_apply_appends_to_an_existing_conftest(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text("X = 1", encoding="utf-8")
    plan = replace(fixer.plan_fix(FIXTURE, STATE), existed=True)  # type: ignore[type-var]
    fixer.apply_fix(tmp_path, plan)
    text = (tmp_path / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert text.startswith("X = 1\n") and "_flakeguard_restore_cache" in text


def test_validation_passes_for_the_real_fix():
    plan = fixer.plan_fix(FIXTURE, STATE)
    log: list[str] = []
    v = fixer.validate_fix(FIXTURE, plan, polluter=POLLUTER, victim=VICTIM, known_failing=KNOWN, runs=3, log=log)  # type: ignore[arg-type]
    assert v.errors == [] and v.victim_failed_after == 0 and v.new_failures == {}
    assert v.pair_before_exit == 1 and v.pair_after_exit == 0 and v.passed
    assert any("pair with the fix" in line for line in log)


def test_validation_says_no_when_the_fix_does_nothing():
    noop = replace(fixer.plan_fix(FIXTURE, STATE), appended="\n# FlakeGuard test: no fixture\n")  # type: ignore[type-var]
    v = fixer.validate_fix(FIXTURE, noop, polluter=POLLUTER, victim=VICTIM, known_failing=KNOWN, runs=2)
    assert v.pair_after_exit == 1 and not v.passed
    assert "two-test repro still failed" in v.reason()
