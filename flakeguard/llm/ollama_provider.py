from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any

import ollama
from pydantic import BaseModel, Field, ValidationError


class EvidenceItem(BaseModel):
    id: str = Field(description="Evidence identifier, e.g., E1, E2")
    type: str = Field(default="static", description="Type of evidence: static, dynamic, log")
    strength: str = Field(default="strong", description="Strength: strong, medium, weak")


class LLMOutputSchema(BaseModel):
    verdict: str = Field(description="Verdict: flaky, real, uncertain")
    root_cause: str = Field(
        description="Root cause: order_dep, shared_state, timing, network, randomness, time_tz, filesystem, none"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    evidence: list[EvidenceItem] = Field(default_factory=list, description="List of cited evidence IDs")
    explanation: str = Field(default="", description="Detailed explanation of the verdict and root cause")
    fix_hint: str = Field(default="", description="Suggested fix or refactor hint to resolve flakiness")


FALLBACK_RESULT: dict[str, Any] = {
    "verdict": "uncertain",
    "root_cause": "none",
    "confidence": 0.0,
    "evidence": [],
    "explanation": "Failed to parse or validate LLM output JSON",
    "fix_hint": "",
}


def _safe_int(val: Any) -> int:
    try:
        return int(val)
    except Exception:
        return 0


class OllamaProvider:
    """Ollama LLM provider implementing LLMProvider protocol with caching, schema validation, and logging."""

    def __init__(
        self,
        model_name: str = "llama3.2:3b",
        cache_dir: str = ".cache/ollama_cache",
        log_file: str = ".cache/llm_calls.jsonl",
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.log_file = log_file
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.log_file) or ".", exist_ok=True)

    def _get_cache_key(self, prompt: str, schema: dict) -> str:
        raw_key = f"{self.model_name}:{prompt}:{json.dumps(schema, sort_keys=True)}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _log_call(
        self,
        prompt: str,
        tokens_in: int,
        tokens_out: int,
        latency_s: float,
        cached: bool,
        error: str | None = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "model": self.model_name,
            "prompt_length": len(prompt),
            "tokens_in": _safe_int(tokens_in),
            "tokens_out": _safe_int(tokens_out),
            "latency_s": round(float(latency_s), 4),
            "cached": cached,
            "error": error,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def validate_and_parse(self, response_text: str) -> dict[str, Any]:
        """Validate JSON string against LLMOutputSchema."""
        data = json.loads(response_text)
        validated = LLMOutputSchema.model_validate(data)
        return validated.model_dump()

    def generate(self, prompt: str, schema: dict | None = None) -> dict[str, Any]:
        """Generate response from Ollama model adhering to contract."""
        if schema is None:
            schema = LLMOutputSchema.model_json_schema()

        cache_key = self._get_cache_key(prompt, schema)
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")

        # Check Cache
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                self._log_call(prompt, 0, 0, 0.0, cached=True)
                return cached_data
            except Exception:
                pass  # Recompute if cache is corrupted

        start_time = time.time()
        tokens_in = 0
        tokens_out = 0

        # Attempt 1
        try:
            res = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                format=schema,
                options={"temperature": 0.0},
            )
            latency_s = time.time() - start_time
            tokens_in = _safe_int(getattr(res, "prompt_eval_count", 0))
            tokens_out = _safe_int(getattr(res, "eval_count", 0))

            response_text = res.response
            result_dict = self.validate_and_parse(response_text)

            # Save to Cache
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2)

            self._log_call(prompt, tokens_in, tokens_out, latency_s, cached=False)
            return result_dict

        except (ValidationError, json.JSONDecodeError) as err:
            # Retry Once with Error Feedback
            retry_prompt = (
                f"{prompt}\n\n"
                f"Your previous output was invalid JSON or failed schema validation with error: {str(err)}.\n"
                f"Please output strictly valid JSON matching the schema."
            )
            try:
                retry_start = time.time()
                res_retry = ollama.generate(
                    model=self.model_name,
                    prompt=retry_prompt,
                    format=schema,
                    options={"temperature": 0.0},
                )
                latency_s += time.time() - retry_start
                tokens_in += _safe_int(getattr(res_retry, "prompt_eval_count", 0))
                tokens_out += _safe_int(getattr(res_retry, "eval_count", 0))

                result_dict = self.validate_and_parse(res_retry.response)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(result_dict, f, indent=2)

                self._log_call(prompt, tokens_in, tokens_out, latency_s, cached=False)
                return result_dict
            except Exception as retry_err:
                self._log_call(
                    prompt,
                    tokens_in,
                    tokens_out,
                    time.time() - start_time,
                    cached=False,
                    error=str(retry_err),
                )
                return FALLBACK_RESULT
        except Exception as e:
            self._log_call(
                prompt,
                tokens_in,
                tokens_out,
                time.time() - start_time,
                cached=False,
                error=str(e),
            )
            return FALLBACK_RESULT
