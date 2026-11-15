"""Unit and integration tests for Step 4 LLM stage."""

import json

from flakeguard.contracts import EvidenceReport, EvidenceTier, InterventionRecord
from flakeguard.llm.ablation import (
    ABLATION_VARIANTS,
    evaluate_ablation_variant,
)
from flakeguard.llm.calibration import compute_ece, compute_risk_coverage_curve
from flakeguard.llm.prompt_v4 import build_prompt_v4
from flakeguard.llm.providers import (
    HOSTED_SECRET_NAMES,
    CachedReplayProvider,
    get_provider,
)
from flakeguard.llm.schema import (
    parse_and_validate_verdict,
)
from flakeguard.llm.self_consistency import run_self_consistency
from flakeguard.stats.bayesian import BayesianFailureRate

# ---------------------------------------------------------------------------
# 1. Schema Validation & Normalization
# ---------------------------------------------------------------------------


def test_schema_parsing_clean_json():
    """Verify parse_and_validate_verdict handles clean JSON."""
    raw = json.dumps({
        "label": "flaky",
        "root_cause": "order_dep",
        "confidence": 0.95,
        "evidence_tier": "reproduced",
        "reasoning": "Test depends on test_a.",
        "abstain": False,
    })
    verdict, err = parse_and_validate_verdict(raw)
    assert err is None
    assert verdict is not None
    assert verdict.label == "flaky"
    assert verdict.root_cause == "order_dep"
    assert verdict.confidence == 0.95
    assert verdict.evidence_tier == "reproduced"
    assert verdict.abstain is False


def test_schema_parsing_markdown_fence_and_normalization():
    """Verify markdown fences are extracted and legacy labels normalized."""
    raw = """Here is the classification verdict:
```json
{
  "label": "real",
  "root_cause": "none",
  "confidence": 0.98,
  "evidence_tier": "none",
  "reasoning": "Real bug in shop.py"
}
```
"""
    verdict, err = parse_and_validate_verdict(raw)
    assert err is None
    assert verdict is not None
    assert verdict.label == "real_fail"  # Normalized from 'real'
    assert verdict.root_cause == "none"


def test_schema_normalization_stable_to_no_evidence():
    """Verify legacy 'stable' label is strictly normalized to 'no_evidence'."""
    raw = json.dumps({
        "label": "stable",
        "root_cause": "none",
        "confidence": 0.90,
    })
    verdict, err = parse_and_validate_verdict(raw)
    assert err is None
    assert verdict is not None
    assert verdict.label == "no_evidence"
    assert verdict.evidence_tier == "none"


# ---------------------------------------------------------------------------
# 2. Providers & Secret Name Resolution
# ---------------------------------------------------------------------------


def test_hosted_secret_names_documented():
    """Verify documented hosted API keys include Gemini, OpenAI, Anthropic, and Groq."""
    assert "GEMINI_API_KEY" in HOSTED_SECRET_NAMES
    assert "OPENAI_API_KEY" in HOSTED_SECRET_NAMES
    assert "ANTHROPIC_API_KEY" in HOSTED_SECRET_NAMES
    assert "GROQ_API_KEY" in HOSTED_SECRET_NAMES


def test_get_provider_fallback_to_cache():
    """Verify get_provider falls back to CachedReplayProvider when no keys are set."""
    provider = get_provider(provider_type="auto", allow_cache_fallback=True)
    assert provider is not None
    resp = provider.generate("test prompt")
    verdict, err = parse_and_validate_verdict(resp)
    assert err is None
    assert verdict is not None


# ---------------------------------------------------------------------------
# 3. Prompt v4 Construction
# ---------------------------------------------------------------------------


def test_build_prompt_v4_assembly():
    """Verify build_prompt_v4 includes stats, navigator context, and evidence tiers."""
    b_rate = BayesianFailureRate("test_case_10", runs=20, failures=10)
    report = EvidenceReport(
        test_id="test_case_10",
        tier=EvidenceTier.REPRODUCED,
        category="shared_state",
        polluter_test_id="test_case_09",
        interventions=[
            InterventionRecord(
                kind="pin_seed",
                parameters={"seed": 42},
                flipped=False,
                outcome="FAIL",
                details="No flip under seed",
            )
        ],
        details={"shared_state_overlap": ["shop._default_tax"]},
    )

    prompt = build_prompt_v4(
        test_id="test_case_10",
        test_body="def test_case_10(): assert calculate_tax(100) == 5.0",
        log_excerpt="AssertionError: assert 25.0 == 5.0",
        b_rate=b_rate,
        evidence_report=report,
        code_under_test=["def calculate_tax(amount): return amount * _default_tax"],
        shared_state=["_default_tax = 0.05"],
        smells=["time.sleep"],
    )

    assert "test_case_10" in prompt
    assert "calculate_tax" in prompt
    assert "_default_tax" in prompt
    assert "reproduced" in prompt
    assert "test_case_09" in prompt
    assert "Posterior Mean Failure Rate" in prompt


