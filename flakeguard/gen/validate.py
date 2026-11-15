"""Validation gates for generated characterization tests."""

from flakeguard.notest.validator import (
    ValidationResult,
    validate_generated_test,
)

__all__ = [
    "ValidationResult",
    "validate_generated_test",
]
