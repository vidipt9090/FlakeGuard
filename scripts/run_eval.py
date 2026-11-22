"""Evaluation runner (M8). Every number it writes comes from a command it ran.

    python scripts/run_eval.py planted                 # runs B1, perturbation, RQ1 table, RQ2
    python scripts/run_eval.py planted --steps rq2     # recompute RQ2 from the recorded perturbation runs

Writes ``results/<label>/*.json``. Each file carries ``provenance``: dataset, label type, N, the exact command,
date, commit. A label type is never mixed with another one: one label, one folder, one set of files.

Methods (docs/EVAL.md):
  B1            N repeats of the whole suite in the suite's own fixed order.
  perturbation  N whole-suite runs in shuffled orders (pytest-randomly, seeds 1 to N).
Both are compared at the same numbers of full-suite runs (N = 5, 10, 20) and the wall-clock minutes of those
runs are measured here, on this machine, and compared with a 6-minute budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from flakeguard.eval.metrics import bootstrap_ci, compute_precision_recall_f1  # noqa: E402
from flakeguard.stats.adaptive import AdaptiveStoppingPolicy  # noqa: E402

BUDGET_MINUTES = 6.0
N_VALUES = (5, 10, 20)
MAX_RUNS = max(N_VALUES)
DATASETS = {
    "planted": {
        "suite": "synthetic/tests",
        "id_prefix": "synthetic",
        "labels": "labels/labels.json",
        "how_labelled": "by construction: each fault was written into the test or the code by hand, so its label is known",
    },
}
LIMITATIONS = {
    "planted": [
        "Planted faults only. Results on planted faults are partly circular: the faults were written to be the "
        "kinds that shuffled runs and the AST analysis are built to find. Read them as a check that the methods "
        "work, not as a measure of how often they find real-world flakes.",
        "No natural flakes (flakes found in real projects) were available. Natural results are not reported "
        "and stay dashes.",
        "Five of the 15 tests labelled flaky fail in every run on this machine: test_case_19, 20 and 21 (root cause "
        "time_tz: the clock is frozen at fixed instants inside the test, so the real time of day does not matter and "
        "they never pass) and test_case_14 and 15 (root cause timing: the test waits 0.02 s for work that takes 0.04 s). "
        "A method that only sees runs cannot tell them from real failures. They are counted as flaky because that is "
        "their label, and reported separately as flaky_label_but_fails_every_run.",
        "Small N: 15 flaky and 16 other tests. Intervals are wide and a difference between methods of a few tests "
        "is not evidence of a difference.",
    ],
}


# ------------------------------------------------------------------------------------- provenance


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def provenance(label: str, labels: list[dict], command: str) -> dict:
    import pytest

    now = datetime.now().astimezone()
    counts: dict[str, int] = {}
    for item in labels:
        counts[item["label"]] = counts.get(item["label"], 0) + 1
    ds = DATASETS[label]
    return {
        "label_type": label,
        "dataset": {
            "suite": ds["suite"],
            "labels_file": ds["labels"],
            "labels_sha256": hashlib.sha256((REPO / ds["labels"]).read_bytes()).hexdigest(),
            "how_labelled": ds["how_labelled"],
            "n_tests": len(labels),
            "n_by_label": counts,
        },
        "command": command,
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "clock": {"local": now.strftime("%Y-%m-%d %H:%M:%S %Z%z"), "weekday": now.strftime("%A")},
        "commit": _git("rev-parse", "HEAD"),
        "tracked_files_modified": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "environment": {"python": platform.python_version(), "pytest": pytest.__version__, "platform": platform.platform()},
        "budget_minutes": BUDGET_MINUTES,
        "limitations": LIMITATIONS[label],
    }


# ------------------------------------------------------------------------------------- running


def run_suite(label: str, *, seed: int | None) -> dict:
    """One whole-suite run. ``seed`` None means the suite's own fixed order; otherwise shuffled with that seed."""
    ds = DATASETS[label]
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        order_flags = ["-p", "no:randomly"] if seed is None else ["-p", "randomly", f"--randomly-seed={seed}"]
        cmd = [sys.executable, "-m", "pytest", ds["suite"], "-q", "-p", "no:cacheprovider", *order_flags,
               "-o", "junit_family=xunit1", f"--junitxml={xml}"]
        start = time.perf_counter()
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        seconds = time.perf_counter() - start
        if proc.returncode not in (0, 1):  # 0 all passed, 1 some failed; anything else means pytest itself broke
            raise RuntimeError(f"pytest exited {proc.returncode} for seed={seed}:\n{proc.stdout[-1500:]}\n{proc.stderr[-800:]}")
        outcomes: dict[str, str] = {}
        order: list[str] = []
        for case in ET.parse(xml).getroot().iter("testcase"):
            tid = f"{ds['id_prefix']}/{case.get('file', '').replace(chr(92), '/')}::{case.get('name')}"
            if case.find("skipped") is not None:
                continue
            outcomes[tid] = "FAIL" if (case.find("failure") is not None or case.find("error") is not None) else "PASS"
            order.append(tid)
    return {"seed": seed, "seconds": round(seconds, 3), "started": datetime.now().astimezone().isoformat(timespec="seconds"),
            "order": order, "outcomes": outcomes}


