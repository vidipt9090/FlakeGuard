"""flakeguard.llm package: Prompt v4, providers, schema validation, self-consistency, calibration, and ablation."""

from flakeguard.llm.ablation import (
    ABLATION_VARIANTS,
    AblationResult,
    AblationVariant,
    evaluate_ablation_variant,
)
from flakeguard.llm.calibration import (
    CalibrationBin,
    CalibrationMetrics,
    RiskCoveragePoint,
    compute_ece,
    compute_risk_coverage_curve,
)
from flakeguard.llm.prompt_v4 import build_prompt_v4
from flakeguard.llm.providers import (
    HOSTED_SECRET_NAMES,
    BaseLLMProvider,
    CachedReplayProvider,
    HostedProvider,
    LocalOllamaProvider,
    get_provider,
)
from flakeguard.llm.schema import (
    VerdictOutput,
    extract_json_from_text,
    normalize_verdict_dict,
    parse_and_validate_verdict,
)
from flakeguard.llm.self_consistency import SelfConsistencyResult, run_self_consistency

__all__ = [
    "ABLATION_VARIANTS",
    "AblationResult",
    "AblationVariant",
    "BaseLLMProvider",
    "CachedReplayProvider",
    "CalibrationBin",
    "CalibrationMetrics",
    "HOSTED_SECRET_NAMES",
    "HostedProvider",
    "LocalOllamaProvider",
    "RiskCoveragePoint",
    "SelfConsistencyResult",
    "VerdictOutput",
    "build_prompt_v4",
    "compute_ece",
    "compute_risk_coverage_curve",
    "evaluate_ablation_variant",
    "extract_json_from_text",
    "get_provider",
    "normalize_verdict_dict",
    "parse_and_validate_verdict",
    "run_self_consistency",
]
