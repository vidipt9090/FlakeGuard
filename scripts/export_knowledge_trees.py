"""Export one knowledge tree and one navigation trace per benchmark case.

Run from the repo root:

    python scripts/export_knowledge_trees.py
    python scripts/export_knowledge_trees.py --repo ../cachetools --repo-name cachetools \
        --gold docs/eval1/nav-gold.json

Writes, under ``results/``:

``knowledge_trees/<case>.json``   the tree, its stats, and the full ordered
                                 trace of AST and jedi steps for that case
``nav_trace.csv``                 one row per case: tree shape and resolver
                                 counters, which is what the dashboard charts
``nav_trace_summary.json``        totals plus the three gate numbers CI reads

Why this exists as an artifact rather than a live call: the dashboard has to
open in a demo without a cachetools checkout or a warm jedi cache, and CI has
to be able to fail when the navigator's reach drops. Both need the numbers on
disk. The dashboard still re-runs the navigator live when a repo is present --
this is the floor, not the ceiling.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flakeguard.navigator.ast_nav import AstNavigator  # noqa: E402

# One row per case. Kept flat and boring so pandas, Excel and a CI log all
# read it the same way.
CSV_FIELDS = [
    "case_id",
    "label",
    "root_cause",
    # tree shape
    "tree_nodes",
    "tree_edges",
    "tree_max_depth",
    "tree_files",
    "branching_factor",
    "nodes_depth_1",
    "nodes_depth_2plus",
    # what reached them
    "edge_calls",
    "edge_infers",
    "edge_expands",
    "edge_fixture",
    "edge_fixture_builds",
    "edge_overrides",
    "edge_touches",
    "edge_smells",
    # how hard the resolvers worked
    "ast_names",
    "jedi_goto_calls",
    "jedi_infer_calls",
    "jedi_calls",
    "jedi_hits",
    "jedi_hit_rate",
    "trace_events",
    "trace_max_depth",
    "elapsed_ms",
]


def load_cases(path: Path) -> list[dict]:
    """Case ids with their labels, from either file format we keep.

    ``labels/labels.json`` is a flat list of benchmark cases keyed ``id``.
    A navigator gold set (``docs/eval1/nav-gold*.json``) is an object with
    provenance at the top and the cases under ``tests``, keyed ``test_id``.
    Both are read here so the same export runs over either.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["tests"] if isinstance(data, dict) and "tests" in data else data
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a list of cases, got {type(items).__name__}")

    out = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: expected a case object, got {item!r}")
        case_id = item.get("id") or item.get("test_id")
        if not case_id:
            raise ValueError(f"{path}: a case has neither 'id' nor 'test_id': {item!r}")
        # A pytest node id for a test function always carries "::". Catching
        # this here is not pedantry: reading the wrong level of a gold file
        # once produced nine tree files named after its metadata keys ("repo",
        # "sha", "method"), each a one-node tree, which then counted as
        # navigated cases and dragged the resolution rate down.
        if "::" not in case_id:
            raise ValueError(
                f"{path}: {case_id!r} is not a pytest node id (no '::'). "
                "This usually means the case list was read from the wrong "
                "level of the file."
            )
        out.append(
            {
                "id": case_id,
                "label": item.get("label", ""),
                "root_cause": item.get("root_cause", ""),
            }
        )
    return out


def row_for(case: dict, explained, elapsed_ms: float) -> dict:
    stats = explained.tree.stats()
    summary = explained.trace.summary()
    by_edge = stats["nodes_by_edge"]
    by_depth = stats["nodes_by_depth"]
    return {
        "case_id": case["id"],
        "label": case["label"],
        "root_cause": case["root_cause"],
        "tree_nodes": stats["nodes"],
        "tree_edges": stats["edges"],
        "tree_max_depth": stats["max_depth"],
        "tree_files": stats["files_touched"],
        "branching_factor": stats["branching_factor"],
        "nodes_depth_1": by_depth.get(1, 0),
        "nodes_depth_2plus": sum(v for k, v in by_depth.items() if k >= 2),
        "edge_calls": by_edge.get("calls", 0),
        "edge_infers": by_edge.get("infers", 0),
        "edge_expands": by_edge.get("expands", 0),
        "edge_fixture": by_edge.get("fixture", 0),
        "edge_fixture_builds": by_edge.get("fixture-builds", 0),
        "edge_overrides": by_edge.get("overrides", 0),
        "edge_touches": by_edge.get("touches", 0),
        "edge_smells": by_edge.get("smells", 0),
        "ast_names": summary["ast_names"],
        "jedi_goto_calls": summary["jedi_goto_calls"],
        "jedi_infer_calls": summary["jedi_infer_calls"],
        "jedi_calls": summary["jedi_calls"],
        "jedi_hits": summary["jedi_hits"],
        "jedi_hit_rate": summary["jedi_hit_rate"],
        "trace_events": summary["events"],
        "trace_max_depth": summary["max_depth"],
        "elapsed_ms": round(elapsed_ms, 2),
    }


