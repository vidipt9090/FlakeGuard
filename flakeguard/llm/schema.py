"""Schema definition and robust JSON parsing/retry for LLM verdicts."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


class VerdictOutput(BaseModel):
    """Schema for LLM test flakiness triage verdict."""

    label: Literal["flaky", "real_fail", "no_evidence"] = Field(
        description="Classification label: flaky, real_fail, or no_evidence"
    )
    root_cause: Literal["order_dep", "shared_state", "timing", "randomness", "time_tz", "none"] = Field(
        description="Root cause category of flakiness"
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    evidence_tier: Literal["observed", "reproduced", "intervention-confirmed", "none"] = Field(
        default="none",
        description="Tier of empirical evidence backing this verdict",
    )
    reasoning: str = Field(
        default="",
        description="Concise rationale citing specific evidence",
    )
    abstain: bool = Field(
        default=False,
        description="Whether the model abstains due to low confidence or conflicting evidence",
    )


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text, handling markdown fences or leading/trailing commentary."""
    text = text.strip()
    if not text:
        return None

    # 1. Try direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Try markdown fence ```json ... ``` or ``` ... ```
    fence_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    match = re.search(fence_pattern, text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. Try finding outermost { ... }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def normalize_verdict_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy or alternate synonyms for robust schema compatibility."""
    normalized = dict(data)

    # Normalize label
    raw_label = str(normalized.get("label", "")).strip().lower()
    if raw_label in ("real", "real_failure", "regression"):
        normalized["label"] = "real_fail"
    elif raw_label in ("stable", "pass", "no_evidence"):
        normalized["label"] = "no_evidence"
    elif raw_label in ("flaky", "flake"):
        normalized["label"] = "flaky"

    # Normalize root_cause
    raw_rc = str(normalized.get("root_cause", "")).strip().lower()
    rc_map = {
        "order": "order_dep",
        "order_dependent": "order_dep",
        "order_dep": "order_dep",
        "shared": "shared_state",
        "shared_state": "shared_state",
        "state": "shared_state",
        "timing": "timing",
        "concurrency": "timing",
        "race": "timing",
        "random": "randomness",
        "randomness": "randomness",
        "timezone": "time_tz",
        "time": "time_tz",
        "time_tz": "time_tz",
        "none": "none",
    }
    normalized["root_cause"] = rc_map.get(raw_rc, "none")

    # Normalize evidence_tier
    raw_tier = str(normalized.get("evidence_tier", "")).strip().lower()
    if "intervention" in raw_tier:
        normalized["evidence_tier"] = "intervention-confirmed"
    elif "reproduced" in raw_tier:
        normalized["evidence_tier"] = "reproduced"
    elif "observed" in raw_tier:
        normalized["evidence_tier"] = "observed"
    else:
        normalized["evidence_tier"] = "none"

    # Confidence bounds
    try:
        conf = float(normalized.get("confidence", 0.0))
        normalized["confidence"] = max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        normalized["confidence"] = 0.0

    return normalized


def parse_and_validate_verdict(raw_text: str) -> tuple[VerdictOutput | None, str | None]:
    """Parse text and validate against VerdictOutput schema.

    Returns:
        (VerdictOutput, None) if successful, or (None, error_description) if failed.
    """
    raw_dict = extract_json_from_text(raw_text)
    if raw_dict is None:
        return None, "Failed to locate valid JSON object in response text"

    norm_dict = normalize_verdict_dict(raw_dict)
    try:
        output = VerdictOutput.model_validate(norm_dict)
        return output, None
    except ValidationError as e:
        return None, f"Schema validation error: {str(e)}"

