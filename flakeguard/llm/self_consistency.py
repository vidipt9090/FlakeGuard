"""k-vote self-consistency sampling, confidence estimation, and selective abstention."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from flakeguard.llm.providers import BaseLLMProvider
from flakeguard.llm.schema import VerdictOutput, parse_and_validate_verdict


@dataclass
class SelfConsistencyResult:
    """Outcome of k-vote self-consistency sampling."""

    final_verdict: VerdictOutput
    k: int
    valid_samples_count: int
    label_votes: dict[str, int]
    root_cause_votes: dict[str, int]
    agreement_ratio: float
    raw_responses: list[str] = field(default_factory=list)


def run_self_consistency(
    prompt: str,
    provider: BaseLLMProvider,
    k: int = 3,
    temperature: float = 0.7,
    min_agreement: float = 0.60,
    abstain_threshold: float = 0.60,
    max_retries_per_sample: int = 2,
) -> SelfConsistencyResult:
    """Sample k responses, vote on label and root cause, and apply selective abstention.

    Args:
        prompt: The evaluation prompt string.
        provider: LLM provider instance.
        k: Number of samples to draw.
        temperature: Sampling temperature for diversity (default 0.7; 0.0 for k=1).
        min_agreement: Minimum fraction of agreeing votes required before abstaining.
        abstain_threshold: Minimum average confidence required before abstaining.
        max_retries_per_sample: Retries if raw response fails schema validation.
    """
    valid_verdicts: list[VerdictOutput] = []
    raw_responses: list[str] = []

    eff_temp = 0.0 if k == 1 else temperature

    for _ in range(k):
        raw_text = ""
        verdict: VerdictOutput | None = None

        for retry in range(max_retries_per_sample + 1):
            curr_prompt = prompt
            if retry > 0:
                curr_prompt = f"{prompt}\n\nIMPORTANT: Return ONLY a valid JSON object matching the required schema."

            raw_text = provider.generate(curr_prompt, temperature=eff_temp)
            verdict, err = parse_and_validate_verdict(raw_text)
            if verdict is not None:
                break

        raw_responses.append(raw_text)
        if verdict is not None:
            valid_verdicts.append(verdict)

    # Fallback if no valid responses
    if not valid_verdicts:
        fallback = VerdictOutput(
            label="no_evidence",
            root_cause="none",
            confidence=0.0,
            evidence_tier="none",
            reasoning="All k samples failed schema validation.",
            abstain=True,
        )
        return SelfConsistencyResult(
            final_verdict=fallback,
            k=k,
            valid_samples_count=0,
            label_votes={},
            root_cause_votes={},
            agreement_ratio=0.0,
            raw_responses=raw_responses,
        )

    # Count votes for label
    label_counts = Counter(v.label for v in valid_verdicts)
    winning_label, winning_label_votes = label_counts.most_common(1)[0]
    agreement_ratio = winning_label_votes / len(valid_verdicts)

    # Voters that chose the winning label
    aligned_voters = [v for v in valid_verdicts if v.label == winning_label]

    # Count root causes among aligned voters
    rc_counts = Counter(v.root_cause for v in aligned_voters)
    winning_rc, _ = rc_counts.most_common(1)[0]

    # Mean confidence among aligned voters
    mean_conf = sum(v.confidence for v in aligned_voters) / len(aligned_voters)

    # Highest evidence tier among aligned voters
    tier_order = ["none", "observed", "reproduced", "intervention-confirmed"]
    highest_tier = max(
        (v.evidence_tier for v in aligned_voters),
        key=lambda t: tier_order.index(t) if t in tier_order else 0,
    )

    # Representative reasoning
    rep_reasoning = aligned_voters[0].reasoning

    # Selective Abstention check
    should_abstain = False
    if agreement_ratio < min_agreement:
        should_abstain = True
        rep_reasoning = (
            f"[ABSTAIN] Insufficient voter consensus: agreement ratio {agreement_ratio:.2f} "
            f"is below threshold {min_agreement:.2f}. Votes: {dict(label_counts)}"
        )
    elif mean_conf < abstain_threshold:
        should_abstain = True
        rep_reasoning = (
            f"[ABSTAIN] Low model confidence: mean confidence {mean_conf:.2f} "
            f"is below threshold {abstain_threshold:.2f}."
        )

    final_verdict = VerdictOutput(
        label=winning_label,
        root_cause=winning_rc,
        confidence=round(mean_conf, 4),
        evidence_tier=highest_tier,
        reasoning=rep_reasoning,
        abstain=should_abstain,
    )

    return SelfConsistencyResult(
        final_verdict=final_verdict,
        k=k,
        valid_samples_count=len(valid_verdicts),
        label_votes=dict(label_counts),
        root_cause_votes=dict(rc_counts),
        agreement_ratio=round(agreement_ratio, 4),
        raw_responses=raw_responses,
    )

