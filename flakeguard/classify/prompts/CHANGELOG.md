# Prompts Changelog

## v1: Plain Prompt (Baseline)
- Simple prompt: "Explain why this test might be flaky" accompanied by the evidence bundle.
- Minimal structural constraints; relies on base model formatting.

## v2: Structured JSON & Taxonomy
- Introduces fixed label set (`flaky`, `real`, `uncertain`).
- Restricts root cause to explicit taxonomy: `order_dep`, `shared_state`, `timing`, `network`, `randomness`, `time_tz`, `filesystem`, `none`.
- Enforces JSON schema output format.
- Adds mandatory requirement to cite evidence IDs (`E1`, `E2`, etc.).

## v3: Few-Shot Examples & Uncertainty Guard
- Adds 2 worked few-shot examples demonstrating evidence citation and root cause classification.
- Adds explicit guard instruction to output `uncertain` with confidence `0.0` when evidence is weak or insufficient.

## Refactor Prompt
- Instructs the model to rewrite a flaky test function and its supporting setup/fixtures into a deterministic, isolated test.
