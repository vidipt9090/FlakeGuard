"""scripts/run_eval.py helpers: the pieces whose silent failure would change a published number."""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_eval", REPO / "scripts" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def test_every_planted_test_has_its_source_text_for_the_code_features():
    labels = json.loads((REPO / "labels" / "labels.json").read_text(encoding="utf-8"))
    sources = run_eval._test_sources("planted")
    assert [x["id"] for x in labels if not sources.get(x["id"])] == []
    assert "time.sleep" in sources["synthetic/tests/test_suite_02.py::test_case_14"]


def test_the_code_features_change_the_feature_vector():
    labels = json.loads((REPO / "labels" / "labels.json").read_text(encoding="utf-8"))
    sources = run_eval._test_sources("planted")
    runs = [{"outcomes": {x["id"]: "PASS" for x in labels}, "durations": {x["id"]: 0.01 for x in labels}}] * 3
    with_code = run_eval._features(labels, runs, sources, True)
    without = run_eval._features(labels, runs, sources, False)
    assert any(a.to_array().tolist() != b.to_array().tolist() for a, b in zip(with_code, without))


def test_wilson_interval_and_classification_words():
    assert run_eval.wilson(0, 0) == [None, None]
    low, high = run_eval.wilson(3, 3)
    assert 0.4 < low < 0.5 and high == 1.0
    assert run_eval.classify(["PASS", "FAIL"]) == "flaky"
    assert run_eval.classify(["FAIL", "FAIL"]) == "real"
    assert run_eval.classify(["PASS", "PASS"]) == "none_seen"  # never "stable"
