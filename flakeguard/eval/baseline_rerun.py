import csv
from collections import defaultdict


def evaluate_rerun_baseline(runs_csv_path, N):
    """Evaluates the N-run rerun baseline classifier on runs.csv for runs 1..N.

    Logic:
    - Collect outcomes for run_id <= N per test_id.
    - If outcomes contain both 'PASS' and 'FAIL', predict label = 'flaky'.
    - Else if all outcomes are 'PASS', predict label = 'stable'.
    - Else if all outcomes are 'FAIL', predict label = 'real'.

    Args:
        runs_csv_path: Path to runs.csv containing run_id, seed, test_id, outcome.
        N: Number of runs to evaluate (e.g. 5, 10, 20).

    Returns:
        Dict mapping test_id -> {'label': predicted_label, 'root_cause': 'none'}
    """
    outcomes_by_test = defaultdict(list)

    with open(runs_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            run_id = int(row["run_id"])
            if run_id <= N:
                tid = row["test_id"]
                outcome = row["outcome"].upper()
                outcomes_by_test[tid].append(outcome)

    predictions = {}
    for tid, outcomes in outcomes_by_test.items():
        unique_outcomes = set(outcomes)
        if "PASS" in unique_outcomes and "FAIL" in unique_outcomes:
            pred_label = "flaky"
        elif unique_outcomes == {"PASS"}:
            pred_label = "stable"
        elif unique_outcomes == {"FAIL"}:
            pred_label = "real"
        else:
            pred_label = "stable"

        predictions[tid] = {"label": pred_label, "root_cause": "none"}

    return predictions
