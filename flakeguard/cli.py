"""FlakeGuard CLI: Entry point for `flakeguard` commands."""

from __future__ import annotations

import argparse
import sys

from flakeguard.runner.orchestrator import ScanConfig, scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flakeguard",
        description="FlakeGuard: PR-native CI/CD framework for flaky test detection, diagnosis, and quarantine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # `flakeguard scan <repo-url|path>`
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan a target repository across the perturbation matrix to detect flakiness.",
    )
    scan_parser.add_argument(
        "target",
        help="Target repository local path or remote Git URL.",
    )
    scan_parser.add_argument(
        "--sha",
        default=None,
        help="Pin execution to a specific Git commit SHA.",
    )
    scan_parser.add_argument(
        "--shuffled-n",
        type=int,
        default=5,
        help="Number of shuffled runs in the perturbation matrix (default: 5).",
    )
    scan_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds per test slice execution (default: 60.0).",
    )
    scan_parser.add_argument(
        "--docker",
        action="store_true",
        default=False,
        help="Execute runs inside Docker sandbox using python:3.12-slim.",
    )
    scan_parser.add_argument(
        "--output-events",
        default=None,
        help="Path to write the single-source-of-truth JSONL event log.",
    )
    scan_parser.add_argument(
        "--output-artifacts",
        default=None,
        help="Directory to save JUnit XML reports and execution artifacts.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        config = ScanConfig(
            target=args.target,
            sha=args.sha,
            shuffled_n=args.shuffled_n,
            timeout=args.timeout,
            use_docker=args.docker,
            output_events=args.output_events,
            output_artifacts=args.output_artifacts,
        )

        print("=" * 80)
        print(f"FLAKEGUARD SCAN: {config.target}")
        print(f"Pinned SHA: {config.sha or 'HEAD'} | Shuffled Runs: {config.shuffled_n} | Sandbox: {'Docker' if config.use_docker else 'Local'}")
        print("=" * 80)

        result = scan(config)

        if not result.success:
            print("\n" + "!" * 80)
            print(f"SCAN FAILED: {result.outcome}")
            print(f"Reason: {result.reason}")
            print(f"Event Log: {result.event_log_path}")
            print("!" * 80)
            return 1

        print("\n" + "=" * 80)
        print("SCAN COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print(f"Run ID: {result.run_id}")
        print(f"Pinned SHA: {result.pinned_sha}")
        print(f"Event Log: {result.event_log_path}")
        print(f"Total Perturbation Slices: {result.total_slices}")
        print(f"Total Unique Tests: {result.total_tests}")
        print(f"Detected Flaky Tests ({len(result.flaky_tests)}):")
        for ft in result.flaky_tests:
            stats = result.test_summaries.get(ft, {})
            print(f"  - {ft:<60} (Fail rate: {stats.get('failure_rate', 0.0) * 100:.1f}%)")
        print("=" * 80)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

