"""flakeguard.baselines package: B1 (reruns), B2 (DeFlaker coverage-diff), and B3 (feature classifier)."""

from flakeguard.baselines.b2_coverage import B2ClassificationResult, B2CoverageClassifier
from flakeguard.baselines.b3_feature_classifier import (
    B3FeatureClassifier,
    TestFeatureVector,
    extract_features_from_runs,
)

__all__ = [
    "B2ClassificationResult",
    "B2CoverageClassifier",
    "B3FeatureClassifier",
    "TestFeatureVector",
    "extract_features_from_runs",
]
