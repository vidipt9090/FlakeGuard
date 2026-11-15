"""Calibration metrics and ECE reliability diagram shim."""
from flakeguard.llm.calibration import (
    CalibrationBin,
    CalibrationMetrics,
    compute_ece,
    compute_risk_coverage_curve,
)

__all__ = ["CalibrationBin", "CalibrationMetrics", "compute_ece", "compute_risk_coverage_curve"]

