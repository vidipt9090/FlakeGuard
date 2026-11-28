"""scripts/run_rq4.py: the parts whose silent failure would change a published number (no model is called here)."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_rq4", REPO / "scripts" / "run_rq4.py")
rq4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rq4)

needs_cache = pytest.mark.skipif(not (rq4.INJECTED / "labels.json").is_file() or not rq4.PRISTINE.is_dir(),
                                 reason="the injected suite is built by scripts/run_eval.py injected")


def test_scrub_removes_the_operator_comment_and_the_assert_message_and_nothing_else():
    messages = rq4._assert_messages()
    source = ("def test_x(self):\n"
              "    # Injected order dependence mutation by FlakeGuard (victim)\n"
              "    assert globals().get('_FLAKEGUARD_ORDER_READY') is True, 'Order dependence: the setup test has not run yet'\n"
              "    # an ordinary comment\n"
              "    assert 1 + 1 == 2, 'an ordinary message'\n")
    out = rq4.scrub(source, messages)
    assert "by FlakeGuard" not in out and "Order dependence:" not in out
    assert "assert globals().get('_FLAKEGUARD_ORDER_READY') is True\n" in out
    assert "# an ordinary comment" in out and "'an ordinary message'" in out


def test_a_reply_that_cannot_be_read_is_not_a_match():
    assert rq4.read_cause('{"cause": " Order_Dependence ", "reason": "x"}') == ("order_dependence", True)
    assert rq4.read_cause('{"cause": "race condition"}') == ("race condition", False)  # outside the six words
    assert rq4.read_cause("not json at all") == (None, False)
    assert rq4.read_cause('{"reason": "no cause field"}') == (None, False)
    assert rq4.read_cause("") == (None, False)


def test_every_label_has_a_word_in_the_vocabulary():
    assert set(rq4.CAUSE_WORD.values()) <= set(rq4.VOCAB) and "other" in rq4.VOCAB


def test_the_four_settings_and_the_frozen_prompt():
    assert rq4.SETTINGS == ("none", "file", "ast", "ast_jedi")
    assert rq4.DEFAULT_PROMPT == "v2"
    assert "v1" in rq4.PROMPTS  # the first version stays, because the tuning log refers to it


def test_a_fix_that_is_not_one_function_with_the_same_name_is_not_validated():
    labels, runs = [], []
    victim = "tests/test_x.py::XTest::test_a"
    assert not rq4.validate_fix(victim, "def broken(:", labels, runs)["validated"]
    assert rq4.validate_fix(victim, "def other(self):\n    pass\n", labels, runs)["reason"] == "the reply is not one function with the same name"
    assert "not valid python" in rq4.validate_fix(victim, "def test_a(self:\n", labels, runs)["reason"]


@needs_cache
def test_a_fix_that_drops_the_test_body_or_keeps_the_dependence_is_not_validated():
    labels = json.loads((rq4.INJECTED / "labels.json").read_text(encoding="utf-8"))
    runs = json.loads((REPO / "results" / "injected" / "perturbation.json").read_text(encoding="utf-8"))["runs"]
    manifest = json.loads((rq4.INJECTED / "manifest.json").read_text(encoding="utf-8"))
    victim = next(i["id"] for i in manifest["injections"] if i["category"] == "order_dep" and i["label"] == "flaky")
    _, _, name = rq4._victim_parts(victim)
    emptied = rq4.validate_fix(victim, f"def {name}(self):\n    pass\n", labels, runs)
    assert not emptied["validated"] and "of the original test body are gone" in emptied["reason"]
    assert rq4.proposer_applies(victim) is False  # the shared flag is set through `global`, not a module-level container
