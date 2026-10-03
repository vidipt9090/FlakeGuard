"""Prompt Version 2: Structured Taxonomy & Evidence ID Rules."""


def build_prompt_v2(evidence_bundle: str) -> str:
    return f"""You are FlakeGuard, an expert automated test triage system.
Analyze the provided test evidence bundle and determine if the failure is due to flakiness or a real bug.

RULES & TAXONOMY:
1. "verdict" MUST be one of: "flaky", "real", "uncertain".
2. "root_cause" MUST be one of: "order_dep", "shared_state", "timing", "network", "randomness", "time_tz", "filesystem", "none".
3. "confidence" MUST be a float between 0.0 and 1.0.
4. "evidence" MUST be a list of evidence objects referencing IDs present in the bundle (e.g., E1, E2, E3).
   Each item must have: {{"id": "<E1/E2/...>", "type": "static|dynamic|log", "strength": "strong|medium|weak"}}.
5. "explanation" MUST cite specific evidence IDs supporting your reasoning.
6. "fix_hint" SHOULD provide actionable guidance to fix or isolate the test.

EVIDENCE BUNDLE:
{evidence_bundle}

Output MUST strictly adhere to JSON format matching the schema.
"""
