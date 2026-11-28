"""flakeguard.stats package: Bayesian failure rate estimation, adaptive stopping, and paired comparison."""

from flakeguard.stats.adaptive import AdaptiveRunSummary, AdaptiveStoppingPolicy
from flakeguard.stats.bayesian import BayesianFailureRate, CredibleInterval
from flakeguard.stats.comparison import (
    BootstrapComparisonResult,
    McNemarResult,
    mcnemar_test,
    paired_bootstrap_comparison,
)

__all__ = [
    "AdaptiveRunSummary",
    "AdaptiveStoppingPolicy",
    "BayesianFailureRate",
    "BootstrapComparisonResult",
    "CredibleInterval",
    "McNemarResult",
    "mcnemar_test",
    "paired_bootstrap_comparison",
]

