import ast
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict

import ollama

# Support running directly or as module
sys.path.insert(0, ".")

from flakeguard.eval.metrics import (
    bootstrap_ci,
    compute_false_quarantine_rate,
    compute_precision_recall_f1,
    compute_root_cause_accuracy,
)

RESULTS_DIR = "results"
RUNS_CSV = os.path.join(RESULTS_DIR, "runs.csv")
LABELS_JSON = "labels/labels.json"
LLM_RAW_DIR = os.path.join(RESULTS_DIR, "llm_raw")
LLM_METRICS_CSV = os.path.join(RESULTS_DIR, "llm_metrics.csv")
BASELINE_METRICS_CSV = os.path.join(RESULTS_DIR, "baseline_metrics.csv")

PROMPT_PATHS = {
    "v1": "prompts/v1.txt",
    "v2": "prompts/v2.txt",
    "v3": "prompts/v3.txt",
}

LOG_EXCERPTS = {
    "test_case_01": "(None - test passed)",
    "test_case_02": "AssertionError: assert 'item_alpha' in []",
    "test_case_03": "(None - test passed)",
    "test_case_04": "AssertionError: assert False is True",
    "test_case_05": "(None - test passed)",
    "test_case_06": "AssertionError: assert '' == 'valid_tok_99'",
    "test_case_07": "(None - test passed)",
    "test_case_08": "KeyError: 'rate'",
    "test_case_09": "(None - test passed)",
    "test_case_10": "AssertionError: assert 25.0 == 5.0",
    "test_case_11": "(None - test passed)",
    "test_case_12": "AssertionError: assert 'VIP' == 'STANDARD'",
    "test_case_13": "AssertionError: assert False",
    "test_case_14": "AssertionError: assert 0 >= 1",
    "test_case_15": "AssertionError: assert 78 == 100",
    "test_case_16": "AssertionError: assert 0.9124 < 0.85",
    "test_case_17": "AssertionError: assert 'FAIL' != 'FAIL'",
    "test_case_18": "AssertionError: assert 7343 % 7 != 0",
    "test_case_19": "AssertionError: assert 'Good night' == 'Good day'",
    "test_case_20": "AssertionError: assert False is True",
    "test_case_21": "AssertionError: assert 0 == 5",
    "test_case_22": "AssertionError: assert 10 == 11",
    "test_case_23": "Failed: DID NOT RAISE <class 'ValueError'>",
    "test_case_24": "Failed: DID NOT RAISE <class 'ValueError'>",
    "test_case_25": "AssertionError: assert '$12.3' == '$12.35'",
    "test_case_26": "AssertionError: assert {'a': [2]} == {'a': [1, 2]}",
    "test_case_27": "IndexError: list index out of range",
    "test_case_28": "(None - test passed)",
    "test_case_29": "(None - test passed)",
    "test_case_30": "(None - test passed)",
    "test_case_31": "(None - test passed)",
}


