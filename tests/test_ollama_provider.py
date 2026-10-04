import json
from unittest.mock import MagicMock, patch

from flakeguard.llm.ollama_provider import OllamaProvider


def test_ollama_provider_success(tmp_path):
    cache_dir = tmp_path / "cache"
    log_file = tmp_path / "log.jsonl"
    provider = OllamaProvider(model_name="llama3.2:3b", cache_dir=str(cache_dir), log_file=str(log_file))

    mock_response = MagicMock()
    mock_response.response = json.dumps({
        "verdict": "flaky",
        "root_cause": "order_dep",
        "confidence": 0.9,
        "evidence": [{"id": "E1", "type": "static", "strength": "strong"}],
        "explanation": "Test depends on previous registration.",
        "fix_hint": "Isolate registration in fixture."
    })
    mock_response.prompt_eval_count = 100
    mock_response.eval_count = 50

    with patch("ollama.generate", return_value=mock_response) as mock_gen:
        res = provider.generate("Test prompt")
        assert res["verdict"] == "flaky"
        assert res["root_cause"] == "order_dep"
        assert res["confidence"] == 0.9
        assert len(res["evidence"]) == 1
        assert res["evidence"][0]["id"] == "E1"
        assert mock_gen.call_count == 1

    # Test cache hit on second call
    with patch("ollama.generate") as mock_gen_cached:
        res_cached = provider.generate("Test prompt")
        assert res_cached == res
        assert mock_gen_cached.call_count == 0


def test_ollama_provider_fallback_on_invalid_json(tmp_path):
    cache_dir = tmp_path / "cache"
    log_file = tmp_path / "log.jsonl"
    provider = OllamaProvider(model_name="llama3.2:3b", cache_dir=str(cache_dir), log_file=str(log_file))

    mock_response_invalid = MagicMock()
    mock_response_invalid.response = "Invalid JSON output"

    with patch("ollama.generate", return_value=mock_response_invalid):
        res = provider.generate("Test prompt with bad output")
        assert res["verdict"] == "uncertain"
        assert res["confidence"] == 0.0
