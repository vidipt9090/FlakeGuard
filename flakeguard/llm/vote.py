"""k-vote self-consistency and selective abstention shim."""
from flakeguard.llm.self_consistency import (
    ConsistencyResult,
    evaluate_self_consistency,
)

__all__ = ["ConsistencyResult", "evaluate_self_consistency"]

