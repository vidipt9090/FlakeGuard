"""Build synthetic mutant benchmark test cases."""

from __future__ import annotations

import json
from pathlib import Path

from flakeguard.inject.operators import apply_all_operators


def build_mutant_suite(source_dir: Path, output_dir: Path, labels_output: Path) -> list[dict]:
    """Inject mutation operators into source files and write ground-truth labels."""
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_output.parent.mkdir(parents=True, exist_ok=True)

    mutants = []
    labels = []

    for py_file in sorted(source_dir.glob("**/*.py")):
        if py_file.name.startswith("test_"):
            continue
        code = py_file.read_text(encoding="utf-8")
        file_mutants = apply_all_operators(code, str(py_file))
        for m in file_mutants:
            mutants.append(m)
            labels.append({
                "id": f"{m.file_path}::{m.operator_name}_{m.line_number}",
                "label": "flaky",
                "root_cause": m.root_cause,
                "file_path": m.file_path,
                "line_number": m.line_number,
                "diff": m.diff,
            })

    labels_output.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    return labels

