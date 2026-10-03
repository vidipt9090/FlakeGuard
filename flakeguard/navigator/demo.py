"""Readable navigator output for one test id.

    python -m flakeguard.navigator.demo <test_id> --repo <path-to-checkout>

Example (cachetools at the pinned sha):

    python -m flakeguard.navigator.demo \
        "tests/test_ttl.py::TTLCacheTest::test_ttl" --repo ../cachetools

This is the Eval 1 demo for the source-graph and navigation line. It prints
what the navigator found and nothing else, so the output is the evidence.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from flakeguard.contracts import Chunk, NavResult
from flakeguard.navigator.ast_nav import AstNavigator

RULE = "=" * 72


def _head(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _show(chunks: list[Chunk], *, preview: int, empty: str) -> None:
    if not chunks:
        print(f"  (none)  {empty}")
        return
    for i, chunk in enumerate(chunks, 1):
        score = f"  score {chunk.score:.0f}" if chunk.score else ""
        print(f"  {i}. {chunk.path}:{chunk.start_line}-{chunk.end_line}  [{chunk.kind}]{score}")
        if preview:
            for line in chunk.text.splitlines()[:preview]:
                print(f"       | {line}")
            if len(chunk.text.splitlines()) > preview:
                print("       | ...")


def render(result: NavResult, elapsed: float, *, preview: int = 0) -> None:
    print(RULE)
    print(f"test: {result.test_id}")
    print(RULE)

    _head(f"Code under test ({len(result.code_under_test)})")
    _show(
        result.code_under_test,
        preview=preview,
        empty="no repo-local definition resolved",
    )

    _head(f"Fixtures ({len(result.fixtures)})")
    _show(
        result.fixtures,
        preview=preview,
        empty="test takes no fixture arguments",
    )

    _head(f"Shared state ({len(result.shared_state)})")
    _show(
        result.shared_state,
        preview=preview,
        empty="no module-level mutable state reachable",
    )

    _head(f"Flakiness smells ({len(result.smells)})")
    if result.smells:
        for smell in result.smells:
            print(f"  - {smell}")
    else:
        print("  (none)  nothing nondeterministic in the reachable code")

    print(f"\nresolved in {elapsed:.2f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flakeguard.navigator.demo",
        description="Show what flakeguard's navigator finds for one test.",
    )
    parser.add_argument("test_id", help="e.g. tests/test_lru.py::LRUCacheTest::test_lru")
    parser.add_argument(
        "--repo", default=".", help="path to the repo checkout (default: current directory)"
    )
    parser.add_argument("--repo-name", default=None, help="label used in chunk ids")
    parser.add_argument("--sha", default="local", help="commit sha used in chunk ids")
    parser.add_argument(
        "--preview", type=int, default=0, metavar="N", help="print the first N lines of each chunk"
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: --repo {repo} is not a directory", file=sys.stderr)
        return 2

    nav = AstNavigator(repo, repo=args.repo_name or repo.name, sha=args.sha)
    start = time.perf_counter()
    result = nav.related(args.test_id)
    render(result, time.perf_counter() - start, preview=args.preview)

    # Exit 1 when nothing was found, so the demo can be checked in a script.
    found = result.code_under_test or result.fixtures or result.shared_state
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
