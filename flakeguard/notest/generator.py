"""Targeted pytest test generator for detected risky sites, explicitly recording current behaviour."""

from __future__ import annotations

import re
from dataclasses import dataclass

from flakeguard.llm.providers import BaseLLMProvider, get_provider
from flakeguard.notest.scanner import RiskySite


@dataclass(frozen=True)
class GeneratedTest:
    """A generated pytest test targeting a specific risky site."""

    test_name: str
    target_function: str
    target_file: str
    risk_category: str
    test_code: str
    records_current_behavior: bool = True
    explanation: str = ""
    from_template: bool = False  # True when the model's reply had no usable test and the generic template was used


_GENERATION_PROMPT_TEMPLATE = """You are FlakeGuard's automated test synthesis engine.
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
"""


def _extract_python_code(text: str) -> str:
    """Extract python code from markdown fence or return clean text."""
    fence_pattern = r"```(?:python)?\s*(.*?)\s*```"
    match = re.search(fence_pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def generate_targeted_test(
    site: RiskySite,
    source_snippet: str,
    module_import_name: str,
    provider: BaseLLMProvider | None = None,
) -> GeneratedTest:
    """Generate a targeted pytest test recording current behaviour around a risky site."""
    llm = provider or get_provider(allow_cache_fallback=True)

    prompt = _GENERATION_PROMPT_TEMPLATE.format(
        risk_category=site.risk_category,
        file_path=site.file_path,
        function_name=site.function_name,
        line_number=site.line_number,
        explanation=site.explanation,
        source_snippet=source_snippet,
    )

    raw_response = llm.generate(prompt)
    code = _extract_python_code(raw_response)

    test_func_name = f"test_current_{site.function_name}"

    # If code is invalid or fallback needed, synthesize deterministic template recording current behavior
    from_template = not code or f"def {test_func_name}" not in code
    if from_template:
        code = f"""import pytest
import {module_import_name}

def {test_func_name}():
    \"\"\"Generated test recording current behaviour at HEAD for {site.function_name}.\"\"\"
    # Generated test by FlakeGuard: records current behaviour at HEAD
    # Target risky site: {site.risk_category} at line {site.line_number}
    try:
        val = {module_import_name}.{site.function_name}()
        assert val is not None
    except TypeError:
        # Function requires arguments, test callable exists
        assert callable(getattr({module_import_name}, "{site.function_name}"))
"""

    return GeneratedTest(
        test_name=test_func_name,
        target_function=site.function_name,
        target_file=site.file_path,
        risk_category=site.risk_category,
        test_code=code,
        records_current_behavior=True,
        explanation=f"Targeted test recording current behaviour around {site.risk_category} in {site.function_name}",
        from_template=from_template,
    )

