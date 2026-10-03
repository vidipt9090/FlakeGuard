"""
flakeguard.parser.junit
~~~~~~~~~~~~~~~~~~~~~~~
Parse JUnit XML files produced by pytest and write a run_table Parquet file.

Usage:
    python -m flakeguard.parser.junit <artifacts_dir> <output_parquet>

Example:
    python -m flakeguard.parser.junit artifacts/ data/run_table.parquet
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from flakeguard.parser.redact import redact

# ---------------------------------------------------------------------------
# Schema fields (README.md section 3):
# repo, sha, run_id, test_id, outcome, duration_s, order_index, seed, py_version, log_path
# ---------------------------------------------------------------------------

_CACHETOOLS_SHA = "3c082c654c2804b9354e4b62dbd2994f1aac464d"
_DEFAULT_REPO = "cachetools"
_DEFAULT_PY_VERSION = "3.12"


def _parse_run_id_and_seed(filename: str) -> tuple[int, int]:
    """Extract run_id and seed from a filename like 'junit-3.xml'."""
    m = re.search(r"junit-(\d+)", filename)
    if m:
        run_id = int(m.group(1))
        return run_id, run_id  # seed == run_id in collect.yml
    return 0, 0


def parse_junit_file(
    xml_path: Path,
    repo: str = _DEFAULT_REPO,
    sha: str = _CACHETOOLS_SHA,
    py_version: str = _DEFAULT_PY_VERSION,
    log_root: Path | None = None,
) -> list[dict]:
    """Return a list of row dicts for run_table from one JUnit XML file."""
    run_id, seed = _parse_run_id_and_seed(xml_path.name)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # JUnit XML root may be <testsuites> or <testsuite>
    suites = (
        root.findall("testsuite") if root.tag == "testsuites" else [root]
    )

    rows: list[dict] = []
    order_index = 0
    for suite in suites:
        for tc in suite.findall("testcase"):
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            test_id = f"{classname}::{name}" if classname else name

            duration_s = float(tc.get("time", "0") or "0")

            # Determine outcome
            if tc.find("failure") is not None:
                outcome = "failed"
            elif tc.find("error") is not None:
                outcome = "error"
            elif tc.find("skipped") is not None:
                outcome = "skipped"
            else:
                outcome = "passed"

            # Log path (sibling log file)
            log_path = ""
            if log_root is not None:
                candidate = log_root / f"log-{run_id}.txt"
                if candidate.exists():
                    log_path = str(candidate)

            rows.append(
                {
                    "repo": repo,
                    "sha": sha,
                    "run_id": run_id,
                    "test_id": redact(test_id),
                    "outcome": outcome,
                    "duration_s": duration_s,
                    "order_index": order_index,
                    "seed": seed,
                    "py_version": py_version,
                    "log_path": log_path,
                }
            )
            order_index += 1

    return rows


def parse_artifacts_dir(
    artifacts_dir: Path,
    output_parquet: Path,
    repo: str = _DEFAULT_REPO,
    sha: str = _CACHETOOLS_SHA,
) -> pd.DataFrame:
    """Parse all junit-*.xml files under artifacts_dir and write Parquet."""
    xml_files = sorted(artifacts_dir.rglob("junit-*.xml"))
    if not xml_files:
        print(f"[warn] No junit-*.xml files found under {artifacts_dir}", file=sys.stderr)

    all_rows: list[dict] = []
    for xml_path in xml_files:
        rows = parse_junit_file(xml_path, repo=repo, sha=sha, log_root=xml_path.parent)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)

    if df.empty:
        # Create empty dataframe with correct schema
        df = pd.DataFrame(
            columns=[
                "repo", "sha", "run_id", "test_id", "outcome",
                "duration_s", "order_index", "seed", "py_version", "log_path",
            ]
        )

    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_parquet, index=False)

    # Print per-test pass rate summary
    if not df.empty:
        summary = (
            df.groupby("test_id")["outcome"]
            .apply(lambda s: (s == "passed").mean())
            .rename("pass_rate")
            .reset_index()
            .sort_values("pass_rate")
        )
        print(f"\n{'test_id':<70} {'pass_rate':>10}")
        print("-" * 82)
        for _, row in summary.iterrows():
            print(f"{row['test_id']:<70} {row['pass_rate']:>10.2f}")
        print(f"\nTotal rows: {len(df)} | Unique tests: {summary.shape[0]}")
    else:
        print("No test results found.")

    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse JUnit XML artifacts into run_table.parquet"
    )
    parser.add_argument("artifacts_dir", type=Path, help="Directory with run-N/ sub-folders")
    parser.add_argument("output_parquet", type=Path, help="Output Parquet file path")
    parser.add_argument("--repo", default=_DEFAULT_REPO)
    parser.add_argument("--sha", default=_CACHETOOLS_SHA)
    args = parser.parse_args()

    parse_artifacts_dir(args.artifacts_dir, args.output_parquet, args.repo, args.sha)


if __name__ == "__main__":
    main()
