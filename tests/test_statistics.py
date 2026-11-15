"""Comprehensive unit and statistical validation tests for Step 3 Statistics."""

from flakeguard.stats.adaptive import AdaptiveStoppingPolicy, simulate_adaptive_run
from flakeguard.stats.bayesian import BayesianFailureRate, beta_cdf, beta_ppf
from flakeguard.stats.comparison import mcnemar_test, paired_bootstrap_comparison

# ---------------------------------------------------------------------------
# 1. Bayesian Failure Rate & Credible Intervals
# ---------------------------------------------------------------------------


def test_beta_cdf_and_ppf_accuracy():
    """Verify numerical beta CDF and quantile inversion accuracy."""
    a, b = 2.0, 5.0
    for p in [0.05, 0.25, 0.5, 0.75, 0.95]:
        x = beta_ppf(p, a, b)
        cdf_val = beta_cdf(x, a, b)
        assert abs(cdf_val - p) < 1e-4


def test_bayesian_failure_rate_flaky_test():
    """Verify Bayesian failure rate estimation and 95% credible interval for flaky test."""
    b = BayesianFailureRate(test_id="test_suite::test_flaky", runs=20, failures=5)
    assert b.runs == 20
    assert b.failures == 5
    assert b.passes == 15
    assert b.verdict == "flaky"

    # Posterior mean: (0.5 + 5) / (0.5 + 0.5 + 20) = 5.5 / 21 ≈ 0.2619
    assert abs(b.posterior_mean - (5.5 / 21.0)) < 1e-5

    ci = b.credible_interval(confidence=0.95)
    assert 0.0 < ci.lower < b.posterior_mean < ci.upper < 1.0
    assert ci.confidence == 0.95


def test_bayesian_zero_failures_wording_constraint():
    """CRITICAL RULE: Zero-failure tests must be worded 'no evidence in N runs', NEVER 'stable'."""
    b = BayesianFailureRate(test_id="test_suite::test_zero", runs=20, failures=0)
    assert b.verdict == "no evidence in 20 runs"
    assert "stable" not in b.verdict.lower()

    ci = b.credible_interval(confidence=0.95)
    assert ci.lower >= 0.0
    # For 20 runs with zero failures, upper bound should be bounded
    assert ci.upper < 0.15


def test_bayesian_deterministic_failure():
    """Verify 100% failure rate yields deterministic_failure classification."""
    b = BayesianFailureRate(test_id="test_suite::test_bug", runs=10, failures=10)
    assert b.verdict == "deterministic_failure"
    assert b.classification == "deterministic_failure"
    ci = b.credible_interval(confidence=0.95)
    assert ci.lower > 0.65


# ---------------------------------------------------------------------------
# 2. Adaptive Stopping Policy
# ---------------------------------------------------------------------------


def test_adaptive_stopping_halts_immediately_on_flakiness():
    """Verify adaptive stopping halts early once both pass and fail are observed."""
    policy = AdaptiveStoppingPolicy(min_runs=3, max_runs=20)

    # 1 run fail: below min_runs
    dec1 = policy.evaluate("test_x", runs=1, failures=1)
    assert dec1.should_stop is False

    # 2 runs, 1 fail: observed both pass and fail -> flakiness confirmed!
    dec2 = policy.evaluate("test_x", runs=2, failures=1)
    assert dec2.should_stop is True
    assert dec2.verdict == "flaky"
    assert "both pass and fail" in dec2.reason


def test_adaptive_stopping_zero_failure_bounds_out():
    """Verify adaptive policy stops when failure rate is bounded and words as 'no evidence'."""
    policy = AdaptiveStoppingPolicy(min_runs=3, max_runs=20, threshold_p=0.15)
    dec = policy.evaluate("test_y", runs=10, failures=0)

    assert dec.should_stop is True
    assert dec.verdict == "no evidence in 10 runs"
    assert "stable" not in dec.verdict.lower()