def run_series(label: str, shuffled: bool, n: int) -> list[dict]:
    return [run_suite(label, seed=(i if shuffled else None)) for i in range(1, n + 1)]


# ------------------------------------------------------------------------------------- statistics


def wilson(k: int, n: int, z: float = 1.96) -> list[float | None]:
    """95% Wilson score interval for k of n. [None, None] when n is 0."""
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None, "ci95_wilson": wilson(k, n)}


def classify(outcomes: list[str]) -> str:
    """What the runs show. Three words only; none of them is 'stable' or 'fixed'."""
    has_fail, has_pass = "FAIL" in outcomes, "PASS" in outcomes
    if has_fail and has_pass:
        return "flaky"
    if has_fail:
        return "real"
    return "none_seen"


def score(labels: list[dict], predictions: dict[str, str]) -> dict:
    y_true = [x["label"] for x in labels]
    y_pred = [predictions[x["id"]] for x in labels]
    tp = sum(t == "flaky" and p == "flaky" for t, p in zip(y_true, y_pred))
    flagged = sum(p == "flaky" for p in y_pred)
    actual = sum(t == "flaky" for t in y_true)
    pairs = list(zip(y_true, y_pred))
    f1 = bootstrap_ci(lambda s: compute_precision_recall_f1([a for a, _ in s], [b for _, b in s], pos_label="flaky")["f1"],
                      pairs, n_bootstraps=2000, seed=42)
    confusion = {a: {p: sum(1 for t, q in pairs if t == a and q == p) for p in ("flaky", "real", "none_seen")}
                 for a in ("flaky", "real", "stable")}
    by_cause = {}
    for cause in sorted({x["root_cause"] for x in labels if x["label"] == "flaky"}):
        ids = [x["id"] for x in labels if x["label"] == "flaky" and x["root_cause"] == cause]
        by_cause[cause] = {"found_flaky": sum(predictions[i] == "flaky" for i in ids), "n": len(ids)}
    return {
        "n_tests": len(labels),
        "flaky_found": {"k": tp, "n": actual},
        "wrongly_flagged_flaky": {"k": flagged - tp, "n": len(labels) - actual},
        "precision": rate(tp, flagged),
        "recall": rate(tp, actual),
        "f1": {"value": round(compute_precision_recall_f1(y_true, y_pred, pos_label="flaky")["f1"], 4),
               "ci95_bootstrap": [round(f1["ci_lower"], 4), round(f1["ci_upper"], 4)], "resamples": 2000,
               "n": len(labels)},
        "real_failures_called_flaky": rate(confusion["real"]["flaky"], sum(confusion["real"].values())),
        "flaky_called_real": rate(confusion["flaky"]["real"], sum(confusion["flaky"].values())),
        "confusion_actual_by_predicted": confusion,
        "by_root_cause": by_cause,
    }


def rq1(label: str, labels: list[dict], series: dict[str, list[dict]]) -> dict:
    rows = []
    for method, runs in series.items():
        for n in N_VALUES:
            first = runs[:n]
            preds = {x["id"]: classify([r["outcomes"][x["id"]] for r in first if x["id"] in r["outcomes"]]) for x in labels}
            no_time_tz = [x for x in labels if x["root_cause"] != "time_tz"]
            minutes = sum(r["seconds"] for r in first) / 60
            rows.append({
                "method": method, "full_suite_runs": n,
                "minutes_measured": round(minutes, 3), "within_budget": minutes <= BUDGET_MINUTES,
                "all_tests": score(labels, preds),
                "without_time_tz_tests": score(no_time_tz, preds),
                "per_test": {x["id"]: {"label": x["label"], "root_cause": x["root_cause"], "called": preds[x["id"]],
                                       "failed_in": sum(r["outcomes"].get(x["id"]) == "FAIL" for r in first), "of": len(first)}
                             for x in labels},
            })
    final = {k: {r["method"]: r for r in rows if r["full_suite_runs"] == MAX_RUNS}[k] for k in series}
    always_fail = [x["id"] for x in labels if x["label"] == "flaky" and all(
        final[m]["per_test"][x["id"]]["failed_in"] == final[m]["per_test"][x["id"]]["of"] for m in final)]
    return {
        "flaky_label_but_fails_every_run": {"k": len(always_fail), "n": sum(x["label"] == "flaky" for x in labels),
                                            "ids": always_fail, "meaning": "failed in all 20 runs of every method"},
        "rows": rows,
    }


# ------------------------------------------------------------------------------------- RQ2


def fixed_decision(seq: list[str], n: int) -> str:
    return classify(seq[:n])


