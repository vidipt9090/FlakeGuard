"""Adaptive test stopping policy to minimize test reruns while guaranteeing confidence."""

from __future__ import annotations

from dataclasses import dataclass, field

from flakeguard.stats.bayesian import BayesianFailureRate


@dataclass(frozen=True)
class AdaptiveStoppingDecision:
    """Decision emitted by adaptive stopping policy."""

    should_stop: bool
    reason: str
    verdict: str  # "flaky" | "deterministic_failure" | "no evidence in N runs" | "uncertain"
    runs_used: int
    failures_observed: int


@dataclass
class AdaptiveRunSummary:
    """Summary of benchmark comparing fixed budget vs adaptive stopping."""

    total_tests: int
    fixed_budget_runs: int
    adaptive_runs: int
    runs_saved: int
    runs_saved_pct: float
    flaky_detected_fixed: set[str] = field(default_factory=set)
    flaky_detected_adaptive: set[str] = field(default_factory=set)
    equal_accuracy: bool = False
    verdicts: dict[str, str] = field(default_factory=dict)
    runs_per_test: dict[str, int] = field(default_factory=dict)


class AdaptiveStoppingPolicy:
    """Bayesian adaptive stopping policy for test repetition.

    Stops early when:
    1. Flakiness is confirmed (both PASS and FAIL observed).
    2. Zero failure rate is statistically bounded (P(p > threshold) <= 1 - confidence).
    3. Consecutive failure indicates deterministic failure.
    4. Max budget is reached.

    CRITICAL RULE:
        Zero-failure tests report 'no evidence in N runs', NEVER 'stable'.
    """

    def __init__(
        self,
        min_runs: int = 3,
        max_runs: int = 20,
        confidence: float = 0.95,
        threshold_p: float = 0.15,
        alpha_0: float = 0.5,
        beta_0: float = 0.5,
    ) -> None:
        self.min_runs = min_runs
        self.max_runs = max_runs
        self.confidence = confidence
        self.threshold_p = threshold_p
        self.alpha_0 = alpha_0
        self.beta_0 = beta_0

    def evaluate(self, test_id: str, runs: int, failures: int) -> AdaptiveStoppingDecision:
        """Evaluate whether to stop running the given test."""
        if runs < 0 or failures < 0 or failures > runs:
            raise ValueError(f"Invalid runs ({runs}) or failures ({failures})")

        passes = runs - failures
        b_rate = BayesianFailureRate(
            test_id=test_id,
            runs=runs,
            failures=failures,
            alpha_0=self.alpha_0,
            beta_0=self.beta_0,
        )

        # 1. Definite Flakiness: observed at least one PASS and at least one FAIL
        if failures > 0 and passes > 0:
            return AdaptiveStoppingDecision(
                should_stop=True,
                reason="Flakiness confirmed: observed both pass and fail outcomes",
                verdict="flaky",
                runs_used=runs,
                failures_observed=failures,
            )

        # 2. Before min_runs, always continue
        if runs < self.min_runs:
            return AdaptiveStoppingDecision(
                should_stop=False,
                reason=f"Below minimum runs threshold ({runs}/{self.min_runs})",
                verdict="uncertain",
                runs_used=runs,
                failures_observed=failures,
            )

        # 3. All Passes (Zero Failures)
        if failures == 0:
            # Check Bayesian upper bound
            ci = b_rate.credible_interval(confidence=self.confidence)
            if ci.upper <= self.threshold_p or runs >= 10:
                return AdaptiveStoppingDecision(
                    should_stop=True,
                    reason=(
                        f"Failure rate statistically bounded below {self.threshold_p:.2f} "
                        f"(upper CI: {ci.upper:.3f} at {self.confidence*100:.0f}%)"
                    ),
                    verdict=f"no evidence in {runs} runs",
                    runs_used=runs,
                    failures_observed=failures,
                )

        # 4. Consistent Failures (Deterministic Regression)
        if failures == runs and runs >= max(self.min_runs, 5):
            return AdaptiveStoppingDecision(
                should_stop=True,
                reason=f"Consistent failure across {runs} consecutive runs",
                verdict="deterministic_failure",
                runs_used=runs,
                failures_observed=failures,
            )

        # 5. Max Budget Reached
        if runs >= self.max_runs:
            verdict = b_rate.verdict
            return AdaptiveStoppingDecision(
                should_stop=True,
                reason=f"Max budget reached ({self.max_runs} runs)",
                verdict=verdict,
                runs_used=runs,
                failures_observed=failures,
            )

        return AdaptiveStoppingDecision(
            should_stop=False,
            reason="Uncertain outcome; statistical threshold not yet met",
            verdict="uncertain",
            runs_used=runs,
            failures_observed=failures,
        )


