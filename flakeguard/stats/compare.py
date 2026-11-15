"""Paired statistical comparison shim."""
from flakeguard.stats.comparison import (
    BootstrapResult,
    McNemarResult,
    mcnemar_test,
    paired_bootstrap_comparison,
)

__all__ = ["McNemarResult", "BootstrapResult", "mcnemar_test", "paired_bootstrap_comparison"]

