"""Static risk scanning for non-deterministic and flaky sites."""

from flakeguard.notest.scanner import (
    RiskCategory,
    RiskySite,
    scan_file_for_risky_sites,
    scan_repository_for_risky_sites,
)

__all__ = [
    "RiskCategory",
    "RiskySite",
    "scan_file_for_risky_sites",
    "scan_repository_for_risky_sites",
]