def adaptive_decision(test_id: str, seq: list[str]) -> dict:
    policy = AdaptiveStoppingPolicy(max_runs=MAX_RUNS)
    fails = 0
    decision = None
    for i, outcome in enumerate(seq[:MAX_RUNS], start=1):
        fails += outcome == "FAIL"
        decision = policy.evaluate(test_id, i, fails)
        if decision.should_stop:
            break
    assert decision is not None
    verdict = decision.verdict
    kind = ("flaky" if verdict == "flaky" else "real" if verdict == "deterministic_failure"
            else "none_seen" if verdict.startswith("no evidence") else "undecided")
    return {"runs_used": decision.runs_used, "failures": decision.failures_observed, "decision": kind,
            "policy_verdict": verdict, "reason": decision.reason}


def _summary(values: list[int]) -> dict:
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    ci = bootstrap_ci(lambda s: sum(s) / len(s), values, n_bootstraps=2000, seed=42)
    return {"n_tests": len(values), "mean": round(sum(values) / len(values), 3), "median": median,
            "mean_ci95_bootstrap": [round(ci["ci_lower"], 3), round(ci["ci_upper"], 3)], "total_test_runs": sum(values)}


def rq2(labels: list[dict], perturbation_runs: list[dict]) -> dict:
    """Runs to a decision per test: adaptive stopping against fixed N, on the recorded perturbation outcomes."""
    ids = [x["id"] for x in labels]
    seqs = {i: [r["outcomes"][i] for r in perturbation_runs if i in r["outcomes"]] for i in ids}
    adaptive = {i: adaptive_decision(i, seqs[i]) for i in ids}
    fixed20 = {i: fixed_decision(seqs[i], MAX_RUNS) for i in ids}
    per_test = {}
    for x in labels:
        i = x["id"]
        per_test[i] = {"label": x["label"], "root_cause": x["root_cause"], "failures_in_20": sum(o == "FAIL" for o in seqs[i][:MAX_RUNS]),
                       "fixed_20": fixed20[i], "adaptive": adaptive[i]}
    differs = [i for i in ids if adaptive[i]["decision"] != fixed20[i]]
    return {
        "source": "outcomes of the perturbation runs recorded in perturbation.json (seeds 1 to 20), fed one run at a time to "
                  "flakeguard.stats.adaptive.AdaptiveStoppingPolicy(min_runs=3, max_runs=20, confidence=0.95, threshold_p=0.15)",
        "runs_to_decision_adaptive": _summary([adaptive[i]["runs_used"] for i in ids]),
        "runs_to_decision_fixed": {f"N={n}": _summary([n] * len(ids)) for n in N_VALUES},
        "suite_runs_until_every_test_decided_adaptive": max(adaptive[i]["runs_used"] for i in ids),
        "decisions_adaptive": {k: sum(v["decision"] == k for v in adaptive.values()) for k in ("flaky", "real", "none_seen", "undecided")},
        "decisions_fixed_20": {k: sum(v == k for v in fixed20.values()) for k in ("flaky", "real", "none_seen")},
        "tests_where_adaptive_differs_from_fixed_20": {"k": len(differs), "n": len(ids), "ids": differs},
        "flaky_tests_adaptive_misses": [i for i in ids if fixed20[i] == "flaky" and adaptive[i]["decision"] != "flaky"],
        "note": "The adaptive count is per test. One whole-suite run executes every test, so the suite stops only after the "
                "last test is decided (suite_runs_until_every_test_decided_adaptive); the per-test saving is not a wall-clock saving "
                "unless that number is below 20.",
        "per_test": per_test,
    }


# ------------------------------------------------------------------------------------- main


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", choices=sorted(DATASETS))
    ap.add_argument("--steps", default="runs,rq1,rq2", help="comma list of: runs (execute B1 and perturbation), rq1, rq2")
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)
    steps = set(args.steps.split(","))
    out = REPO / args.out / args.label
    labels = json.loads((REPO / DATASETS[args.label]["labels"]).read_text(encoding="utf-8"))
    command = "python " + " ".join(["scripts/run_eval.py", *(argv if argv is not None else sys.argv[1:])])
    prov = provenance(args.label, labels, command)

    if "runs" in steps:
        for name, shuffled in (("b1_fixed_order", False), ("perturbation", True)):
            runs = run_series(args.label, shuffled, MAX_RUNS)
            write(out / f"{name}.json", {"provenance": prov, "method": name, "runs": runs})
    series = {name: json.loads((out / f"{name}.json").read_text(encoding="utf-8"))["runs"]
              for name in ("b1_fixed_order", "perturbation")}
    if "rq1" in steps:
        write(out / "rq1.json", {"provenance": prov, **rq1(args.label, labels, series)})
    if "rq2" in steps:
        write(out / "rq2.json", {"provenance": prov, **rq2(labels, series["perturbation"])})
    return 0


if __name__ == "__main__":
    sys.exit(main())