def safe_name(case_id: str) -> str:
    """A filename that survives Windows, from a pytest node id."""
    return (
        case_id.replace("::", "__")
        .replace("/", "_")
        .replace("\\", "_")
        .replace("[", "_")
        .replace("]", "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repository checkout to navigate")
    parser.add_argument("--repo-name", default="synthetic", help="repo label in chunk ids")
    parser.add_argument("--sha", default="local", help="commit label in chunk ids")
    parser.add_argument(
        "--gold",
        default="labels/labels.json",
        help="labels.json, or a nav gold set keyed by test id",
    )
    parser.add_argument("--out", default="results", help="output directory")
    parser.add_argument(
        "--with-text",
        action="store_true",
        help="include source text in the JSON (bigger files, offline demo)",
    )
    parser.add_argument(
        "--min-nodes",
        type=int,
        default=2,
        help="a tree with fewer nodes than this counts as a miss",
    )
    args = parser.parse_args(argv)

    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = REPO_ROOT / gold_path
    if not gold_path.is_file():
        print(f"error: {gold_path} not found", file=sys.stderr)
        return 2

    cases = load_cases(gold_path)
    if not cases:
        print(f"error: no cases in {gold_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    tree_dir = out_dir / "knowledge_trees"
    tree_dir.mkdir(parents=True, exist_ok=True)

    nav = AstNavigator(args.repo, repo=args.repo_name, sha=args.sha)

    rows: list[dict] = []
    misses: list[str] = []
    print(f"Navigating {len(cases)} case(s) in {Path(args.repo).resolve()}\n")
    print(f"{'case':<52} {'nodes':>5} {'depth':>5} {'jedi':>5} {'hit%':>6} {'ms':>7}")
    print("-" * 84)

    for case in cases:
        started = time.perf_counter()
        explained = nav.explain(case["id"])
        elapsed_ms = (time.perf_counter() - started) * 1000

        payload = explained.to_dict(include_text=args.with_text)
        payload["label"] = case["label"]
        payload["root_cause"] = case["root_cause"]
        payload["rendered"] = explained.tree.render()
        payload["rows"] = explained.tree.rows()
        (tree_dir / f"{safe_name(case['id'])}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

        row = row_for(case, explained, elapsed_ms)
        rows.append(row)
        if row["tree_nodes"] < args.min_nodes:
            misses.append(case["id"])

        short = case["id"].split("/")[-1]
        print(
            f"{short:<52} {row['tree_nodes']:>5} {row['tree_max_depth']:>5} "
            f"{row['jedi_calls']:>5} {row['jedi_hit_rate'] * 100:>5.1f}% "
            f"{row['elapsed_ms']:>7.1f}"
        )

    csv_path = out_dir / "nav_trace.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    resolved = len(rows) - len(misses)
    total_jedi = sum(r["jedi_calls"] for r in rows)
    total_hits = sum(r["jedi_hits"] for r in rows)
    summary = {
        "repo": args.repo_name,
        "sha": args.sha,
        "gold": str(gold_path.relative_to(REPO_ROOT)) if gold_path.is_relative_to(REPO_ROOT) else str(gold_path),
        "cases": len(rows),
        "resolved": resolved,
        "resolution_rate": round(resolved / len(rows), 4),
        "unresolved_cases": misses,
        "mean_tree_nodes": round(sum(r["tree_nodes"] for r in rows) / len(rows), 2),
        "mean_tree_depth": round(sum(r["tree_max_depth"] for r in rows) / len(rows), 2),
        "max_tree_depth": max(r["tree_max_depth"] for r in rows),
        "trees_with_depth_2plus": sum(1 for r in rows if r["tree_max_depth"] >= 2),
        "mean_ast_names": round(sum(r["ast_names"] for r in rows) / len(rows), 2),
        "total_jedi_calls": total_jedi,
        "jedi_hit_rate": round(total_hits / total_jedi, 4) if total_jedi else 0.0,
        "median_ms": round(sorted(r["elapsed_ms"] for r in rows)[len(rows) // 2], 2),
        "max_ms": round(max(r["elapsed_ms"] for r in rows), 2),
    }
    (out_dir / "nav_trace_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("-" * 84)
    print(f"  cases                 : {summary['cases']}")
    print(f"  resolved (>= {args.min_nodes} nodes) : {resolved} ({summary['resolution_rate']:.1%})")
    print(f"  mean tree nodes       : {summary['mean_tree_nodes']}")
    print(f"  mean / max tree depth : {summary['mean_tree_depth']} / {summary['max_tree_depth']}")
    print(f"  trees reaching depth 2+: {summary['trees_with_depth_2plus']}")
    print(f"  jedi calls            : {summary['total_jedi_calls']}")
    print(f"  jedi hit rate         : {summary['jedi_hit_rate']:.1%}")
    print(f"  median / max latency  : {summary['median_ms']} ms / {summary['max_ms']} ms")
    print(f"\n  trees -> {tree_dir.relative_to(REPO_ROOT)}/")
    print(f"  csv   -> {csv_path.relative_to(REPO_ROOT)}")
    print(f"  summary -> {(out_dir / 'nav_trace_summary.json').relative_to(REPO_ROOT)}")
    if misses:
        print(f"\n  WARNING: {len(misses)} case(s) resolved to nothing:")
        for case_id in misses:
            print(f"    - {case_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