def load_runs_summary(runs_csv_path):
    stats = defaultdict(lambda: {"total": 0, "pass": 0, "fail": 0})
    if not os.path.exists(runs_csv_path):
        return stats
    with open(runs_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = row["test_id"]
            outcome = row["outcome"].upper()
            stats[tid]["total"] += 1
            if outcome == "PASS":
                stats[tid]["pass"] += 1
            elif outcome == "FAIL":
                stats[tid]["fail"] += 1
    return stats


def extract_ast_code():
    test_bodies = {}
    code_under_test = {}

    shop_path = "synthetic/src/shop.py"
    shop_src = ""
    shop_ast = None
    if os.path.exists(shop_path):
        with open(shop_path, "r", encoding="utf-8") as f:
            shop_src = f.read()
            shop_ast = ast.parse(shop_src)

    shop_funcs = {}
    if shop_ast:
        shop_lines = shop_src.splitlines()
        for node in ast.walk(shop_ast):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 5)
                shop_funcs[node.name] = "\n".join(shop_lines[start:end])

    test_dir = "synthetic/tests"
    for fname in sorted(os.listdir(test_dir)):
        if fname.startswith("test_suite_") and fname.endswith(".py"):
            fpath = os.path.join(test_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                src = f.read()
                lines = src.splitlines()
                parsed = ast.parse(src)
                for node in parsed.body:
                    if (
                        isinstance(node, ast.FunctionDef)
                        and node.name.startswith("test_case_")
                    ):
                        start = node.lineno - 1
                        end = getattr(node, "end_lineno", start + 5)
                        func_code = "\n".join(lines[start:end])
                        test_bodies[node.name] = func_code

                        # Find shop.func calls
                        called_code = []
                        for subnode in ast.walk(node):
                            if (
                                isinstance(subnode, ast.Attribute)
                                and isinstance(subnode.value, ast.Name)
                                and subnode.value.id == "shop"
                            ):
                                attr_name = subnode.attr
                                if attr_name in shop_funcs:
                                    called_code.append(
                                        f"# Function: {attr_name}\n"
                                        + shop_funcs[attr_name]
                                    )
                                elif attr_name in shop_src:
                                    called_code.append(
                                        f"# Attribute/Function: {attr_name}"
                                    )
                        if not called_code:
                            code_under_test[node.name] = shop_src[:500]
                        else:
                            code_under_test[node.name] = "\n\n".join(
                                list(set(called_code))
                            )

    return test_bodies, code_under_test


def parse_and_clean_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    data = json.loads(text)

    # Normalize fields
    label = str(data.get("label", "stable")).lower().strip()
    if label not in ["flaky", "real", "stable"]:
        if "flak" in label:
            label = "flaky"
        elif "real" in label:
            label = "real"
        else:
            label = "stable"

    root_cause = str(data.get("root_cause", "none")).lower().strip()
    valid_rcs = [
        "order_dep",
        "shared_state",
        "timing",
        "randomness",
        "time_tz",
        "none",
    ]
    if root_cause not in valid_rcs:
        if "order" in root_cause:
            root_cause = "order_dep"
        elif "shared" in root_cause or "state" in root_cause:
            root_cause = "shared_state"
        elif "time_tz" in root_cause or "tz" in root_cause or "clock" in root_cause:
            root_cause = "time_tz"
        elif "timing" in root_cause or "race" in root_cause:
            root_cause = "timing"
        elif "rand" in root_cause:
            root_cause = "randomness"
        else:
            root_cause = "none"

    confidence = float(data.get("confidence", 0.8))
    reasoning = str(data.get("reasoning", ""))

    return {
        "label": label,
        "root_cause": root_cause,
        "confidence": confidence,
        "reasoning": reasoning,
    }


_OLLAMA_CACHE = {}
CACHE_DIR = ".cache/ollama_eval_cache"


def call_ollama(model_name, prompt, seed=42):
    cache_key = (model_name, prompt)
    if cache_key in _OLLAMA_CACHE:
        return _OLLAMA_CACHE[cache_key]

    os.makedirs(CACHE_DIR, exist_ok=True)
    hash_str = hashlib.sha256(f"{model_name}:{prompt}".encode("utf-8")).hexdigest()
    disk_cache_path = os.path.join(CACHE_DIR, f"{hash_str}.json")

    if os.path.exists(disk_cache_path):
        try:
            with open(disk_cache_path, "r", encoding="utf-8") as f:
                cached_ret = json.load(f)
            ret = (
                cached_ret["parsed"],
                cached_ret["raw_response"],
                cached_ret["failed"],
            )
            _OLLAMA_CACHE[cache_key] = ret
            return ret
        except Exception:
            pass

    res = ollama.generate(
        model=model_name,
        prompt=prompt,
        options={"temperature": 0.0, "seed": seed, "num_predict": 150},
    )
    raw_response = res.response

    try:
        parsed = parse_and_clean_json(raw_response)
        ret = (parsed, raw_response, False)
        _OLLAMA_CACHE[cache_key] = ret
        with open(disk_cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {"parsed": parsed, "raw_response": raw_response, "failed": False},
                f,
                indent=2,
            )
        return ret
    except Exception as err:
        retry_prompt = (
            prompt
            + f"\n\nPrevious attempt failed with error: {str(err)}.\nPlease return strictly valid JSON matching the schema."
        )
        try:
            retry_res = ollama.generate(
                model=model_name,
                prompt=retry_prompt,
                options={"temperature": 0.0, "seed": seed + 1, "num_predict": 150},
            )
            parsed = parse_and_clean_json(retry_res.response)
            ret = (parsed, retry_res.response, False)
            _OLLAMA_CACHE[cache_key] = ret
            with open(disk_cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "parsed": parsed,
                        "raw_response": retry_res.response,
                        "failed": False,
                    },
                    f,
                    indent=2,
                )
            return ret
        except Exception:
            fallback = {
                "label": "stable",
                "root_cause": "none",
                "confidence": 0.0,
                "reasoning": "Failed to parse JSON after retry",
            }
            ret = (fallback, raw_response, True)
            _OLLAMA_CACHE[cache_key] = ret
            with open(disk_cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "parsed": fallback,
                        "raw_response": raw_response,
                        "failed": True,
                    },
                    f,
                    indent=2,
                )
            return ret


