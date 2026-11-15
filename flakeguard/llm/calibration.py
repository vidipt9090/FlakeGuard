"""Calibration metrics, Expected Calibration Error (ECE), reliability diagrams, and risk-coverage curves."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationBin:
    """A single confidence bin in a reliability diagram."""

    bin_lower: float
    bin_upper: float
    count: int
    avg_confidence: float
    accuracy: float
    bin_error: float


@dataclass(frozen=True)
class CalibrationMetrics:
    """Expected Calibration Error (ECE) and reliability diagram data."""

    ece: float
    mce: float  # Maximum Calibration Error
    total_samples: int
    bins: list[CalibrationBin]


def compute_ece(
    confidences: list[float],
    correct: list[bool],
    n_bins: int = 10,
) -> CalibrationMetrics:
    """Compute Expected Calibration Error (ECE) and reliability diagram bins.

    ECE = sum_{m=1}^M (|B_m| / N) * |acc(B_m) - conf(B_m)|
    """
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must have equal length")

    n = len(confidences)
    if n == 0:
        return CalibrationMetrics(ece=0.0, mce=0.0, total_samples=0, bins=[])

    bins: list[CalibrationBin] = []
    bin_width = 1.0 / n_bins
    total_ece = 0.0
    max_error = 0.0

    for m in range(n_bins):
        b_low = m * bin_width
        b_high = (m + 1) * bin_width

        # In last bin, include upper boundary 1.0
        if m == n_bins - 1:
            indices = [i for i, c in enumerate(confidences) if b_low <= c <= b_high]
        else:
            indices = [i for i, c in enumerate(confidences) if b_low <= c < b_high]

        count = len(indices)
        if count == 0:
            bins.append(
                CalibrationBin(
                    bin_lower=round(b_low, 3),
                    bin_upper=round(b_high, 3),
                    count=0,
                    avg_confidence=0.0,
                    accuracy=0.0,
                    bin_error=0.0,
                )
            )
            continue

        bin_conf = sum(confidences[i] for i in indices) / count
        bin_acc = sum(1 for i in indices if correct[i]) / count
        bin_err = abs(bin_acc - bin_conf)

        total_ece += (count / n) * bin_err
        max_error = max(max_error, bin_err)

        bins.append(
            CalibrationBin(
                bin_lower=round(b_low, 3),
                bin_upper=round(b_high, 3),
                count=count,
                avg_confidence=round(bin_conf, 4),
                accuracy=round(bin_acc, 4),
                bin_error=round(bin_err, 4),
            )
        )

    return CalibrationMetrics(
        ece=round(total_ece, 4),
        mce=round(max_error, 4),
        total_samples=n,
        bins=bins,
    )


@dataclass(frozen=True)
class RiskCoveragePoint:
    """A point on the risk-coverage curve."""

    coverage: float  # Fraction of predictions retained [0, 1]
    confidence_threshold: float
    retained_count: int
    accuracy: float
    selective_risk: float  # 1.0 - accuracy
    abstain_rate: float  # 1.0 - coverage


def compute_risk_coverage_curve(
    confidences: list[float],
    correct: list[bool],
    steps: int = 10,
) -> list[RiskCoveragePoint]:
    """Compute selective classification risk-coverage curve.

    As coverage decreases (low-confidence predictions are abstained),
    well-calibrated models exhibit monotonically decreasing risk.
    """
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must have equal length")

    n = len(confidences)
    if n == 0:
        return []

    # Sort descending by confidence
    paired = sorted(zip(confidences, correct), key=lambda x: x[0], reverse=True)

    points: list[RiskCoveragePoint] = []
    fractions = [round((s + 1) / steps, 2) for s in range(steps)]

    for frac in fractions:
        k = max(1, int(round(frac * n)))
        subset = paired[:k]

        retained_acc = sum(1 for _, is_corr in subset if is_corr) / k
        min_conf = subset[-1][0]

        points.append(
            RiskCoveragePoint(
                coverage=round(k / n, 4),
                confidence_threshold=round(min_conf, 4),
                retained_count=k,
                accuracy=round(retained_acc, 4),
                selective_risk=round(1.0 - retained_acc, 4),
                abstain_rate=round(1.0 - (k / n), 4),
            )
        )

    return points

