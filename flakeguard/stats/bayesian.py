"""Per-test Bayesian failure-rate estimation with credible intervals and bounded zero-failure uncertainty."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np


def _beta_log_constant(a: float, b: float) -> float:
    """Compute log(B(a, b)) using log gamma."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def beta_pdf(x: float, a: float, b: float) -> float:
    """Beta probability density function."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    log_c = _beta_log_constant(a, b)
    log_val = (a - 1.0) * math.log(x) + (b - 1.0) * math.log(1.0 - x) - log_c
    return math.exp(log_val)


def beta_cdf(x: float, a: float, b: float, n_points: int = 60) -> float:
    """Beta cumulative distribution function computed via Gauss-Legendre quadrature.

    Uses variable substitution t = u^(1/a) when a < 1 to eliminate the endpoint singularity at 0.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    log_c = _beta_log_constant(a, b)

    if a < 1.0:
        u_max = x**a
        nodes, weights = np.polynomial.legendre.leggauss(n_points)
        u = 0.5 * u_max * (nodes + 1.0)
        integrand = np.array([
            math.exp((b - 1.0) * math.log(max(1e-15, 1.0 - float(ui) ** (1.0 / a))) - log_c) / a
            for ui in u
        ])
        return min(1.0, max(0.0, float(0.5 * u_max * np.sum(weights * integrand))))

    nodes, weights = np.polynomial.legendre.leggauss(n_points)
    t = 0.5 * x * (nodes + 1.0)
    integrand = np.array([
        math.exp((a - 1.0) * math.log(float(ti)) + (b - 1.0) * math.log(1.0 - float(ti)) - log_c)
        for ti in t
    ])
    return min(1.0, max(0.0, float(0.5 * x * np.sum(weights * integrand))))


def beta_ppf(p: float, a: float, b: float, tol: float = 1e-7, max_iter: int = 80) -> float:
    """Percent point function (inverse CDF) for Beta distribution using bisection."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0

    low, high = 0.0, 1.0
    for _ in range(max_iter):
        mid = (low + high) / 2.0
        val = beta_cdf(mid, a, b)
        if abs(val - p) < tol:
            return mid
        if val < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


@dataclass(frozen=True)
class CredibleInterval:
    """Bayesian equal-tailed credible interval [lower, upper]."""

    lower: float
    upper: float
    confidence: float = 0.95


@dataclass
class BayesianFailureRate:
    """Beta-Binomial Bayesian conjugate model for test failure rate.

    Prior: Beta(alpha_0, beta_0). Default is Jeffreys prior Beta(0.5, 0.5).
    Posterior: Beta(alpha_0 + k, beta_0 + n - k) where n=total runs, k=failures.

    CRITICAL RULE:
        Tests with zero failures are worded as 'no evidence in N runs', NEVER 'stable'.
    """

    test_id: str
    runs: int
    failures: int
    alpha_0: float = 0.5
    beta_0: float = 0.5

    def __post_init__(self) -> None:
        if self.runs < 0 or self.failures < 0:
            raise ValueError("runs and failures must be non-negative integers")
        if self.failures > self.runs:
            raise ValueError("failures cannot exceed total runs")
        if self.alpha_0 <= 0 or self.beta_0 <= 0:
            raise ValueError("prior hyperparameters must be strictly positive")

    @property
    def passes(self) -> int:
        return self.runs - self.failures

    @property
    def alpha(self) -> float:
        """Posterior alpha."""
        return self.alpha_0 + self.failures

    @property
    def beta(self) -> float:
        """Posterior beta."""
        return self.beta_0 + self.passes

    @property
    def posterior_mean(self) -> float:
        """Expected value of failure rate under posterior."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def posterior_variance(self) -> float:
        """Variance of failure rate under posterior."""
        a, b = self.alpha, self.beta
        return (a * b) / (((a + b) ** 2) * (a + b + 1.0))

    def credible_interval(self, confidence: float = 0.95) -> CredibleInterval:
        """Compute equal-tailed credible interval for failure rate."""
        tail = (1.0 - confidence) / 2.0
        lower = beta_ppf(tail, self.alpha, self.beta)
        upper = beta_ppf(1.0 - tail, self.alpha, self.beta)
        return CredibleInterval(lower=round(lower, 6), upper=round(upper, 6), confidence=confidence)

    @property
    def verdict(self) -> str:
        """Formal verdict.

        Rule: NEVER outputs 'stable'.
        Zero-failure tests report 'no evidence in N runs'.
        """
        if self.runs == 0:
            return "untested (0 runs)"
        if self.failures == 0:
            return f"no evidence in {self.runs} runs"
        if self.failures == self.runs:
            return "deterministic_failure"
        return "flaky"

    @property
    def classification(self) -> Literal["flaky", "deterministic_failure", "no_evidence"]:
        if self.failures == 0:
            return "no_evidence"
        if self.failures == self.runs:
            return "deterministic_failure"
        return "flaky"

    def prob_failure_rate_exceeds(self, threshold: float) -> float:
        """Compute posterior probability that true failure rate exceeds a threshold: P(p > threshold)."""
        return 1.0 - beta_cdf(threshold, self.alpha, self.beta)
