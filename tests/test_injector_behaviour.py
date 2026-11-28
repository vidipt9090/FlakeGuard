"""The injected faults behave as their labels say, checked by running the mutated code (not by reading its text).

A fault labelled flaky must fail sometimes and pass sometimes, or fail only when something outside the test (the order of
tests, the clock) changes. This is the check that the first timing operator would have failed: it failed every time.
"""

import ast

import pytest
from freezegun import freeze_time

from flakeguard.injector.operators import (
    OrderDependenceOperator,
    RandomnessOperator,
    RealFailureOperator,
    SharedStateOperator,
    SleepRaceOperator,
    TimeTZOperator,
    find_function,
)

SRC = "def test_x():\n    assert True\n"


def load(mutation, name="test_x", ns=None):
    ns = {} if ns is None else ns
    exec(mutation.mutated_code, ns)
    return ns[name]


def failures(fn, times):
    failed = 0
    for _ in range(times):
        try:
            fn()
        except AssertionError:
            failed += 1
    return failed


def test_timing_race_is_intermittent_not_deterministic():
    fn = load(SleepRaceOperator().apply(SRC, "test_x"))
    failed = failures(fn, 60)
    assert 0 < failed < 60, f"failed {failed} of 60: a race must both pass and fail"


def test_randomness_fails_about_fifteen_percent_of_the_time():
    fn = load(RandomnessOperator().apply(SRC, "test_x"))
    failed = failures(fn, 2000)
    assert 200 <= failed <= 400, f"failed {failed} of 2000, expected about 300"


def test_time_tz_depends_on_the_clock_and_only_on_the_clock():
    fn = load(TimeTZOperator().apply(SRC, "test_x"))
    with freeze_time("2026-11-23 12:00:00"):
        assert failures(fn, 5) == 0
    for night in ("2026-11-23 23:00:00", "2026-11-23 03:00:00"):
        with freeze_time(night):
            assert failures(fn, 5) == 5


def test_shared_state_only_the_first_mutated_test_of_a_module_passes():
    op = SharedStateOperator()
    ns: dict = {}
    first = load(op.apply(SRC, "test_x"), ns=ns)
    second = load(op.apply(SRC.replace("test_x", "test_y"), "test_y"), "test_y", ns=ns)
    first()  # the first one to run sees the counter at 1
    assert failures(second, 3) == 3  # every later one fails, every time
    assert failures(first, 3) == 3
    fresh: dict = {}
    assert failures(load(op.apply(SRC, "test_x"), ns=fresh), 1) == 0  # a new process starts clean


def test_order_dependence_passes_only_after_its_setup_test():
    op = OrderDependenceOperator()
    ns: dict = {}
    victim = load(op.apply(SRC.replace("test_x", "test_victim"), "test_victim"), "test_victim", ns=ns)
    setup_src = op.apply_setup(SRC.replace("test_x", "test_setup"), "test_setup")
    setup_ns = {}
    exec(setup_src, ns)
    assert failures(victim, 1) == 1  # setup has not run in this process
    ns["test_setup"]()
    assert failures(victim, 5) == 0
    assert failures(load(op.apply(SRC.replace("test_x", "test_victim"), "test_victim"), "test_victim", ns=setup_ns), 1) == 1


def test_real_failure_never_passes():
    assert failures(load(RealFailureOperator().apply(SRC, "test_x")), 50) == 50
    assert RealFailureOperator().apply(SRC, "test_x").label == "real_fail"


@pytest.mark.parametrize("op", [SleepRaceOperator(), SharedStateOperator(), RandomnessOperator(), TimeTZOperator(),
                                OrderDependenceOperator(), RealFailureOperator()])
def test_operators_work_on_a_method_with_a_docstring_and_leave_valid_code(op):
    src = (
        "import unittest\n\n\nclass CacheTest(unittest.TestCase):\n"
        "    def test_one(self):\n        '''doc'''\n        self.assertTrue(True)\n\n"
        "    def test_one_other(self):\n        self.assertTrue(True)\n"
    )
    mutation = op.apply(src, "test_one", "CacheTest")
    assert mutation is not None
    tree = ast.parse(mutation.mutated_code)  # still valid Python, correctly indented
    assert find_function(tree, "test_one", "CacheTest") is not None
    assert mutation.mutant_id.endswith("CacheTest_test_one")
    assert "self.assertTrue(True)" in mutation.mutated_code  # the original body is kept


def test_a_one_line_function_or_a_missing_name_is_refused_not_broken():
    assert RandomnessOperator().apply("def test_x(): pass\n", "test_x") is None
    assert RandomnessOperator().apply(SRC, "test_nope") is None
    assert RandomnessOperator().apply(SRC, "test_x", "NoSuchClass") is None