def simulate_adaptive_run(
    test_runs: dict[str, list[str]],
    fixed_budget: int = 20,
    policy: AdaptiveStoppingPolicy | None = None,
) -> AdaptiveRunSummary:
    """Simulate and compare fixed budget reruns vs adaptive stopping on historical/synthetic runs.

    Args:
        test_runs: Mapping of test_id -> list of sequential outcomes (e.g. ['PASS', 'FAIL', ...]).
        fixed_budget: Fixed repetition budget per test.
        policy: AdaptiveStoppingPolicy instance (defaults to standard policy).
    """
    pol = policy or AdaptiveStoppingPolicy(max_runs=fixed_budget)

    fixed_flaky: set[str] = set()
    adaptive_flaky: set[str] = set()
    verdicts: dict[str, str] = {}
    runs_per_test: dict[str, int] = {}

    total_fixed_runs = 0
    total_adaptive_runs = 0

    for test_id, sequence in test_runs.items():
        # Truncate sequence or loop if necessary to reach budget
        available = list(sequence)
        if not available:
            continue

        # 1. Fixed budget evaluation
        fixed_slice = [available[i % len(available)] for i in range(fixed_budget)]
        total_fixed_runs += len(fixed_slice)
        fixed_fails = sum(1 for o in fixed_slice if o in ("FAIL", "ERROR"))
        fixed_passes = len(fixed_slice) - fixed_fails
        if fixed_fails > 0 and fixed_passes > 0:
            fixed_flaky.add(test_id)

        # 2. Sequential adaptive evaluation
        ad_runs = 0
        ad_fails = 0
        ad_decision: AdaptiveStoppingDecision | None = None

        for i in range(fixed_budget):
            outcome = available[i % len(available)]
            ad_runs += 1
            if outcome in ("FAIL", "ERROR"):
                ad_fails += 1

            decision = pol.evaluate(test_id, ad_runs, ad_fails)
            if decision.should_stop:
                ad_decision = decision
                break

        if ad_decision is None:
            ad_decision = pol.evaluate(test_id, ad_runs, ad_fails)

        total_adaptive_runs += ad_decision.runs_used
        verdicts[test_id] = ad_decision.verdict
        runs_per_test[test_id] = ad_decision.runs_used

        if ad_decision.verdict == "flaky":
            adaptive_flaky.add(test_id)

    runs_saved = total_fixed_runs - total_adaptive_runs
    saved_pct = (runs_saved / total_fixed_runs * 100.0) if total_fixed_runs > 0 else 0.0
    equal_accuracy = (fixed_flaky == adaptive_flaky)

    return AdaptiveRunSummary(
        total_tests=len(test_runs),
        fixed_budget_runs=total_fixed_runs,
        adaptive_runs=total_adaptive_runs,
        runs_saved=runs_saved,
        runs_saved_pct=round(saved_pct, 2),
        flaky_detected_fixed=fixed_flaky,
        flaky_detected_adaptive=adaptive_flaky,
        equal_accuracy=equal_accuracy,
        verdicts=verdicts,
        runs_per_test=runs_per_test,
    )

