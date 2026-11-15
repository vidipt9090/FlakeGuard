"""Supervised feature classifier baseline shim."""
from flakeguard.baselines.b3_feature_classifier import (
    FeatureClassifierBaseline,
    TestFeatures,
    extract_test_features,
)

__all__ = ["TestFeatures", "extract_test_features", "FeatureClassifierBaseline"]

