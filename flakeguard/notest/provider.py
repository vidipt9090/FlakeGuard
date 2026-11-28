"""A local Ollama provider for the no-tests flow.

``flakeguard.llm.providers.LocalOllamaProvider`` asks Ollama for ``format="json"``. The generator below asks for a Python code
block, so a JSON-only reply never contains ``def test_current_<name>`` and every test would fall back to the generic template.
This provider sends no output format, fixes temperature, seed and context size, and refuses to run when Ollama is not reachable:
it never replays a cached answer, so a test is marked as written by the model only when the model wrote it.
"""

from __future__ import annotations

import json
import os
import urllib.request

from flakeguard.llm.providers import BaseLLMProvider

MODEL = "llama3.2:3b"
SEED = 42
NUM_CTX = 16384


class OllamaUnavailable(RuntimeError):
    """Ollama did not answer; the flow stops instead of falling back to canned text."""


class PlainOllamaProvider(BaseLLMProvider):
    """``/api/generate`` with temperature, seed and ``num_ctx`` set, free-form output, no cache."""

    def __init__(self, model_name: str = MODEL, host: str | None = None) -> None:
        self.model_name = model_name
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host

    @property
    def provider_name(self) -> str:
        return f"ollama:{self.model_name}"

    def _call(self, path: str, body: dict | None = None, timeout: float = 600.0) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.host + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except OSError as exc:  # refused connection, timeout, HTTP error
            raise OllamaUnavailable(f"Ollama did not answer at {self.host}: {exc}") from exc

    def version(self) -> str | None:
        return self._call("/api/version", timeout=10).get("version")

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 1000) -> str:
        body = {"model": self.model_name, "prompt": prompt, "stream": False,
                "options": {"temperature": temperature, "seed": SEED, "num_ctx": NUM_CTX, "num_predict": max_tokens}}
        return self._call("/api/generate", body).get("response", "")
