# Prompts

## No-tests flow: the test generator (`flakeguard/notest/generator.py`)

One request per risky spot. The template below is copied from `_GENERATION_PROMPT_TEMPLATE` when this file was written; its SHA-256 is `4020ea560998e07b8cd6b51955f2e3b1e20ce671162d2b36f99af2d5bca5500b`.

```text
You are FlakeGuard's automated test synthesis engine.
Your task is to write a clean, focused, deterministic pytest test for a function containing a risky site ({risk_category}).

IMPORTANT SPECIFICATION:
1. Generated tests record current behaviour at HEAD.
2. The test must import the target module and call the function with reasonable inputs.
3. The test must assert the current return value or state.
4. Output ONLY valid Python code inside a ```python ``` block.

--- TARGET FILE: {file_path} ---
--- TARGET FUNCTION: {function_name} (Line {line_number}) ---
--- DETECTED RISK: {risk_category} ---
{explanation}

--- RELEVANT SOURCE CODE ---
{source_snippet}

Write a pytest test function `test_current_{function_name}()` that exercises this function and records current behaviour:
```

Placeholders: `risk_category`, `file_path`, `function_name`, `line_number`, `explanation` (the scanner's one-line reason) and `source_snippet` (the whole source file of the spot).

**Model and decoding for the recorded scan.** `llama3.2:3b` through a local Ollama (`/api/generate`), temperature 0, seed 42, `num_ctx` 16384, `num_predict` 1000, no output format, no retry, no cache (`flakeguard/notest/provider.py`). The older `LocalOllamaProvider` asks for `format=json`, which would never return a Python code block, so the no-tests flow does not use it. If Ollama does not answer, `scripts/run_no_tests.py` stops; it does not replay cached text.

**What is kept.** `flakeguard/notest/validator.py`: the test passes at HEAD, and gives the same result in k runs with `--randomly-seed` 1 to k (default k = 5). The mutation check is not run. A test whose reply had no `def test_current_<function>` is replaced by a generic template and marked as such in the scan notes (`GeneratedTest.from_template`).

## Other prompts in this repository

* Triage prompts v1 to v3: `prompts/v1.txt`, `prompts/v2.txt`, `prompts/v3.txt` (Eval 2).
* RQ4 diagnosis and fix prompts: `scripts/run_rq4.py` (`PROMPTS`, `FIX_PROMPT`); their hashes are in `results/injected/rq4.json` under `provenance.prompt`.