def test_simulate_adaptive_run_runs_saved_at_equal_accuracy():
    """Verify adaptive stopping saves significant runs (>50%) while achieving equal accuracy."""
    test_runs = {
        "t_flaky_1": ["PASS", "FAIL", "PASS", "FAIL"] * 5,
        "t_flaky_2": ["PASS", "PASS", "PASS", "FAIL"] * 5,
        "t_flaky_3": ["FAIL", "PASS", "PASS", "PASS"] * 5,
        "t_pass_1": ["PASS"] * 20,
        "t_pass_2": ["PASS"] * 20,
        "t_pass_3": ["PASS"] * 20,
        "t_pass_4": ["PASS"] * 20,
        "t_fail_1": ["FAIL"] * 20,
    }

    summary = simulate_adaptive_run(test_runs, fixed_budget=20)

    assert summary.total_tests == 8
    assert summary.fixed_budget_runs == 160
    assert summary.adaptive_runs < summary.fixed_budget_runs
    assert summary.runs_saved > 0
    assert summary.runs_saved_pct > 50.0  # Saves over 50% of test runs
    assert summary.equal_accuracy is True
    assert summary.flaky_detected_fixed == {"t_flaky_1", "t_flaky_2", "t_flaky_3"}
    assert summary.flaky_detected_adaptive == summary.flaky_detected_fixed

    # Verify wording in verdicts
    for test_id, verdict in summary.verdicts.items():
        if "pass" in test_id:
            assert "no evidence in" in verdict
            assert "stable" not in verdict.lower()


# ---------------------------------------------------------------------------
# 3. Paired Statistical Comparison (McNemar & Paired Bootstrap)
# ---------------------------------------------------------------------------


def test_mcnemar_identical_classifiers():
    """Identical predictions should yield p_value = 1.0 and zero discordant pairs."""
    y_true = ["flaky", "real_fail", "no_evidence"] * 5
    pred_a = list(y_true)
    pred_b = list(y_true)

    res = mcnemar_test(y_true, pred_a, pred_b)
    assert res.b == 0
    assert res.c == 0
    assert res.p_value == 1.0
    assert res.is_significant is False
    assert len(res.justification) > 20


def test_mcnemar_significant_difference():
    """When Model A significantly outperforms Model B on discordant pairs, p < alpha."""
    y_true = ["flaky"] * 20
    pred_a = ["flaky"] * 18 + ["no_evidence"] * 2  # 18 correct
    pred_b = ["flaky"] * 6 + ["no_evidence"] * 14  # 6 correct

    res = mcnemar_test(y_true, pred_a, pred_b, alpha=0.05)
    assert res.b > res.c
    assert res.p_value < 0.05
    assert res.is_significant is True


def test_paired_bootstrap_accuracy_comparison():
    """Verify paired bootstrap computes empirical distribution and confidence intervals."""
    y_true = ["flaky"] * 15 + ["no_evidence"] * 15
    pred_a = ["flaky"] * 14 + ["no_evidence"] * 1 + ["no_evidence"] * 14 + ["flaky"] * 1  # 28/30 correct
    pred_b = ["flaky"] * 8 + ["no_evidence"] * 7 + ["no_evidence"] * 8 + ["flaky"] * 7  # 16/30 correct

    def accuracy_metric(y_t, y_p):
        return sum(1 for yt, yp in zip(y_t, y_p) if yt == yp) / len(y_t)

    res = paired_bootstrap_comparison(
        y_true=y_true,
        pred_a=pred_a,
        pred_b=pred_b,
        metric_fn=accuracy_metric,
        metric_name="Accuracy",
        n_bootstraps=500,
        confidence=0.95,
    )

    assert res.metric_name == "Accuracy"
    assert res.diff_mean > 0.30
    assert res.ci_lower > 0.15
    assert res.ci_upper > res.ci_lower
    assert res.is_significant is True
    assert "paired bootstrap" in res.justification.lower()
