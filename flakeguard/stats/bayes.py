"""Bayesian statistics and adaptive stopping policy shim."""
from flakeguard.stats.adaptive import (
    AdaptivePolicyConfig,
    AdaptiveTestSession,
    AdaptiveVerdict,
    simulate_adaptive_run,
)
from flakeguard.stats.bayesian import (
    BayesianFailureRate,
    beta_credible_interval,
    compute_beta_cdf,
)

__all__ = [
    "BayesianFailureRate",
    "beta_credible_interval",
    "compute_beta_cdf",
    "AdaptivePolicyConfig",
    "AdaptiveTestSession",
    "AdaptiveVerdict",
    "simulate_adaptive_run",
]

