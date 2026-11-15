"""Prompt v4 template builder combining Bayesian stats, AST navigator context, and evidence tiers."""

from __future__ import annotations

from pathlib import Path

from flakeguard.contracts import EvidenceReport
from flakeguard.stats.bayesian import BayesianFailureRate

PROMPT_V4_PATH = Path(__file__).parent.parent.parent / "prompts" / "v4.txt"


def format_bayesian_stats(b_rate: BayesianFailureRate) -> str:
    """Format Bayesian stats string for prompt inclusion."""
    ci = b_rate.credible_interval(confidence=0.95)
    mean_pct = b_rate.posterior_mean * 100.0
    low_pct = ci.lower * 100.0
    up_pct = ci.upper * 100.0
    return (
        f"Total Runs: {b_rate.runs}, Failures: {b_rate.failures}, Passes: {b_rate.passes}.\n"
        f"Posterior Mean Failure Rate: {mean_pct:.1f}% (95% Credible Interval: [{low_pct:.1f}%, {up_pct:.1f}%]).\n"
        f"Empirical Verdict: {b_rate.verdict}."
    )


def format_navigator_context(
    code_under_test: list[str] | None = None,
    shared_state: list[str] | None = None,
    smells: list[str] | None = None,
) -> str:
    """Format AST navigator context."""
    lines: list[str] = []
    if code_under_test:
        lines.append("Code Under Test:")
        for cut in code_under_test:
            lines.append(f"```python\n{cut.strip()}\n```")
    else:
        lines.append("Code Under Test: None detected")

    if shared_state:
        lines.append("Shared State Globals / Module Variables:")
        for ss in shared_state:
            lines.append(f"- {ss.strip()}")

    if smells:
        lines.append(f"Detected Code Smells: {', '.join(smells)}")

    return "\n".join(lines)


def format_evidence_tier_context(report: EvidenceReport | None = None) -> str:
    """Format empirical evidence tier and causal diagnostics."""
    if report is None:
        return "Evidence Tier: none (No perturbation evidence recorded)"

    lines = [f"Evidence Tier: {report.tier.value}"]
    if report.polluter_test_id:
        lines.append(f"Polluter Test (Bisection Confirmed): {report.polluter_test_id}")
    if report.details.get("state_setter_id"):
        lines.append(f"Prerequisite Setter Test: {report.details['state_setter_id']}")
    if report.details.get("shared_state_overlap"):
        lines.append(f"Shared State Overlap: {report.details['shared_state_overlap']}")

    if report.interventions:
        lines.append("Targeted Interventions:")
        for inv in report.interventions:
            status = "FLIPPED OUTCOME" if inv.flipped else "No change"
            lines.append(f"- [{inv.kind}] ({status}): {inv.details}")

    return "\n".join(lines)


def build_prompt_v4(
    test_id: str,
    test_body: str,
    log_excerpt: str,
    b_rate: BayesianFailureRate,
    evidence_report: EvidenceReport | None = None,
    code_under_test: list[str] | None = None,
    shared_state: list[str] | None = None,
    smells: list[str] | None = None,
) -> str:
    """Construct full Prompt v4 string."""
    template = PROMPT_V4_PATH.read_text(encoding="utf-8")

    stats_str = format_bayesian_stats(b_rate)
    nav_str = format_navigator_context(code_under_test, shared_state, smells)
    evidence_str = format_evidence_tier_context(evidence_report)

    prompt = (
        template.replace("{bayesian_stats}", stats_str)
        .replace("{log_excerpt}", log_excerpt.strip() or "(None - test passed)")
        .replace("{test_body}", test_body.strip() or f"# Test {test_id}")
        .replace("{navigator_context}", nav_str)
        .replace("{evidence_tier_context}", evidence_str)
    )
    return prompt

