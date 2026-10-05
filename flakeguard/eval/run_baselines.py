import csv
import json
import os
import sys

# Support running either directly or as package module
sys.path.insert(0, ".")

from flakeguard.eval.baseline_rerun import evaluate_rerun_baseline
from flakeguard.eval.metrics import (
    bootstrap_ci,
    compute_confusion_matrix,
    compute_false_quarantine_rate,
    compute_precision_recall_f1,
    compute_root_cause_accuracy,
)


def load_ground_truth(labels_json_path):
    with open(labels_json_path, "r", encoding="utf-8") as f:
        labels_data = json.load(f)

    ground_truth = {}
    if isinstance(labels_data, list):
        for item in labels_data:
            ground_truth[item["id"]] = {
                "label": item["label"],
                "root_cause": item["root_cause"],
            }
    elif isinstance(labels_data, dict):
        for tid, item in labels_data.items():
            ground_truth[tid] = {
                "label": item["label"],
                "root_cause": item["root_cause"],
            }
    return ground_truth


def run_baselines(
    runs_csv="results/runs.csv",
    labels_json="labels/labels.json",
    output_csv="results/baseline_metrics.csv",
    n_values=(5, 10, 20),
    n_bootstraps=1000,
):
    ground_truth = load_ground_truth(labels_json)

    metrics_rows = []

    print("=" * 90)
    print("FLAKEGUARD BASELINE EVALUATION (Rerun Baseline @ N=5, 10, 20)")
    print("=" * 90)

    for N in n_values:
        predictions = evaluate_rerun_baseline(runs_csv, N)

        dataset = []
        for tid, gt in ground_truth.items():
            pred = predictions.get(
                tid, {"label": "stable", "root_cause": "none"}
            )
            dataset.append(
                {
                    "test_id": tid,
                    "actual_label": gt["label"],
                    "pred_label": pred["label"],
                    "actual_rc": gt["root_cause"],
                    "pred_rc": pred["root_cause"],
                }
            )

        y_true = [d["actual_label"] for d in dataset]
        y_pred = [d["pred_label"] for d in dataset]
        rc_true = [d["actual_rc"] for d in dataset]
        rc_pred = [d["pred_rc"] for d in dataset]

        # Calculate point metrics
        prf = compute_precision_recall_f1(y_true, y_pred, pos_label="flaky")
        rc_acc = compute_root_cause_accuracy(rc_true, rc_pred)
        fq_rate = compute_false_quarantine_rate(
            y_true, y_pred, real_label="real", flaky_label="flaky"
        )
        cm = compute_confusion_matrix(
            y_true, y_pred, labels=["flaky", "real", "stable"]
        )

        # Bootstrap CIs for Precision, Recall, F1
        p_ci = bootstrap_ci(
            lambda sample: compute_precision_recall_f1(
                [s["actual_label"] for s in sample],
                [s["pred_label"] for s in sample],
            )["precision"],
            dataset,
            n_bootstraps=n_bootstraps,
        )

        r_ci = bootstrap_ci(
            lambda sample: compute_precision_recall_f1(
                [s["actual_label"] for s in sample],
                [s["pred_label"] for s in sample],
            )["recall"],
            dataset,
            n_bootstraps=n_bootstraps,
        )

        f1_ci = bootstrap_ci(
            lambda sample: compute_precision_recall_f1(
                [s["actual_label"] for s in sample],
                [s["pred_label"] for s in sample],
            )["f1"],
            dataset,
            n_bootstraps=n_bootstraps,
        )

        row = {
            "baseline": "rerun",
            "N": N,
            "precision": round(prf["precision"], 4),
            "precision_ci_lower": round(p_ci["ci_lower"], 4),
            "precision_ci_upper": round(p_ci["ci_upper"], 4),
            "recall": round(prf["recall"], 4),
            "recall_ci_lower": round(r_ci["ci_lower"], 4),
            "recall_ci_upper": round(r_ci["ci_upper"], 4),
            "f1": round(prf["f1"], 4),
            "f1_ci_lower": round(f1_ci["ci_lower"], 4),
            "f1_ci_upper": round(f1_ci["ci_upper"], 4),
            "root_cause_acc": round(rc_acc, 4),
            "false_quarantine_rate": round(fq_rate, 4),
        }
        metrics_rows.append(row)

        print(f"\n--- RERUN BASELINE @ N={N} ---")
        print(
            f"Precision : {row['precision']:.4f}  (95% CI: [{row['precision_ci_lower']:.4f}, {row['precision_ci_upper']:.4f}])"
        )
        print(
            f"Recall    : {row['recall']:.4f}  (95% CI: [{row['recall_ci_lower']:.4f}, {row['recall_ci_upper']:.4f}])"
        )
        print(
            f"F1 Score  : {row['f1']:.4f}  (95% CI: [{row['f1_ci_lower']:.4f}, {row['f1_ci_upper']:.4f}])"
        )
        print(f"RC Acc    : {row['root_cause_acc']:.4f}")
        print(f"False Quar: {row['false_quarantine_rate']:.4f}")
        print("Confusion Matrix (Actual \\ Pred):")
        print("           flaky  real  stable")
        for lbl in ["flaky", "real", "stable"]:
            print(
                f"  {lbl:<6} : {cm[lbl]['flaky']:<6} {cm[lbl]['real']:<5} {cm[lbl]['stable']:<6}"
            )

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    fieldnames = list(metrics_rows[0].keys())

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metrics_rows)

    print("\n" + "=" * 90)
    print(f"Saved baseline metrics to {output_csv}")
    print("=" * 90)


if __name__ == "__main__":
    run_baselines()
