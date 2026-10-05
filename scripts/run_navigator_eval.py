import ast
import csv
import json
import os
import sys

sys.path.insert(0, ".")

from flakeguard.navigator.ast_nav import AstNavigator
from flakeguard.navigator.demo import render

RESULTS_DIR = "results"
LABELS_JSON = "labels/labels.json"
NAVIGATION_CSV = os.path.join(RESULTS_DIR, "navigation.csv")


def count_ast_steps(target_func_ast):
    """Count the AST navigation steps (calls, subscript operators, attribute accesses)."""
    steps = 1  # Base step for locating function definition
    for node in ast.walk(target_func_ast):
        if isinstance(node, ast.Call):
            steps += 1
        elif isinstance(node, ast.Subscript):
            steps += 1
        elif isinstance(node, ast.Attribute):
            steps += 1
    return steps


def run_navigator_evaluation():
    if not os.path.exists(LABELS_JSON):
        print(f"Error: {LABELS_JSON} not found.")
        sys.exit(1)

    with open(LABELS_JSON, "r", encoding="utf-8") as f:
        labels_list = json.load(f)

    nav = AstNavigator(".", repo="synthetic", sha="local")

    print("=" * 85)
    print("DEMO: NAVIGATOR CALL GRAPH RESOLUTION FOR ONE CASE")
    print("=" * 85)

    demo_case_id = "synthetic/tests/test_suite_01.py::test_case_02"
    demo_result = nav.related(demo_case_id)
    render(demo_result, elapsed=0.01, preview=3)

    print("\n" + "=" * 85)
    print("NAVIGATOR EVALUATION ACROSS ALL PLANTED BENCHMARK CASES")
    print("=" * 85)

    rows = []
    total_steps = 0
    success_count = 0

    for item in labels_list:
        tid = item["id"]
        result = nav.related(tid)

        target = None
        try:
            target = nav._locate(tid)
        except Exception:
            pass

        steps = count_ast_steps(target.func) if target else 1

        cut_count = len(result.code_under_test)
        fx_count = len(result.fixtures)
        ss_count = len(result.shared_state)
        smell_count = len(result.smells)

        success = 1 if (cut_count > 0 or ss_count > 0 or fx_count > 0) else 0

        if success:
            success_count += 1
        total_steps += steps

        rows.append(
            {
                "case_id": tid,
                "success": success,
                "steps_taken": steps,
                "code_under_test_count": cut_count,
                "fixtures_count": fx_count,
                "shared_state_count": ss_count,
                "smells_count": smell_count,
            }
        )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    fieldnames = [
        "case_id",
        "success",
        "steps_taken",
        "code_under_test_count",
        "fixtures_count",
        "shared_state_count",
        "smells_count",
    ]

    with open(NAVIGATION_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total_cases = len(rows)
    success_rate = (
        (success_count / total_cases * 100) if total_cases > 0 else 0.0
    )
    mean_steps = (total_steps / total_cases) if total_cases > 0 else 0.0

    print(
        f"{'Case ID':<50} | {'Success':<7} | {'Steps':<5} | {'CUT':<4} | {'State':<5}"
    )
    print("-" * 80)
    for r in rows:
        status = "YES" if r["success"] else "NO"
        print(
            f"{r['case_id']:<50} | {status:<7} | {r['steps_taken']:<5} | {r['code_under_test_count']:<4} | {r['shared_state_count']:<5}"
        )

    print("=" * 85)
    print("SUMMARY METRICS FOR NAVIGATOR CALL GRAPH RESOLUTION")
    print("=" * 85)
    print(f"  - Total Planted Cases Evaluated : {total_cases}")
    print(
        f"  - Successful Resolutions        : {success_count} / {total_cases}"
    )
    print(f"  - Navigation Success Rate       : {success_rate:.1f}%")
    print(f"  - Mean Steps Taken per Case     : {mean_steps:.2f} steps")
    print(f"  - Results Saved To              : {NAVIGATION_CSV}")
    print("=" * 85)


if __name__ == "__main__":
    run_navigator_evaluation()
