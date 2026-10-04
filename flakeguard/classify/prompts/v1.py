"""Prompt Version 1: Plain Baseline Prompt."""


def build_prompt_v1(evidence_bundle: str) -> str:
    return f"""You are a test triage assistant.
Explain why this test might be flaky using the provided evidence bundle below.

{evidence_bundle}

Provide your response in JSON format with fields: verdict, root_cause, confidence, evidence, explanation, fix_hint.
"""
