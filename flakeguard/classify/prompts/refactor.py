"""Refactor Prompt: Rewrite test to be deterministic and isolated."""


def build_refactor_prompt(evidence_bundle: str) -> str:
    return f"""You are a senior test engineer.
Rewrite the flaky test body and any required setup in the following evidence bundle so that the test becomes 100% deterministic, isolated, and order-independent.

EVIDENCE BUNDLE:
{evidence_bundle}

Provide your response in JSON format with fields:
- "original_test_id": string
- "refactored_code": string (complete Python code for the refactored test function and any fixtures)
- "explanation": string (why this refactoring eliminates flakiness)
"""