# ---------------------------------------------------------------------------
# 4. Self-Consistency & Selective Abstention
# ---------------------------------------------------------------------------


class MockVotingProvider(CachedReplayProvider):
    def __init__(self, responses: list[dict]):
        super().__init__()
        self.responses = [json.dumps(r) for r in responses]
        self.idx = 0

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 1000) -> str:
        resp = self.responses[self.idx % len(self.responses)]
        self.idx += 1
        return resp


def test_self_consistency_consensus():
    """Verify self-consistency aggregates 3 agreeing votes."""
    provider = MockVotingProvider([
        {"label": "flaky", "root_cause": "order_dep", "confidence": 0.90},
        {"label": "flaky", "root_cause": "order_dep", "confidence": 0.94},
        {"label": "flaky", "root_cause": "order_dep", "confidence": 0.92},
    ])
    result = run_self_consistency("prompt", provider, k=3)
    assert result.agreement_ratio == 1.0
    assert result.final_verdict.label == "flaky"
    assert result.final_verdict.root_cause == "order_dep"
    assert result.final_verdict.abstain is False
    assert 0.90 <= result.final_verdict.confidence <= 0.95


def test_self_consistency_abstains_on_disagreement():
    """Verify self-consistency marks abstain=True when agreement ratio is below threshold."""
    provider = MockVotingProvider([
        {"label": "flaky", "root_cause": "order_dep", "confidence": 0.85},
        {"label": "real_fail", "root_cause": "none", "confidence": 0.80},
        {"label": "no_evidence", "root_cause": "none", "confidence": 0.75},
    ])
    result = run_self_consistency("prompt", provider, k=3, min_agreement=0.60)
    assert result.agreement_ratio < 0.60
    assert result.final_verdict.abstain is True
    assert "[ABSTAIN]" in result.final_verdict.reasoning


# ---------------------------------------------------------------------------
# 5. Calibration (ECE & Risk-Coverage Curve)
# ---------------------------------------------------------------------------


def test_compute_ece_perfect_calibration():
    """Verify ECE is near zero for perfectly calibrated predictions."""
    # 10 cases with confidence 1.0 and correct=True
    confidences = [1.0] * 10
    correct = [True] * 10
    metrics = compute_ece(confidences, correct, n_bins=5)
    assert metrics.ece == 0.0
    assert metrics.total_samples == 10


def test_compute_ece_miscalibration():
    """Verify ECE detects overconfidence."""
    # Model is 100% confident, but only 50% accurate -> ECE should be 0.50
    confidences = [1.0] * 20
    correct = [True] * 10 + [False] * 10
    metrics = compute_ece(confidences, correct, n_bins=5)
    assert abs(metrics.ece - 0.50) < 1e-4


def test_risk_coverage_curve_monotonicity():
    """Verify risk-coverage curve shows lower risk at lower coverage."""
    confidences = [0.95, 0.90, 0.85, 0.70, 0.60, 0.50]
    correct = [True, True, True, False, False, False]
    curve = compute_risk_coverage_curve(confidences, correct, steps=6)

    assert len(curve) > 0
    # Top 50% (k=3) should have 0% risk (100% accuracy)
    top_pt = next(pt for pt in curve if pt.retained_count == 3)
    assert top_pt.selective_risk == 0.0
    assert top_pt.accuracy == 1.0

    # 100% coverage should have 50% risk (3/6 correct)
    full_pt = curve[-1]
    assert full_pt.selective_risk == 0.50


# ---------------------------------------------------------------------------
# 6. Leave-One-Out Evidence Ablation
# ---------------------------------------------------------------------------


def test_evidence_ablation_variants_execution():
    """Verify all 5 ablation variants execute and produce complete metrics."""
    assert len(ABLATION_VARIANTS) == 5

    cases = [
        {
            "id": "synthetic/tests/test_suite_01.py::test_case_10",
            "ground_truth": "flaky",
            "b_rate": BayesianFailureRate("test_case_10", 20, 10),
            "log_excerpt": "AssertionError: assert 25.0 == 5.0",
            "code_under_test": ["def calculate_tax(amount): return amount * _default_tax"],
            "shared_state": ["_default_tax = 0.05"],
            "evidence_report": EvidenceReport(
                test_id="test_case_10",
                tier=EvidenceTier.REPRODUCED,
                category="shared_state",
                polluter_test_id="test_case_09",
            ),
        }
    ]

    provider = CachedReplayProvider()
    for variant in ABLATION_VARIANTS:
        res = evaluate_ablation_variant(cases, variant, provider)
        assert res.variant_name == variant.name
        assert res.total_cases == 1
        assert 0.0 <= res.accuracy <= 1.0
        assert 0.0 <= res.ece <= 1.0
