import csv
import json
import os
import sys

sys.path.insert(0, ".")

RESULTS_DIR = "results"
LABELS_JSON = "labels/labels.json"
LLM_RAW_DIR = os.path.join(RESULTS_DIR, "llm_raw")
FAILURE_LOG_CSV = os.path.join(RESULTS_DIR, "failure_log.csv")


def generate_failure_log():
    if not os.path.exists(LABELS_JSON):
        print(f"Error: {LABELS_JSON} not found.")
        sys.exit(1)

    with open(LABELS_JSON, "r", encoding="utf-8") as f:
        labels_list = json.load(f)

    gt_map = {
        item["id"]: {
            "actual_label": item["label"],
            "actual_root_cause": item["root_cause"],
        }
        for item in labels_list
    }

    failure_rows = []
    version_counts = {"v1": 0, "v2": 0, "v3": 0}

    for ver in ["v1", "v2", "v3"]:
        raw_ver_dir = os.path.join(LLM_RAW_DIR, ver)
        if not os.path.exists(raw_ver_dir):
            continue

        for fname in sorted(os.listdir(raw_ver_dir)):
            if fname.endswith(".json"):
                fpath = os.path.join(raw_ver_dir, fname)
                with open(fpath, "r", encoding="utf-8") as rf:
                    case_data = json.load(rf)

                tid = case_data.get("test_id", "")
                gt = gt_map.get(
                    tid, {"actual_label": "unknown", "actual_root_cause": "unknown"}
                )

                parsed = case_data.get("parsed_output", {})
                pred_label = parsed.get("label", "")
                pred_rc = parsed.get("root_cause", "")
                reasoning = parsed.get("reasoning", "")

                actual_label = gt["actual_label"]
                actual_rc = gt["actual_root_cause"]

                # Check if wrong prediction
                label_wrong = pred_label != actual_label
                rc_wrong = pred_rc != actual_rc

                if label_wrong or rc_wrong:
                    version_counts[ver] += 1
                    failure_rows.append(
                        {
                            "prompt_version": ver,
                            "case_id": tid,
                            "actual_label": actual_label,
                            "pred_label": pred_label,
                            "actual_root_cause": actual_rc,
                            "pred_root_cause": pred_rc,
                            "reasoning": reasoning,
                            "human_tag": "",  # Placeholder for human review tag: leakage|missing_evidence|small_model_error|ambiguous_label|parse_failure
                        }
                    )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    fieldnames = [
        "prompt_version",
        "case_id",
        "actual_label",
        "pred_label",
        "actual_root_cause",
        "pred_root_cause",
        "reasoning",
        "human_tag",
    ]

    with open(FAILURE_LOG_CSV, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(failure_rows)

    print("=" * 80)
    print("FAILURE LOG GENERATION COMPLETE")
    print("=" * 80)
    print(f"Total incorrect predictions logged: {len(failure_rows)}")
    for ver, count in version_counts.items():
        print(f"  - Version {ver}: {count} failures")
    print(f"Saved failure log to {FAILURE_LOG_CSV}")
    print("=" * 80)


if __name__ == "__main__":
    generate_failure_log()
