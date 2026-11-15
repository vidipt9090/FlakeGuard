"""Polluter fix generator proposing teardown fixtures to eliminate state leakage."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def propose_teardown_fix(
    polluter_test_id: str,
    leaked_state_var: str,
    test_file_path: Path | str,
) -> dict[str, Any]:
    """Generate a clean pytest teardown fixture patch to isolate leaked mutable state."""
    path = Path(test_file_path)
    clean_var_name = leaked_state_var.strip()
    fixture_code = (
        f"\n\n@pytest.fixture(autouse=True)\n"
        f"def _cleanup_{clean_var_name}():\n"
        f"    yield\n"
        f"    # FlakeGuard Automated Fix: Reset shared mutable state after test execution\n"
        f"    try:\n"
        f"        {clean_var_name}.clear()\n"
        f"    except Exception:\n"
        f"        pass\n"
    )

    diff = (
        f"--- a/{path.name}\n"
        f"+++ b/{path.name}\n"
        f"@@ -1,5 +1,12 @@\n"
        f"+import pytest\n"
        f"+{fixture_code.replace(chr(10), chr(10) + '+')}"
    )

    return {
        "polluter_test_id": polluter_test_id,
        "target_file": str(path),
        "leaked_var": clean_var_name,
        "proposed_fixture": fixture_code,
        "patch_diff": diff,
        "status": "ready_for_review",
    }

