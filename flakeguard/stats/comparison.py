"""Paired statistical comparison methods: McNemar's test and Paired Bootstrap with scientific justifications."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class McNemarResult:
    """Outcome of McNemar's paired contingency test."""

    b: int  # Model A correct, Model B incorrect
    c: int  # Model A incorrect, Model B correct
    statistic: float  # Chi-squared statistic (or min(b, c) for exact binomial)
    p_value: float
    is_significant: bool  # True if p_value < alpha
    alpha: float
    method: str  # "exact_binomial" or "chi_squared_continuity"
    justification: str


@dataclass(frozen=True)
class BootstrapComparisonResult:
    """Outcome of paired bootstrap comparison for any evaluation metric."""

    metric_name: str
    diff_mean: float  # Mean(Metric(A) - Metric(B))
    ci_lower: float  # 2.5th percentile
    ci_upper: float  # 97.5th percentile
    confidence: float
    p_value: float  # Empirical two-sided p-value
    is_significant: bool  # True if 0 is not in [ci_lower, ci_upper]
    justification: str


def mcnemar_test(
    y_true: list[str],
    pred_a: list[str],
    pred_b: list[str],
    alpha: float = 0.05,
) -> McNemarResult:
    """Compute McNemar's paired test comparing classifier A and classifier B against ground truth.

    Justification:
        McNemar's test is the standard non-parametric test for paired binary classifications
        evaluated on the identical test instances. It controls Type I error rate when comparing
        two algorithms on the same benchmark, focusing exclusively on discordant pairs (b vs c).
    """
    if not (len(y_true) == len(pred_a) == len(pred_b)):
        raise ValueError("y_true, pred_a, and pred_b must have identical lengths")

    # b: A correct, B incorrect
    # c: A incorrect, B correct
    b = 0
    c = 0
    for yt, ya, yb in zip(y_true, pred_a, pred_b):
        a_correct = (ya == yt)
        b_correct = (yb == yt)
        if a_correct and not b_correct:
            b += 1
        elif not a_correct and b_correct:
            c += 1

    total_discordant = b + c

    justification = (
        "McNemar's test is mathematically justified for paired benchmark evaluations because both "
        "classifiers are evaluated on the exact same dataset instances. Standard independent two-sample "
        "tests violate the independence assumption and produce biased variance estimates. McNemar's test "
        "strictly evaluates the symmetry of discordant classifications (b vs c)."
    )

    if total_discordant == 0:
        return McNemarResult(
            b=0,
            c=0,
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            alpha=alpha,
            method="exact_binomial",
            justification=justification,
        )

    # For small samples (b + c < 25), use exact two-sided binomial test
    if total_discordant < 25:
        k = min(b, c)
        # Two-sided binomial p-value under p=0.5: 2 * sum_{i=0}^k (n choose i) * 0.5^n
        p_val = 2.0 * sum(math.comb(total_discordant, i) * (0.5**total_discordant) for i in range(k + 1))
        p_val = min(1.0, p_val)
        return McNemarResult(
            b=b,
            c=c,
            statistic=float(k),
            p_value=round(p_val, 6),
            is_significant=(p_val < alpha),
            alpha=alpha,
            method="exact_binomial",
            justification=justification,
        )

    # For larger samples (b + c >= 25), use Chi-squared with Edwards continuity correction
    chi2 = ((abs(b - c) - 1.0) ** 2) / total_discordant
    # Survival function of chi-squared with 1 df is erfc(sqrt(chi2 / 2))
    p_val = math.erfc(math.sqrt(chi2 / 2.0))

    return McNemarResult(
        b=b,
        c=c,
        statistic=round(chi2, 4),
        p_value=round(p_val, 6),
        is_significant=(p_val < alpha),
        alpha=alpha,
        method="chi_squared_continuity",
        justification=justification,
    )


def paired_bootstrap_comparison(
    y_true: list[str],
    pred_a: list[str],
    pred_b: list[str],
    metric_fn: Callable[[list[str], list[str]], float],
    metric_name: str = "Accuracy",
    n_bootstraps: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapComparisonResult:
    """Compute paired non-parametric bootstrap confidence interval for Delta Metric = Metric(A) - Metric(B).

    Justification:
        Paired bootstrap resamples instance triplets (y_i, pred_a_i, pred_b_i) simultaneously with
        replacement. This preserves intra-instance correlation and provides exact percentile confidence
        intervals for complex non-linear metrics (F1, Accuracy, Precision) without assuming normality.
    """
    n = len(y_true)
    if not (n == len(pred_a) == len(pred_b)):
        raise ValueError("y_true, pred_a, and pred_b must have identical lengths")
    if n == 0:
        raise ValueError("Data cannot be empty")

    rng = random.Random(seed)
    diffs: list[float] = []

    for _ in range(n_bootstraps):
        indices = [rng.randint(0, n - 1) for _ in range(n)]
        boot_y = [y_true[idx] for idx in indices]
        boot_a = [pred_a[idx] for idx in indices]
        boot_b = [pred_b[idx] for idx in indices]

        metric_a = metric_fn(boot_y, boot_a)
        metric_b = metric_fn(boot_y, boot_b)
        diffs.append(metric_a - metric_b)

    diffs.sort()
    alpha = 1.0 - confidence
    lower_idx = int(alpha / 2.0 * n_bootstraps)
    upper_idx = int((1.0 - alpha / 2.0) * n_bootstraps)
    upper_idx = min(upper_idx, n_bootstraps - 1)

    ci_lower = diffs[lower_idx]
    ci_upper = diffs[upper_idx]
    diff_mean = sum(diffs) / n_bootstraps

    # Empirical two-sided p-value: fraction of bootstraps on opposite side of zero
    if diff_mean >= 0:
        p_val = 2.0 * sum(1 for d in diffs if d <= 0) / n_bootstraps
    else:
        p_val = 2.0 * sum(1 for d in diffs if d >= 0) / n_bootstraps
    p_val = min(1.0, max(1.0 / n_bootstraps, p_val))

    is_significant = (ci_lower > 0 and ci_upper > 0) or (ci_lower < 0 and ci_upper < 0)

    justification = (
        "Paired bootstrap resampling preserves the paired correlation structure across test instances "
        "and makes zero parametric assumptions about normality. It calculates empirical distribution "
        f"for Delta {metric_name} and provides distribution-free credible intervals."
    )

    return BootstrapComparisonResult(
        metric_name=metric_name,
        diff_mean=round(diff_mean, 4),
        ci_lower=round(ci_lower, 4),
        ci_upper=round(ci_upper, 4),
        confidence=confidence,
        p_value=round(p_val, 4),
        is_significant=is_significant,
        justification=justification,
    )

