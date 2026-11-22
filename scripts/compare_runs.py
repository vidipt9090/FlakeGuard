"""Compare a second execution of scripts/run_eval.py (for example on a clean checkout) with the committed results.

    python scripts/compare_runs.py <other results dir> [--out results/clean_rerun_comparison.json]

Prints and stores, per label type and method row, the found-flaky and wrongly-flagged counts of both executions, whether every
per-test call is identical, and the RQ2 headline numbers. It reads files only; nothing is estimated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def family(method: str) -> str:
    return "b1" if method == "b1_fixed_order" else "b2" if method.startswith("b2") else "b3" if method.startswith("b3") else "perturbation"


def compare(label: str, other: Path) -> dict:
    a = json.loads((REPO / "results" / label / "rq1.json").read_text(encoding="utf-8"))
    b = json.loads((other / label / "rq1.json").read_text(encoding="utf-8"))
    rows = []
    for r, s in zip(a["rows"], b["rows"], strict=True):
        assert (r["method"], r["full_suite_runs"]) == (s["method"], s["full_suite_runs"])
        k = lambda x: (x["all_tests"]["flaky_found"]["k"], x["all_tests"]["wrongly_flagged_flaky"]["k"])  # noqa: E731
        rows.append({"method": r["method"], "family": family(r["method"]), "n": r["full_suite_runs"],
                     "committed": {"found": k(r)[0], "wrongly_flagged": k(r)[1]}, "rerun": {"found": k(s)[0], "wrongly_flagged": k(s)[1]},
                     "found_difference": abs(k(r)[0] - k(s)[0]), "every_per_test_call_identical": r["per_test"] == s["per_test"]})
    x = json.loads((REPO / "results" / label / "rq2.json").read_text(encoding="utf-8"))
    y = json.loads((other / label / "rq2.json").read_text(encoding="utf-8"))
    head = lambda d: {"mean_runs_per_test": d["runs_to_decision_adaptive"]["mean"],  # noqa: E731
                      "flaky_found_adaptive": d["tradeoff"]["flaky_found_adaptive"]["k"],
                      "flaky_found_fixed_20": d["tradeoff"]["flaky_found_fixed_20"]["k"],
                      "whole_suite_runs_saved": d["tradeoff"]["whole_suite_runs_saved"]["k"],
                      "decisions_adaptive": d["decisions_adaptive"]}
    return {
        "label": label,
        "committed": {"commit": a["provenance"]["commit"][:7], "started_local": a["provenance"]["clock"]["local"]},
        "rerun": {"commit": b["provenance"]["commit"][:7], "started_local": b["provenance"]["clock"]["local"],
                  "tracked_files_modified": b["provenance"]["tracked_files_modified"]},
        "labels_sha256_equal": a["provenance"]["dataset"]["labels_sha256"] == b["provenance"]["dataset"]["labels_sha256"],
        "rows": rows,
        "max_found_difference_by_family": {f: max(r["found_difference"] for r in rows if r["family"] == f)
                                           for f in sorted({r["family"] for r in rows})},
        "rq2": {"committed": head(x), "rerun": head(y), "per_test_decisions_identical": x["per_test"] == y["per_test"]},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("other", type=Path, help="the other execution's results folder (contains planted/ and injected/)")
    ap.add_argument("--out", default="results/clean_rerun_comparison.json")
    args = ap.parse_args(argv)
    doc = {"what": "A second execution of the same commands on a clean checkout, compared with the committed results.",
           "labels": [compare(label, args.other) for label in ("planted", "injected")]}
    for d in doc["labels"]:
        print(f"== {d['label']}: committed {d['committed']['commit']} vs rerun {d['rerun']['commit']} (modified={d['rerun']['tracked_files_modified']}); labels sha equal: {d['labels_sha256_equal']}")
        for r in d["rows"]:
            print(f"   {r['method'][:44]:44}{r['n']:>3}  {r['committed']['found']:>3}/{r['committed']['wrongly_flagged']:<3} -> {r['rerun']['found']:>3}/{r['rerun']['wrongly_flagged']:<3}  identical={r['every_per_test_call_identical']}  [{r['family']}]")
        print(f"   largest found-flaky difference by family: {d['max_found_difference_by_family']}")
        print(f"   RQ2 committed {d['rq2']['committed']}\n   RQ2 rerun     {d['rq2']['rerun']}\n   per-test decisions identical: {d['rq2']['per_test_decisions_identical']}")
    (REPO / args.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
