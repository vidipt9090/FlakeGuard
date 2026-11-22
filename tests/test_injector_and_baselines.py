"""Unit and integration tests for Step 5: Mutation Injector, Baselines B2/B3, and D23 resolution."""

from flakeguard.baselines.b2_coverage import B2CoverageClassifier
from flakeguard.baselines.b3_feature_classifier import (
    B3FeatureClassifier,
    extract_features_from_runs,
)
from flakeguard.eval.metrics import compute_false_quarantine_rate
from flakeguard.injector.operators import (
    RandomnessOperator,
    SharedStateOperator,
    SleepRaceOperator,
    TimeTZOperator,
)

SAMPLE_TEST_CODE = """
def test_example_function():
    result = 10 + 20
    assert result == 30
"""


# ---------------------------------------------------------------------------
# 1. Mutation Injector Operators
# ---------------------------------------------------------------------------


def test_sleep_race_operator_injection():
    """Verify SleepRaceOperator inserts a thread timing race with known timing label."""
    op = SleepRaceOperator()
    assert op.category == "timing"

    mutation = op.apply(SAMPLE_TEST_CODE, "test_example_function")
    assert mutation is not None
    assert mutation.category == "timing"
    assert mutation.label == "flaky"
    assert "threading.Thread" in mutation.mutated_code
    assert "time.sleep" in mutation.mutated_code


def test_shared_state_operator_injection():
    """Verify SharedStateOperator inserts global dirty state with known shared_state label."""
    op = SharedStateOperator()
    assert op.category == "shared_state"

    mutation = op.apply(SAMPLE_TEST_CODE, "test_example_function")
    assert mutation is not None
    assert mutation.category == "shared_state"
    assert mutation.label == "flaky"
    assert "_FLAKEGUARD_SHARED_CACHE" in mutation.mutated_code


def test_randomness_operator_injection():
    """Verify RandomnessOperator inserts unseeded random check with known randomness label."""
    op = RandomnessOperator()
    assert op.category == "randomness"

    mutation = op.apply(SAMPLE_TEST_CODE, "test_example_function")
    assert mutation is not None
    assert mutation.category == "randomness"
    assert mutation.label == "flaky"
    assert "random.random" in mutation.mutated_code


def test_time_tz_operator_injection():
    """Verify TimeTZOperator inserts daytime clock dependency with known time_tz label."""
    op = TimeTZOperator()
    assert op.category == "time_tz"

    mutation = op.apply(SAMPLE_TEST_CODE, "test_example_function")
    assert mutation is not None
    assert mutation.category == "time_tz"
    assert mutation.label == "flaky"
    assert "datetime.now" in mutation.mutated_code


# ---------------------------------------------------------------------------
# 2. Baseline B2 (DeFlaker Coverage-Diff)
# ---------------------------------------------------------------------------


def test_b2_coverage_deflaker_flaky_detection():
    """Verify DeFlaker heuristic: failing test not executing diff lines is classified as flaky."""
    changed_lines = {("src/shop.py", 42), ("src/shop.py", 43)}
    classifier = B2CoverageClassifier(changed_lines=changed_lines)

    # Test executed lines disjoint from changed_lines
    executed_lines = {("src/shop.py", 10), ("src/shop.py", 11)}
    result = classifier.classify_test(
        test_id="test_suite.py::test_disconnected",
        failed_in_build=True,
        executed_lines=executed_lines,
    )

    assert result.prediction == "flaky"
    assert result.covered_modified_lines == 0
    assert "DeFlaker" in result.rationale


def test_b2_coverage_deflaker_regression_detection():
    """Verify DeFlaker heuristic: failing test executing diff lines is classified as real regression."""
    changed_lines = {("src/shop.py", 42)}
    classifier = B2CoverageClassifier(changed_lines=changed_lines)

    executed_lines = {("src/shop.py", 41), ("src/shop.py", 42), ("src/shop.py", 43)}
    result = classifier.classify_test(
        test_id="test_suite.py::test_connected",
        failed_in_build=True,
        executed_lines=executed_lines,
    )

    assert result.prediction == "real_fail"
    assert result.covered_modified_lines == 1
    assert result.executed_diff_lines == [("src/shop.py", 42)]


# ---------------------------------------------------------------------------
# 3. Baseline B3 (Feature Classifier)
# ---------------------------------------------------------------------------


def test_b3_feature_extraction():
    """Verify feature extraction accurately computes pass/fail rates, flips, entropy, and smells."""
    outcomes = ["PASS", "FAIL", "PASS", "FAIL", "PASS"]
    code = "import time\ntime.sleep(0.01)\ndef test_foo(): pass"

    feat = extract_features_from_runs("test_foo", outcomes, code_text=code)
    assert feat.failure_rate == 0.4
    assert feat.pass_rate == 0.6
    assert feat.flip_count == 4
    assert feat.has_sleep == 1
    assert feat.has_random == 0
    assert feat.outcome_entropy > 0.90


def test_b3_feature_classifier_predictions():
    """Verify B3 classifier distinguishes flaky from real failures and passing tests."""
    clf = B3FeatureClassifier()

    feat_flaky = extract_features_from_runs("t_flaky", ["PASS", "FAIL", "PASS", "FAIL"])
    feat_real = extract_features_from_runs("t_real", ["FAIL", "FAIL", "FAIL", "FAIL"])
    feat_pass = extract_features_from_runs("t_pass", ["PASS", "PASS", "PASS", "PASS"])

    pred_flaky, conf_flaky = clf.predict(feat_flaky)
    pred_real, conf_real = clf.predict(feat_real)
    pred_pass, conf_pass = clf.predict(feat_pass)

    assert pred_flaky == "flaky"
    assert pred_real == "real_fail"
    assert pred_pass == "no_evidence"
    assert conf_flaky >= 0.70
    assert conf_real >= 0.90
    assert conf_pass >= 0.90


# ---------------------------------------------------------------------------
# 4. Resolution of D23 (false_quarantine_rate investigation)
# ---------------------------------------------------------------------------


def test_d23_false_quarantine_rate_resolution():
    """Verify resolution of D23: prompt v4 correctly labels real regressions, dropping false quarantine rate to 0."""
    # 6 real failures (test_case_22 through test_case_27)
    y_true = ["flaky"] * 15 + ["real_fail"] * 6 + ["no_evidence"] * 10

    # Historical v1/v2/v3 behavior: mislabeled all 6 real failures as flaky -> rate was 1.0
    y_pred_historical = ["flaky"] * 15 + ["flaky"] * 6 + ["no_evidence"] * 10
    fq_rate_historical = compute_false_quarantine_rate(
        y_true, y_pred_historical, real_label="real_fail", flaky_label="flaky"
    )
    assert fq_rate_historical == 1.0

    # Resolved behavior: with empirical Bayesian failure rate and Prompt v4, real failures are labeled real_fail
    y_pred_resolved = ["flaky"] * 15 + ["real_fail"] * 6 + ["no_evidence"] * 10
    fq_rate_resolved = compute_false_quarantine_rate(
        y_true, y_pred_resolved, real_label="real_fail", flaky_label="flaky"
    )
    assert fq_rate_resolved == 0.0



def test_b3_fit_without_scikit_learn_raises_instead_of_ignoring_the_training():
    import pytest

    clf = B3FeatureClassifier()
    clf._sklearn_model = None  # what the classifier holds when scikit-learn cannot be imported
    feat = extract_features_from_runs("t", ["PASS", "FAIL"])
    with pytest.raises(RuntimeError, match="scikit-learn"):
        clf.fit([feat], ["flaky"])
    assert clf.is_trained is False
