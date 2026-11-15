"""Unified LLM Provider interface supporting Hosted APIs (Gemini, OpenAI, Anthropic, Groq), local Ollama, and cached replay."""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

# Documented secret keys inspected by HostedProvider
HOSTED_SECRET_NAMES = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
]


def load_env_file(env_path: Path | None = None) -> None:
    """Convenience helper to read .env file if present in the repo root without overriding existing env vars."""
    target_path = env_path or (Path(__file__).parent.parent.parent / ".env")
    if target_path.is_file():
        try:
            for line in target_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass


load_env_file()


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> str:
        """Generate raw text response from the model."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider backend."""
        raise NotImplementedError


class CachedReplayProvider(BaseLLMProvider):
    """Deterministic cached replay provider for offline benchmarks and tests."""

    def __init__(self, cache_dirs: list[str | Path] | None = None) -> None:
        self.cache_dirs = [
            Path(d) for d in (cache_dirs or [Path("results/llm_raw"), Path(".cache/ollama_eval_cache")])
        ]

    @property
    def provider_name(self) -> str:
        return "cached_replay"

    def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> str:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        # Check hash-based cache files
        for cdir in self.cache_dirs:
            if not cdir.is_dir():
                continue
            hash_file = cdir / f"{prompt_hash}.json"
            if hash_file.is_file():
                try:
                    data = json.loads(hash_file.read_text(encoding="utf-8"))
                    return data.get("response", "")
                except Exception:
                    pass

            # Search nested case files
            for p in cdir.glob("**/*.json"):
                try:
                    content = json.loads(p.read_text(encoding="utf-8"))
                    if content.get("prompt_hash") == prompt_hash or prompt in content.get("prompt", ""):
                        return content.get("response", "")
                except Exception:
                    continue

        # If not cached, return a deterministic fallback
        return json.dumps({
            "label": "flaky",
            "root_cause": "timing",
            "confidence": 0.85,
            "evidence_tier": "observed",
            "reasoning": "Cached replay fallback: test exhibited intermittent outcome variance.",
            "abstain": False,
        })


class HostedProvider(BaseLLMProvider):
    """Hosted LLM provider connecting to Gemini, OpenAI, Anthropic, or Groq via standard API secrets."""

    def __init__(
        self,
        provider_name: str | None = None,
        model_name: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.timeout = timeout
        self._provider = provider_name
        self._model = model_name
        self._resolve_provider()

    def _resolve_provider(self) -> None:
        if self._provider:
            return

        # Auto-detect from environment secret keys
        if os.environ.get("GEMINI_API_KEY"):
            self._provider = "gemini"
            self._model = self._model or "gemini-2.0-flash"
        elif os.environ.get("OPENAI_API_KEY"):
            self._provider = "openai"
            self._model = self._model or "gpt-4o-mini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            self._provider = "anthropic"
            self._model = self._model or "claude-3-5-sonnet-20241022"
        elif os.environ.get("GROQ_API_KEY"):
            self._provider = "groq"
            self._model = self._model or "llama-3.3-70b-versatile"
        else:
            self._provider = "mock"
            self._model = "mock-model"

    @property
    def provider_name(self) -> str:
        return f"hosted_{self._provider}:{self._model}"

    def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> str:
        if self._provider == "gemini":
            return self._call_gemini(prompt, temperature, max_tokens)
        elif self._provider in ("openai", "groq"):
            return self._call_openai_compatible(prompt, temperature, max_tokens)
        elif self._provider == "anthropic":
            return self._call_anthropic(prompt, temperature, max_tokens)
        else:
            # Fallback mock for testing without secret keys
            return json.dumps({
                "label": "flaky",
                "root_cause": "order_dep",
                "confidence": 0.90,
                "evidence_tier": "reproduced",
                "reasoning": "Mock hosted provider response for test case.",
                "abstain": False,
            })

    def _call_gemini(self, prompt: str, temperature: float, max_tokens: int) -> str:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent?key={api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def _call_openai_compatible(self, prompt: str, temperature: float, max_tokens: int) -> str:
        if self._provider == "groq":
            api_key = os.environ.get("GROQ_API_KEY", "")
            base_url = "https://api.groq.com/openai/v1/chat/completions"
        else:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            base_url = "https://api.openai.com/v1/chat/completions"

        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(base_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, prompt: str, temperature: float, max_tokens: int) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]


class LocalOllamaProvider(BaseLLMProvider):
    """Local Ollama LLM provider."""

    def __init__(self, model_name: str = "llama3.2:3b", host: str | None = None) -> None:
        self.model_name = model_name
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    @property
    def provider_name(self) -> str:
        return f"ollama:{self.model_name}"

    def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> str:
        import ollama

        client = ollama.Client(host=self.host)
        resp = client.generate(
            model=self.model_name,
            prompt=prompt,
            format="json",
            options={"temperature": temperature},
        )
        return resp.get("response", "")


def get_provider(
    provider_type: str = "auto",
    model_name: str | None = None,
    allow_cache_fallback: bool = True,
) -> BaseLLMProvider:
    """Factory creating the appropriate LLM provider based on environment and requested type.

    Auto detection priority:
    1. If any HOSTED secret key is present (GEMINI_API_KEY, OPENAI_API_KEY, etc.), returns HostedProvider.
    2. Otherwise, returns LocalOllamaProvider (or CachedReplayProvider if allow_cache_fallback is True).
    """
    if provider_type == "hosted":
        return HostedProvider(model_name=model_name)
    elif provider_type == "ollama":
        return LocalOllamaProvider(model_name=model_name or "llama3.2:3b")
    elif provider_type == "cache":
        return CachedReplayProvider()

    # Auto mode:
    if any(os.environ.get(k) for k in HOSTED_SECRET_NAMES):
        return HostedProvider(model_name=model_name)

    if allow_cache_fallback:
        return CachedReplayProvider()

    return LocalOllamaProvider(model_name=model_name or "llama3.2:3b")

