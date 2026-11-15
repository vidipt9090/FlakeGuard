"""Leave-one-out evidence ablation pipeline for evaluating the impact of each causal evidence component."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flakeguard.contracts import EvidenceReport
from flakeguard.eval.metrics import compute_precision_recall_f1
from flakeguard.llm.calibration import compute_ece
from flakeguard.llm.prompt_v4 import (
    format_bayesian_stats,
    format_navigator_context,
)
from flakeguard.llm.providers import BaseLLMProvider
from flakeguard.llm.schema import VerdictOutput, parse_and_validate_verdict
from flakeguard.stats.bayesian import BayesianFailureRate


@dataclass(frozen=True)
class AblationVariant:
    """Configuration for a specific leave-one-out evidence ablation condition."""

    name: str
    description: str
    include_stats: bool = True
    include_log: bool = True
    include_nav: bool = True
    include_interventions: bool = True
    include_bisection: bool = True
    include_tier: bool = True


ABLATION_VARIANTS = [
    AblationVariant(
        name="full_v4",
        description="Full Prompt v4 (All evidence: stats, nav, bisection, interventions, tiers)",
        include_stats=True,
        include_log=True,
        include_nav=True,
        include_interventions=True,
        include_bisection=True,
        include_tier=True,
    ),
    AblationVariant(
        name="minus_navigator",
        description="Leave-one-out: Minus AST Navigator context (code under test, shared globals)",
        include_stats=True,
        include_log=True,
        include_nav=False,
        include_interventions=True,
        include_bisection=True,
        include_tier=True,
    ),
    AblationVariant(
        name="minus_interventions",
        description="Leave-one-out: Minus targeted interventions (no seed, clock, TZ, or delay results)",
        include_stats=True,
        include_log=True,
        include_nav=True,
        include_interventions=False,
        include_bisection=True,
        include_tier=True,
    ),
    AblationVariant(
        name="minus_bisection",
        description="Leave-one-out: Minus polluter bisection (no polluter or setter IDs)",
        include_stats=True,
        include_log=True,
        include_nav=True,
        include_interventions=True,
        include_bisection=False,
        include_tier=True,
    ),
    AblationVariant(
        name="minimal_stats_only",
        description="Minimal baseline: Only failure stats and log excerpts (equivalent to v1/v2)",
        include_stats=True,
        include_log=True,
        include_nav=False,
        include_interventions=False,
        include_bisection=False,
        include_tier=False,
    ),
]


@dataclass
class AblationResult:
    """Metrics and predictions for an ablation variant."""

    variant_name: str
    description: str
    total_cases: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    ece: float
    abstain_rate: float
    predictions: list[VerdictOutput] = field(default_factory=list)


def build_ablated_prompt(
    test_id: str,
    test_body: str,
    log_excerpt: str,
    b_rate: BayesianFailureRate,
    evidence_report: EvidenceReport | None,
    code_under_test: list[str] | None,
    shared_state: list[str] | None,
    smells: list[str] | None,
    variant: AblationVariant,
) -> str:
    """Build prompt customized to the ablation variant's inclusions."""
    # Stats
    stats_str = format_bayesian_stats(b_rate) if variant.include_stats else "Failure Stats: Unavailable"

    # Log
    log_str = log_excerpt if variant.include_log else "Log: Unavailable"

    # Navigator
    if variant.include_nav:
        nav_str = format_navigator_context(code_under_test, shared_state, smells)
    else:
        nav_str = "AST Navigator Context: [Ablated / Excluded]"

    # Evidence & Tier
    if not (variant.include_tier or variant.include_bisection or variant.include_interventions):
        evidence_str = "Causal Evidence: [Ablated / Excluded]"
    else:
        lines: list[str] = []
        if variant.include_tier and evidence_report:
            lines.append(f"Evidence Tier: {evidence_report.tier.value}")
        if variant.include_bisection and evidence_report:
            if evidence_report.polluter_test_id:
                lines.append(f"Polluter Test: {evidence_report.polluter_test_id}")
            if evidence_report.details.get("state_setter_id"):
                lines.append(f"Setter Test: {evidence_report.details['state_setter_id']}")
        if variant.include_interventions and evidence_report and evidence_report.interventions:
            lines.append("Interventions:")
            for inv in evidence_report.interventions:
                lines.append(f"- [{inv.kind}] (flipped={inv.flipped}): {inv.details}")
        evidence_str = "\n".join(lines) if lines else "Causal Evidence: none"

    prompt = f"""You are FlakeGuard test triage assistant.
Output strictly valid JSON with keys: label ("flaky" | "real_fail" | "no_evidence"), root_cause, confidence, evidence_tier, reasoning, abstain (boolean).

--- TARGET CASE: {test_id} ---
--- BAYESIAN STATS ---
{stats_str}

--- LOG EXCERPT ---
{log_str}

--- TEST BODY ---
{test_body}

--- AST NAVIGATOR CONTEXT ---
{nav_str}

--- CAUSAL EVIDENCE ---
{evidence_str}
"""
    return prompt


def evaluate_ablation_variant(
    cases: list[dict[str, Any]],
    variant: AblationVariant,
    provider: BaseLLMProvider,
) -> AblationResult:
    """Run an ablation condition over a benchmark dataset of cases."""
    preds: list[VerdictOutput] = []
    y_true: list[str] = []
    y_pred: list[str] = []
    confidences: list[float] = []
    correct_list: list[bool] = []

    for item in cases:
        test_id = item["id"]
        ground_truth = item.get("ground_truth", item.get("label", "flaky"))
        # Normalize ground truth
        if ground_truth in ("real", "real_failure"):
            ground_truth = "real_fail"
        elif ground_truth in ("stable", "pass"):
            ground_truth = "no_evidence"

        prompt = build_ablated_prompt(
            test_id=test_id,
            test_body=item.get("test_body", f"def {test_id.split('::')[-1]}(): pass"),
            log_excerpt=item.get("log_excerpt", ""),
            b_rate=item.get("b_rate", BayesianFailureRate(test_id, runs=20, failures=4)),
            evidence_report=item.get("evidence_report"),
            code_under_test=item.get("code_under_test"),
            shared_state=item.get("shared_state"),
            smells=item.get("smells"),
            variant=variant,
        )

        raw = provider.generate(prompt)
        verdict, _ = parse_and_validate_verdict(raw)
        if verdict is None:
            verdict = VerdictOutput(
                label="no_evidence",
                root_cause="none",
                confidence=0.0,
                evidence_tier="none",
                reasoning="Parse failure",
                abstain=True,
            )

        preds.append(verdict)
        y_true.append(ground_truth)
        y_pred.append(verdict.label)
        confidences.append(verdict.confidence)
        correct_list.append(verdict.label == ground_truth)

    # Compute metrics
    prf = compute_precision_recall_f1(y_true, y_pred, pos_label="flaky")
    calib = compute_ece(confidences, correct_list, n_bins=10)
    acc = sum(correct_list) / len(correct_list) if correct_list else 0.0
    abstain_rate = sum(1 for p in preds if p.abstain) / len(preds) if preds else 0.0

    return AblationResult(
        variant_name=variant.name,
        description=variant.description,
        total_cases=len(cases),
        accuracy=round(acc, 4),
        precision=round(prf["precision"], 4),
        recall=round(prf["recall"], 4),
        f1=round(prf["f1"], 4),
        ece=calib.ece,
        abstain_rate=round(abstain_rate, 4),
        predictions=preds,
    )