def run_llm_prompts(model_name="llama3.2:3b"):
    print("=" * 90, flush=True)
    print(f"STARTING LLM PROMPT EVALUATION USING MODEL: {model_name}", flush=True)
    print("=" * 90, flush=True)

    with open(LABELS_JSON, "r", encoding="utf-8") as f:
        labels_list = json.load(f)

    runs_summary = load_runs_summary(RUNS_CSV)
    test_bodies, code_under_test_map = extract_ast_code()

    prompt_templates = {}
    for ver, path in PROMPT_PATHS.items():
        with open(path, "r", encoding="utf-8") as f:
            prompt_templates[ver] = f.read()

    llm_metrics_rows = []

    for ver in ["v1", "v2", "v3"]:
        raw_out_dir = os.path.join(LLM_RAW_DIR, ver)
        os.makedirs(raw_out_dir, exist_ok=True)
        template = prompt_templates[ver]

        print(f"\n---> Evaluating Prompt Version: {ver} <---", flush=True)

        dataset = []
        parse_failure_count = 0
        case_self_consistency = []

        for item in labels_list:
            tid = item["id"]
            case_name = tid.split("::")[-1]
            gt_label = item["label"]
            gt_rc = item["root_cause"]

            stats_info = runs_summary[tid]
            tot = stats_info["total"]
            pas = stats_info["pass"]
            fal = stats_info["fail"]
            fail_pct = (fal / tot * 100) if tot > 0 else 0.0
            failure_stats_str = (
                f"{tot} total runs, {pas} passes, {fal} fails ({fail_pct:.1f}% failure rate)"
            )

            log_excerpt_str = LOG_EXCERPTS.get(
                case_name, "AssertionError: test failed"
            )
            tbody_str = test_bodies.get(case_name, "# Test body unavailable")
            cut_str = code_under_test_map.get(
                case_name, "# Code under test unavailable"
            )

            prompt = (
                template.replace("{failure_stats}", failure_stats_str)
                .replace("{log_excerpt}", log_excerpt_str)
                .replace("{test_body}", tbody_str)
                .replace("{code_under_test}", cut_str)
            )

            # 3x Self-consistency runs
            run_preds = []
            final_parsed = None
            final_raw = ""

            for run_idx in range(3):
                seed = 42 + run_idx
                parsed, raw_text, failed = call_ollama(
                    model_name, prompt, seed=seed
                )
                if run_idx == 0:
                    final_parsed = parsed
                    final_raw = raw_text
                    if failed:
                        parse_failure_count += 1

                run_preds.append((parsed["label"], parsed["root_cause"]))

            # Save raw response for case (Run 1)
            raw_save_path = os.path.join(raw_out_dir, f"{case_name}.json")
            with open(raw_save_path, "w", encoding="utf-8") as rf:
                json.dump(
                    {
                        "test_id": tid,
                        "case_name": case_name,
                        "model": model_name,
                        "version": ver,
                        "prompt": prompt,
                        "parsed_output": final_parsed,
                        "raw_response": final_raw,
                        "self_consistency_runs": run_preds,
                    },
                    rf,
                    indent=2,
                )

            # Record self consistency: whether all 3 runs agree
            is_consistent = len(set(run_preds)) == 1
            case_self_consistency.append(is_consistent)

            dataset.append(
                {
                    "test_id": tid,
                    "actual_label": gt_label,
                    "pred_label": final_parsed["label"],
                    "actual_rc": gt_rc,
                    "pred_rc": final_parsed["root_cause"],
                }
            )

            print(
                f"  [{case_name}] Actual: ({gt_label}, {gt_rc}) | Pred: ({final_parsed['label']}, {final_parsed['root_cause']})",
                flush=True,
            )

        y_true = [d["actual_label"] for d in dataset]
        y_pred = [d["pred_label"] for d in dataset]
        rc_true = [d["actual_rc"] for d in dataset]
        rc_pred = [d["pred_rc"] for d in dataset]

        prf = compute_precision_recall_f1(y_true, y_pred, pos_label="flaky")
        rc_acc = compute_root_cause_accuracy(rc_true, rc_pred)
        fq_rate = compute_false_quarantine_rate(
            y_true, y_pred, real_label="real", flaky_label="flaky"
        )
        agreement_rate = (
            sum(case_self_consistency) / len(case_self_consistency)
            if case_self_consistency
            else 0.0
        )

        p_ci = bootstrap_ci(
            lambda s: compute_precision_recall_f1(
                [x["actual_label"] for x in s], [x["pred_label"] for x in s]
            )["precision"],
            dataset,
        )

        r_ci = bootstrap_ci(
            lambda s: compute_precision_recall_f1(
                [x["actual_label"] for x in s], [x["pred_label"] for x in s]
            )["recall"],
            dataset,
        )

        f1_ci = bootstrap_ci(
            lambda s: compute_precision_recall_f1(
                [x["actual_label"] for x in s], [x["pred_label"] for x in s]
            )["f1"],
            dataset,
        )

        row = {
            "prompt_version": ver,
            "model": model_name,
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
            "self_consistency_agreement": round(agreement_rate, 4),
            "parse_failures": parse_failure_count,
        }
        llm_metrics_rows.append(row)

    # Write results/llm_metrics.csv
    os.makedirs(os.path.dirname(LLM_METRICS_CSV), exist_ok=True)
    fieldnames = list(llm_metrics_rows[0].keys())
    with open(LLM_METRICS_CSV, "w", newline="", encoding="utf-8") as mf:
        writer = csv.DictWriter(mf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(llm_metrics_rows)

    print(f"\nSaved LLM evaluation metrics to {LLM_METRICS_CSV}")

    # Print Unified Comparison Table
    print_comparison_table(LLM_METRICS_CSV, BASELINE_METRICS_CSV)


def print_comparison_table(llm_metrics_csv, baseline_metrics_csv):
    baseline_rows = []
    if os.path.exists(baseline_metrics_csv):
        with open(baseline_metrics_csv, "r", encoding="utf-8") as bf:
            baseline_rows = list(csv.DictReader(bf))

    llm_rows = []
    if os.path.exists(llm_metrics_csv):
        with open(llm_metrics_csv, "r", encoding="utf-8") as lf:
            llm_rows = list(csv.DictReader(lf))

    print("\n" + "=" * 115)
    print("UNIFIED BENCHMARK COMPARISON: RERUN BASELINES VS LLM PROMPT VERSIONS")
    print("=" * 115)
    header = (
        f"{'Method / Prompt':<25} | {'Precision (95% CI)':<22} | "
        f"{'Recall (95% CI)':<22} | {'F1 (95% CI)':<22} | {'RC Acc':<7} | {'False Quar':<10}"
    )
    print(header)
    print("-" * 115)

    for b in baseline_rows:
        name = f"Rerun (N={b['N']})"
        p_str = f"{float(b['precision']):.4f} [{float(b['precision_ci_lower']):.4f},{float(b['precision_ci_upper']):.4f}]"
        r_str = f"{float(b['recall']):.4f} [{float(b['recall_ci_lower']):.4f},{float(b['recall_ci_upper']):.4f}]"
        f1_str = f"{float(b['f1']):.4f} [{float(b['f1_ci_lower']):.4f},{float(b['f1_ci_upper']):.4f}]"
        rc = f"{float(b['root_cause_acc']):.4f}"
        fq = f"{float(b['false_quarantine_rate']):.4f}"
        print(
            f"{name:<25} | {p_str:<22} | {r_str:<22} | {f1_str:<22} | {rc:<7} | {fq:<10}"
        )

    for lm in llm_rows:
        name = f"LLM {lm['prompt_version'].upper()} ({lm['model']})"
        p_str = f"{float(lm['precision']):.4f} [{float(lm['precision_ci_lower']):.4f},{float(lm['precision_ci_upper']):.4f}]"
        r_str = f"{float(lm['recall']):.4f} [{float(lm['recall_ci_lower']):.4f},{float(lm['recall_ci_upper']):.4f}]"
        f1_str = f"{float(lm['f1']):.4f} [{float(lm['f1_ci_lower']):.4f},{float(lm['f1_ci_upper']):.4f}]"
        rc = f"{float(lm['root_cause_acc']):.4f}"
        fq = f"{float(lm['false_quarantine_rate']):.4f}"
        print(
            f"{name:<25} | {p_str:<22} | {r_str:<22} | {f1_str:<22} | {rc:<7} | {fq:<10}"
        )

    print("=" * 115)


if __name__ == "__main__":
    run_llm_prompts()
