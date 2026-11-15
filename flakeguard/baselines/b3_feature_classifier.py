"""Baseline B3: Machine learning feature classifier trained on execution run features and static code smells."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class TestFeatureVector:
    """Feature vector extracted for a single test."""

    test_id: str
    failure_rate: float
    pass_rate: float
    flip_count: int
    flip_rate: float
    outcome_entropy: float
    duration_mean: float
    duration_std: float
    has_sleep: int
    has_random: int
    has_datetime: int

    def to_array(self) -> np.ndarray:
        return np.array([
            self.failure_rate,
            self.pass_rate,
            self.flip_count,
            self.flip_rate,
            self.outcome_entropy,
            self.duration_mean,
            self.duration_std,
            self.has_sleep,
            self.has_random,
            self.has_datetime,
        ], dtype=float)


def extract_features_from_runs(
    test_id: str,
    outcomes: list[str],
    durations: list[float] | None = None,
    code_text: str = "",
) -> TestFeatureVector:
    """Extract run features and code smell features from test execution sequence."""
    n = len(outcomes)
    if n == 0:
        return TestFeatureVector(
            test_id=test_id,
            failure_rate=0.0,
            pass_rate=0.0,
            flip_count=0,
            flip_rate=0.0,
            outcome_entropy=0.0,
            duration_mean=0.0,
            duration_std=0.0,
            has_sleep=0,
            has_random=0,
            has_datetime=0,
        )

    fails = sum(1 for o in outcomes if o in ("FAIL", "ERROR"))
    p_fail = fails / n
    p_pass = 1.0 - p_fail

    # Flip count: transitions between pass and fail
    flips = 0
    for i in range(1, n):
        prev_fail = outcomes[i - 1] in ("FAIL", "ERROR")
        curr_fail = outcomes[i] in ("FAIL", "ERROR")
        if prev_fail != curr_fail:
            flips += 1
    flip_rate = flips / (n - 1) if n > 1 else 0.0

    # Shannon entropy
    entropy = 0.0
    if 0.0 < p_fail < 1.0:
        entropy = - (p_fail * math.log2(p_fail) + p_pass * math.log2(p_pass))

    # Durations
    durs = durations or [0.01] * n
    dur_mean = float(np.mean(durs))
    dur_std = float(np.std(durs))

    # Code smells
    has_sleep = 1 if "sleep" in code_text else 0
    has_random = 1 if "random" in code_text else 0
    has_datetime = 1 if any(t in code_text for t in ("datetime", "timezone", "time.")) else 0

    return TestFeatureVector(
        test_id=test_id,
        failure_rate=round(p_fail, 4),
        pass_rate=round(p_pass, 4),
        flip_count=flips,
        flip_rate=round(flip_rate, 4),
        outcome_entropy=round(entropy, 4),
        duration_mean=round(dur_mean, 4),
        duration_std=round(dur_std, 4),
        has_sleep=has_sleep,
        has_random=has_random,
        has_datetime=has_datetime,
    )


class B3FeatureClassifier:
    """Supervised feature classifier distinguishing flaky, real_fail, and no_evidence tests."""

    def __init__(self) -> None:
        self.is_trained = False
        self._classes = ["flaky", "real_fail", "no_evidence"]
        self._sklearn_model = None
        self._init_model()

    def _init_model(self) -> None:
        try:
            from sklearn.ensemble import RandomForestClassifier

            self._sklearn_model = RandomForestClassifier(n_estimators=50, random_state=42)
        except ImportError:
            self._sklearn_model = None

    def fit(self, X: list[TestFeatureVector], y: list[str]) -> None:
        """Fit classifier on extracted feature vectors and ground truth labels."""
        X_mat = np.array([f.to_array() for f in X])
        y_arr = np.array(y)

        if self._sklearn_model is not None:
            self._sklearn_model.fit(X_mat, y_arr)
        self.is_trained = True

    def predict(self, feature: TestFeatureVector) -> tuple[Literal["flaky", "real_fail", "no_evidence"], float]:
        """Predict test classification and confidence score.

        Returns:
            (predicted_label, confidence)
        """
        arr = feature.to_array().reshape(1, -1)

        if self._sklearn_model is not None and self.is_trained:
            pred = self._sklearn_model.predict(arr)[0]
            probs = self._sklearn_model.predict_proba(arr)[0]
            conf = float(np.max(probs))
            return pred, round(conf, 4)

        # Robust analytical decision boundary based on empirical features:
        # 1. Zero failures -> no evidence
        if feature.failure_rate == 0.0:
            return "no_evidence", 0.95

        # 2. 100% failures with zero flips -> deterministic failure (real_fail)
        if feature.failure_rate == 1.0 and feature.flip_count == 0:
            return "real_fail", 0.95

        # 3. Flips > 0 or 0 < failure_rate < 1.0 -> flaky
        if feature.flip_count > 0 or (0.0 < feature.failure_rate < 1.0):
            # Confidence proportional to entropy and flip count
            conf = min(0.99, max(0.70, 0.70 + 0.25 * feature.outcome_entropy))
            return "flaky", round(conf, 4)

        return "flaky", 0.75
