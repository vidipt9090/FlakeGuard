"""Evaluation runner (M8). Every number it writes comes from a command it ran.

    python scripts/run_eval.py planted                 # B1, perturbation, RQ1 table, RQ2
    python scripts/run_eval.py planted --steps rq2     # recompute RQ2 from the recorded perturbation runs
    python scripts/run_eval.py injected                # builds the injected dataset, then B1, perturbation, B2, B3, RQ1, RQ2

Writes ``results/<label>/*.json``. Each file carries ``provenance``: dataset, label type, N, the exact command,
date, commit. A label type is never mixed with another one: one label, one folder, one set of files.

Methods (docs/EVAL.md):
  B1            N repeats of the whole suite in the suite's own fixed order.
  perturbation  N whole-suite runs in shuffled orders (pytest-randomly, seeds 1 to N).
  B2            DeFlaker-style coverage diff: a test that failed and covers none of the changed lines is flaky.
  B3            random forest on run features and code features, trained on the planted set, scored on the injected set.
B1, perturbation and B2 are compared at the same numbers of full-suite runs (N = 5, 10, 20), and the wall-clock minutes
of those runs are measured here, on this machine, and compared with a 6-minute budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from flakeguard.baselines.b2_coverage import B2CoverageClassifier  # noqa: E402
from flakeguard.baselines.b3_feature_classifier import (  # noqa: E402
    B3FeatureClassifier,
    extract_features_from_runs,
)
from flakeguard.eval.metrics import bootstrap_ci, compute_precision_recall_f1  # noqa: E402
from flakeguard.stats.adaptive import AdaptiveStoppingPolicy  # noqa: E402

BUDGET_MINUTES = 6.0
N_VALUES = (5, 10, 20)
MAX_RUNS = max(N_VALUES)
B2_DIFFS = 10  # one-line diffs sampled for B2
B2_SEED = 20261122
DAYTIME = (8, 18)  # local hours in which the injected time_tz faults cannot fail
CACHE = ".eval_cache"
DATASETS = {
    "planted": {
        "root": ".", "suite": "synthetic/tests", "id_prefix": "synthetic/", "labels": "labels/labels.json",
        "how_labelled": "by construction: each fault was written into the test or the code by hand, so its label is known",
    },
    "injected": {
        "root": f"{CACHE}/injected", "suite": "tests", "id_prefix": "", "labels": f"{CACHE}/injected/labels.json",
        "how_labelled": "by construction: operators in flakeguard/injector insert each fault into a passing published test "
                        "suite (cachetools); untouched tests are stable by observation (pristine suite passed in every pristine run)",
    },
}
DEFAULT_STEPS = {"planted": "runs,rq1,rq2", "injected": "runs,coverage,rq1,rq2"}
LIMITATIONS = {
    "planted": [
        "Planted faults only. Results on planted faults are partly circular: the faults were written to be the "
        "kinds that shuffled runs and the AST analysis are built to find. Read them as a check that the methods "
        "work, not as a measure of how often they find real-world flakes.",
        "No natural flakes (flakes found in real projects) were available. Natural results are not reported "
        "and stay dashes.",
        "Five of the 15 tests labelled flaky cannot pass on this machine, judging by their code (see "
        "sensitivity below). The primary table keeps the labels as written; the sensitivity table relabels "
        "those five as real, with the reason read from the test code. The five were first noticed because every method "
        "called them real, then confirmed by reading the code; no test is dropped because a method called it real.",
        "Small N: 15 flaky and 16 other tests. Intervals are wide and a difference between methods of a few tests "
        "is not evidence of a difference.",
        "B2 and B3 are not scored on this set: it has no commit diff or coverage run for B2, and B3 is trained on it, "
        "so scoring B3 here would score it on its training tests.",
    ],
    "injected": [
        "No natural flakes (flakes found in real projects) were available. Natural results are not reported and stay dashes.",
        "The injection operators produce the same fault classes the detector looks for (order, shared state, timing, randomness, "
        "clock), so injected results are only partly independent of the methods being evaluated.",
        "B1 (fixed order) cannot see a fault that only an unusual order triggers, and the order-dependence pairs are built so that "
        "the setup test comes first in the default order (as a real order dependence usually does, or it would be found at once).",
        "The time_tz faults fail only when the local hour is outside 8 to 17. Runs were made in the daytime, so those faults cannot "
        "fail in these runs by construction. The sensitivity table removes them; the primary table keeps them as flaky.",
        "Tests no operator touched are labelled stable because the untouched suite passed in every one of its recorded runs. That is "
        "evidence, not proof; a rare flake in the library's own tests would be counted as a wrong flag.",
        "26 flaky and 5 real tests among 476: small N for the flaky class. Intervals are wide.",
        "B3's code features (the words sleep, random, datetime in the test source) read the text the operators insert, so B3 with them "
        "is partly circular; the run-features-only variant is reported next to it.",
    ],
}
SENSITIVITY = {
    "planted": {
        "synthetic/tests/test_suite_02.py::test_case_14": "asserts after sleeping 0.02 s that a worker which sleeps 0.04 s before it increments has run, so it fails unless the main thread oversleeps by 20 ms",
        "synthetic/tests/test_suite_02.py::test_case_15": "asserts after 0.02 s that two threads, each doing 50 steps of sleep(0.0001), have both finished (COUNTER == 100); on this machine's sleep resolution 50 steps take longer than 0.02 s, so it cannot pass (on a faster timer it would be an intermittent lost-update race)",
        "synthetic/tests/test_suite_02.py::test_case_19": "freeze_time sets 23:30 inside the test and it asserts the greeting is 'Good day', but shop.greeting returns 'Good night' for hour >= 22, so it fails whatever the real clock says",
        "synthetic/tests/test_suite_02.py::test_case_20": "freeze_time sets 2026-10-04 02:00, a Sunday before 08:00, and it asserts is_business_hours is True, but the function returns False for weekends and hours outside 8 to 17, so it fails whatever the real clock says",
        "synthetic/tests/test_suite_03.py::test_case_21": "freeze_time sets 12:00 and it asserts check_timezone_offset(now) == 5, but that function is (now.hour - utcnow().hour) % 24 and both come from the same frozen instant, so it is always 0",
    },
}
B1_TOLERANCE = "B1 found-flaky counts vary by about 1 test between executions (unseeded randomness tests)."


# ------------------------------------------------------------------------------------- provenance


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(label: str, labels: list[dict], command: str) -> dict:
    import pytest

    now = datetime.now().astimezone()
    counts: dict[str, int] = {}
    for item in labels:
        counts[item["label"]] = counts.get(item["label"], 0) + 1
    ds = DATASETS[label]
    dataset = {
        "suite": ds["suite"], "labels_file": ds["labels"], "labels_sha256": _sha256(REPO / ds["labels"]),
        "how_labelled": ds["how_labelled"], "n_tests": len(labels), "n_by_label": counts,
    }
    if label == "injected":
        manifest = json.loads((REPO / ds["root"] / "manifest.json").read_text(encoding="utf-8"))
        dataset.update({
            "base": f"{manifest['package']} {manifest['version']} (source archive sha256 {manifest['sdist_sha256']})",
            "seed": manifest["seed"], "manifest_sha256": _sha256(REPO / ds["root"] / "manifest.json"),
            "injections_by_category": {c: sum(1 for i in manifest["injections"] if i["category"] == c)
                                       for c in sorted({i["category"] for i in manifest["injections"]})},
            "pristine_runs": [r["summary"] for r in manifest["pristine_runs"]],
            "excluded_from_injection": manifest["excluded_from_injection"],
        })
    return {
        "label_type": label,
        "dataset": dataset,
        "command": command,
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "clock": {"local": now.strftime("%Y-%m-%d %H:%M:%S %Z%z"), "weekday": now.strftime("%A")},
        "commit": _git("rev-parse", "HEAD"),
        "tracked_files_modified": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "environment": {"python": platform.python_version(), "pytest": pytest.__version__, "platform": platform.platform()},
        "budget_minutes": BUDGET_MINUTES,
        "tolerances": {"b1_fixed_order": B1_TOLERANCE,
                       "perturbation": "exact on the same commit and environment: seeds fix the order and reseed random (timing faults can differ)",
                       "minutes": "about 0.1 minute between executions on the planted suite; the injected suite takes longer per run",
                       **({"time_tz": "depends on the local hour at which the runs are made; valid for runs between 08:00 and 18:00"} if label == "injected" else {})},
        "natural_flakes": "none available: shown as a dash on the Results screen",
        "limitations": LIMITATIONS[label],
    }


# ------------------------------------------------------------------------------------- dataset


def prepare(label: str, rebuild: bool = False) -> list[dict]:
    """The labelled tests of ``label``. The injected set is built on first use (needs the pinned cachetools archive)."""
    ds = DATASETS[label]
    labels_path = REPO / ds["labels"]
    if label == "injected" and (rebuild or not labels_path.is_file()):
        from flakeguard.injector import dataset

        manifest = dataset.build(REPO / CACHE / "dl", REPO / ds["root"])
        print(f"built injected dataset: {manifest['n_tests']} tests, {manifest['counts']}")
    return json.loads(labels_path.read_text(encoding="utf-8"))


def _suite_root_and_env(label: str) -> tuple[Path, dict, list[str]]:
    ds = DATASETS[label]
    root = (REPO / ds["root"]).resolve()
    if label == "planted":
        return root, dict(os.environ), []
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    return root, env, ["--rootdir", str(root), "-c", str(root / "pyproject.toml")]


def _case_id(label: str, case: ET.Element) -> str:
    file = case.get("file", "").replace("\\", "/")
    module = file[:-3].replace("/", ".")
    classname = case.get("classname", "")
    cls = classname[len(module) + 1:] if classname.startswith(module + ".") else None
    name = case.get("name", "")
    return f"{DATASETS[label]['id_prefix']}{file}" + (f"::{cls}" if cls else "") + f"::{name}"


def run_suite(label: str, *, seed: int | None, coverage_rc: Path | None = None) -> dict:
    """One whole-suite run. ``seed`` None means the suite's own fixed order; otherwise shuffled with that seed."""
    ds = DATASETS[label]
    root, env, rootargs = _suite_root_and_env(label)
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        order_flags = ["-p", "no:randomly"] if seed is None else ["-p", "randomly", f"--randomly-seed={seed}"]
        runner = [sys.executable, "-m", "coverage", "run", "--rcfile", str(coverage_rc), "-m", "pytest"] if coverage_rc \
            else [sys.executable, "-m", "pytest"]
        cmd = [*runner, ds["suite"], "-q", "-p", "no:cacheprovider", *order_flags, *rootargs,
               "-o", "junit_family=xunit1", f"--junitxml={xml}"]
        start = time.perf_counter()
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
        seconds = time.perf_counter() - start
        if proc.returncode not in (0, 1):  # 0 all passed, 1 some failed; anything else means pytest itself broke
            raise RuntimeError(f"pytest exited {proc.returncode} for seed={seed}:\n{proc.stdout[-1500:]}\n{proc.stderr[-800:]}")
        outcomes: dict[str, str] = {}
        durations: dict[str, float] = {}
        order: list[str] = []
        for case in ET.parse(xml).getroot().iter("testcase"):
            if case.find("skipped") is not None:
                continue
            tid = _case_id(label, case)
            failed = case.find("failure") is not None or case.find("error") is not None
            if tid not in outcomes:
                order.append(tid)
            outcomes[tid] = "FAIL" if (failed or outcomes.get(tid) == "FAIL") else "PASS"  # a failing sub-case fails the test
            durations[tid] = round(durations.get(tid, 0.0) + float(case.get("time", 0) or 0), 4)
    return {"seed": seed, "seconds": round(seconds, 3), "started": datetime.now().astimezone().isoformat(timespec="seconds"),
            "order": order, "outcomes": outcomes, "durations": durations}


def run_series(label: str, shuffled: bool, n: int, labels: list[dict]) -> list[dict]:
    runs = [run_suite(label, seed=(i if shuffled else None)) for i in range(1, n + 1)]
    expected = {x["id"] for x in labels}
    for run in runs:
        got = set(run["outcomes"])
        if got != expected:
            raise RuntimeError(f"the run's test ids do not match the labels: only in run {sorted(got - expected)[:3]}, "
                               f"only in labels {sorted(expected - got)[:3]}")
    return runs


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
        "wrongly_flagged_ids": [x["id"] for x in labels if x["label"] != "flaky" and predictions[x["id"]] == "flaky"],
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


# ------------------------------------------------------------------------------------- RQ1


def sensitivity(label: str, labels: list[dict], series: dict[str, list[dict]]) -> tuple[list[dict], dict] | None:
    """The second scoring scope: labels changed or tests set aside for reasons read from the code, not from scores."""
    if label == "planted":
        reasons = SENSITIVITY["planted"]
        return ([{**x, "label": "real", "root_cause": "none"} if x["id"] in reasons else x for x in labels],
                {"kind": "five tests relabelled real", "reasons_from_reading_the_code": reasons})
    hours = {datetime.fromisoformat(r["started"]).hour for runs in series.values() for r in runs}
    if not all(DAYTIME[0] <= h < DAYTIME[1] for h in hours):
        return None
    ids = [x["id"] for x in labels if x["root_cause"] == "time_tz"]
    return ([x for x in labels if x["root_cause"] != "time_tz"],
            {"kind": "time_tz faults set aside", "n_set_aside": len(ids), "ids": ids,
             "reason": f"each asserts 8 <= local hour < 18; every run started at local hour(s) {sorted(hours)}, "
                       "so by the code none of them can fail in these runs"})


def _method_row(method: str, n: int, minutes: float, preds: dict[str, str], labels: list[dict], scope2, extra: dict | None = None) -> dict:
    row = {
        "method": method, "full_suite_runs": n, "minutes_measured": round(minutes, 3), "within_budget": minutes <= BUDGET_MINUTES,
        "all_tests": score(labels, preds),
    }
    if scope2 is not None:
        row["sensitivity"] = score(scope2[0], preds)
    row["per_test"] = {x["id"]: {"label": x["label"], "root_cause": x["root_cause"], "called": preds[x["id"]]}
                       for x in labels if x["label"] != "stable"}
    if method == "b1_fixed_order":
        row["tolerance"] = B1_TOLERANCE
    row.update(extra or {})
    return row


def _failures_in(runs: list[dict], tid: str) -> tuple[int, int]:
    got = [r["outcomes"][tid] for r in runs if tid in r["outcomes"]]
    return sum(o == "FAIL" for o in got), len(got)


def rq1(label: str, labels: list[dict], series: dict[str, list[dict]], out: Path, planted_runs: list[dict] | None) -> dict:
    scope2 = sensitivity(label, labels, series)
    rows: list[dict] = []
    for method, runs in series.items():
        for n in N_VALUES:
            first = runs[:n]
            preds = {x["id"]: classify([r["outcomes"][x["id"]] for r in first if x["id"] in r["outcomes"]]) for x in labels}
            row = _method_row(method, n, sum(r["seconds"] for r in first) / 60, preds, labels, scope2)
            row["per_test_failed_in"] = {x["id"]: dict(zip(("failed", "of"), _failures_in(first, x["id"])))
                                         for x in labels if x["label"] != "stable"}
            rows.append(row)

    not_run: dict[str, str] = {}
    if label == "injected":
        rows += b2_rows(labels, series["b1_fixed_order"], out, scope2)
        if planted_runs is None:
            not_run["b3"] = "needs results/planted/b1_fixed_order.json (the training set); run planted first"
        else:
            rows += b3_rows(labels, series["b1_fixed_order"], planted_runs, scope2)
    else:
        not_run["b2_coverage_diff"] = "the planted suite has no commit diff and no coverage run"
        not_run["b3"] = "B3 is trained on the planted set; scoring it here would score it on its training tests"

    final = {r["method"]: r for r in rows if r["full_suite_runs"] == MAX_RUNS}
    flaky_ids = [x["id"] for x in labels if x["label"] == "flaky"]
    always_fail = [i for i in flaky_ids if all(
        _failures_in(series[m], i)[0] == _failures_in(series[m], i)[1] for m in series if m in final)]
    return {
        "flaky_label_but_fails_every_run": {"k": len(always_fail), "n": len(flaky_ids), "ids": always_fail,
                                            "meaning": f"failed in all {MAX_RUNS} runs of every run-based method"},
        "methods_not_run": not_run,
        "sensitivity": None if scope2 is None else {
            "meaning": "Same predictions scored on a changed set; the primary scope (all_tests) keeps the labels as written.", **scope2[1]},
        "rows": rows,
    }


# ------------------------------------------------------------------------------------- B2


def coverage_step(label: str, out: Path) -> None:
    """One fixed-order run under coverage, with one context per test, to know which source lines each test executes."""
    import coverage

    root, _, _ = _suite_root_and_env(label)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "cov.data"
        rc = Path(tmp) / "rc"
        rc.write_text(f"[run]\nsource = {root / 'src' / 'cachetools'}\ndynamic_context = test_function\ndata_file = {data}\n", encoding="utf-8")
        run = run_suite(label, seed=None, coverage_rc=rc)
        cov = coverage.CoverageData(basename=str(data))
        cov.read()
        lines_by_context: dict[str, dict[str, list[int]]] = {}
        for filename in sorted(cov.measured_files()):
            rel = Path(filename).resolve().relative_to(root).as_posix()
            for lineno, contexts in cov.contexts_by_lineno(filename).items():
                for ctx in contexts:
                    if ctx:
                        lines_by_context.setdefault(ctx, {}).setdefault(rel, []).append(lineno)
    payload = {"note": "one fixed-order run under coverage (coverage.py dynamic_context=test_function), library source only",
               "seconds": run["seconds"], "outcomes_in_this_run": run["outcomes"], "coverage_version": coverage.__version__,
               "lines_by_context": {c: {f: sorted(set(v)) for f, v in files.items()} for c, files in sorted(lines_by_context.items())}}
    write(out / "coverage.json", payload)


def _context_to_id(context: str, ids: set[str]) -> str | None:
    """coverage names a context ``tests.test_fifo.FIFOCacheTest.test_fifo``; ids are ``tests/test_fifo.py::FIFOCacheTest::test_fifo``."""
    parts = context.split(".")
    for cut in range(1, len(parts)):
        module, rest = ".".join(parts[:cut]), parts[cut:]
        tid = module.replace(".", "/") + ".py::" + "::".join(rest)
        if tid in ids:
            return tid
    return None


def b2_rows(labels: list[dict], fixed_runs: list[dict], out: Path, scope2) -> list[dict]:
    cov_path = out / "coverage.json"
    if not cov_path.is_file():
        return []
    cov = json.loads(cov_path.read_text(encoding="utf-8"))
    ids = {x["id"] for x in labels}
    executed: dict[str, set[tuple[str, int]]] = {i: set() for i in ids}
    unmatched = 0
    for ctx, files in cov["lines_by_context"].items():
        tid = _context_to_id(ctx, ids)
        if tid is None:
            unmatched += 1
            continue
        for f, lines in files.items():
            executed[tid].update((f, ln) for ln in lines)
    covered = sorted({pair for s in executed.values() for pair in s})
    diffs = random.Random(B2_SEED).sample(covered, B2_DIFFS)
    word = {"flaky": "flaky", "real_fail": "real", "no_evidence": "none_seen"}
    rows = []
    for n in N_VALUES:
        first = fixed_runs[:n]
        failed_any = {i: any(r["outcomes"].get(i) == "FAIL" for r in first) for i in ids}
        per_diff = []
        for line in diffs:
            clf = B2CoverageClassifier(changed_lines={line})
            preds = {i: word[clf.classify_test(i, failed_any[i], executed[i]).prediction] for i in sorted(ids)}
            per_diff.append({"changed_line": list(line), "preds": preds, "score": score(labels, preds)})
        order = sorted(range(len(per_diff)), key=lambda k: (per_diff[k]["score"]["recall"]["value"] or 0, k))
        typical = per_diff[order[len(order) // 2]]
        minutes = (sum(r["seconds"] for r in first) + cov["seconds"]) / 60
        extra = {
            "diff_used_for_the_row": typical["changed_line"],
            "across_diffs": {
                "n_diffs": len(per_diff),
                "recall": {"min": min(d["score"]["recall"]["value"] or 0 for d in per_diff),
                           "max": max(d["score"]["recall"]["value"] or 0 for d in per_diff)},
                "wrongly_flagged_flaky": {"min": min(d["score"]["wrongly_flagged_flaky"]["k"] for d in per_diff),
                                          "max": max(d["score"]["wrongly_flagged_flaky"]["k"] for d in per_diff)},
                "changed_lines": [d["changed_line"] for d in per_diff],
            },
            "note": f"The row scores the diff with the median recall of the {B2_DIFFS} sampled one-line diffs; across_diffs gives the range. "
                    f"Coverage contexts that match no test id: {unmatched}.",
            "minutes_include": f"{n} fixed-order runs plus one coverage run",
        }
        rows.append(_method_row("b2_coverage_diff", n, minutes, typical["preds"], labels, scope2, extra))
    return rows


# ------------------------------------------------------------------------------------- B3


def _test_sources(label: str) -> dict[str, str]:
    """Source text of every test function or method, by test id."""
    import ast

    root, _, _ = _suite_root_and_env(label)
    prefix = DATASETS[label]["id_prefix"]
    suite_dir = root / DATASETS[label]["suite"]
    out: dict[str, str] = {}
    for path in sorted(suite_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        rel = f"{prefix}{path.relative_to(root).as_posix()}"
        for node in ast.parse(text).body:
            if isinstance(node, ast.FunctionDef):
                out[f"{rel}::{node.name}"] = ast.get_source_segment(text, node) or ""
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        out[f"{rel}::{node.name}::{item.name}"] = ast.get_source_segment(text, item) or ""
    return out


B3_WORD = {"flaky": "flaky", "real": "real_fail", "stable": "no_evidence"}
B3_BACK = {"flaky": "flaky", "real_fail": "real", "no_evidence": "none_seen"}


def _features(labels: list[dict], runs: list[dict], sources: dict[str, str], use_code: bool):
    return [extract_features_from_runs(
        x["id"], [r["outcomes"][x["id"]] for r in runs if x["id"] in r["outcomes"]],
        [r["durations"][x["id"]] for r in runs if x["id"] in r["durations"]], sources.get(x["id"], "") if use_code else "")
        for x in labels]


def b3_rows(labels: list[dict], fixed_runs: list[dict], planted_runs: list[dict], scope2) -> list[dict]:
    planted_labels = json.loads((REPO / DATASETS["planted"]["labels"]).read_text(encoding="utf-8"))
    p_sources, i_sources = _test_sources("planted"), _test_sources("injected")
    model = "sklearn RandomForestClassifier(n_estimators=50, random_state=42) via flakeguard.baselines.b3_feature_classifier.B3FeatureClassifier"
    rows = []
    for use_code, tag in ((True, "b3"), (False, "b3_run_features_only")):
        for n in N_VALUES:
            train_x = _features(planted_labels, planted_runs[:n], p_sources, use_code)
            train_y = [B3_WORD[x["label"]] for x in planted_labels]
            test_x = _features(labels, fixed_runs[:n], i_sources, use_code)
            start = time.perf_counter()
            clf = B3FeatureClassifier()
            clf.fit(train_x, train_y)
            preds = {x["id"]: B3_BACK[clf.predict(f)[0]] for x, f in zip(labels, test_x)}
            minutes = (sum(r["seconds"] for r in fixed_runs[:n]) + (time.perf_counter() - start)) / 60
            rows.append(_method_row(f"{tag}_trained_on_planted", n, minutes, preds, labels, scope2, {
                "training": f"MAIN: trained on the {len(planted_labels)} planted tests (features from {n} fixed-order planted runs); "
                            f"scored on the {len(labels)} injected tests, none of which it was trained on",
                "model": model,
                "features": "failure rate, pass rate, flips, flip rate, entropy, duration mean and std"
                            + (", and sleep/random/datetime in the test source" if use_code else " (no code features)"),
                "minutes_include": f"{n} fixed-order runs of the injected suite plus training and scoring"}))
    # secondary check: leave one out inside the injected tests
    for use_code, tag in ((True, "b3"), (False, "b3_run_features_only")):
        for n in N_VALUES:
            feats = _features(labels, fixed_runs[:n], i_sources, use_code)
            words = [B3_WORD[x["label"]] for x in labels]
            preds = {}
            start = time.perf_counter()
            for k, x in enumerate(labels):
                clf = B3FeatureClassifier()
                clf.fit(feats[:k] + feats[k + 1:], words[:k] + words[k + 1:])
                preds[x["id"]] = B3_BACK[clf.predict(feats[k])[0]]
            minutes = (sum(r["seconds"] for r in fixed_runs[:n]) + (time.perf_counter() - start)) / 60
            rows.append(_method_row(f"{tag}_leave_one_out_injected", n, minutes, preds, labels, scope2, {
                "training": f"SECONDARY check: for each of the {len(labels)} injected tests, trained on the other "
                            f"{len(labels) - 1} injected tests and scored on the held-out one",
                "model": model,
                "minutes_include": f"{n} fixed-order runs plus {len(labels)} fits (a real CI would fit once; this is the leave-one-out cost)"}))
    return rows


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
    differs = [i for i in ids if adaptive[i]["decision"] != fixed20[i]]
    interesting = {x["id"] for x in labels if x["label"] != "stable"} | set(differs)
    per_test = {x["id"]: {"label": x["label"], "root_cause": x["root_cause"],
                          "failures_in_20": sum(o == "FAIL" for o in seqs[x["id"]][:MAX_RUNS]),
                          "fixed_20": fixed20[x["id"]], "adaptive": adaptive[x["id"]]}
                for x in labels if x["id"] in interesting}
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
        "tradeoff": {
            "whole_suite_runs_saved": {"k": MAX_RUNS - max(adaptive[i]["runs_used"] for i in ids), "n": MAX_RUNS},
            "flaky_found_adaptive": {"k": sum(adaptive[x["id"]]["decision"] == "flaky" and x["label"] == "flaky" for x in labels),
                                     "n": sum(x["label"] == "flaky" for x in labels)},
            "flaky_found_fixed_20": {"k": sum(fixed20[x["id"]] == "flaky" and x["label"] == "flaky" for x in labels),
                                     "n": sum(x["label"] == "flaky" for x in labels)},
            "missed_by_adaptive_but_found_by_fixed_20": [i for i in ids if fixed20[i] == "flaky" and adaptive[i]["decision"] != "flaky"],
            "stop_rule_disclosure": "The stop rule (a test with no failure is declared 'no evidence' once runs >= 10, whether or not the credible-interval bound is met) is existing code in flakeguard/stats/adaptive.py. It was not tuned on this data or by us for this evaluation.",
        },
        "note": "The adaptive count is per test. One whole-suite run executes every test, so the suite stops only after the "
                "last test is decided (suite_runs_until_every_test_decided_adaptive); the per-test saving is not a wall-clock saving "
                "unless that number is below 20. per_test lists the tests that are not labelled stable and every test where adaptive and fixed differ.",
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
    ap.add_argument("--steps", default=None, help="comma list of: runs (execute B1 and perturbation), coverage (B2 input), rq1, rq2")
    ap.add_argument("--out", default="results")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the injected dataset even if it exists")
    args = ap.parse_args(argv)
    steps = set((args.steps or DEFAULT_STEPS[args.label]).split(","))
    out = REPO / args.out / args.label
    labels = prepare(args.label, args.rebuild)
    command = "python " + " ".join(["scripts/run_eval.py", *(argv if argv is not None else sys.argv[1:])])
    prov = provenance(args.label, labels, command)

    if "runs" in steps:
        for name, shuffled in (("b1_fixed_order", False), ("perturbation", True)):
            runs = run_series(args.label, shuffled, MAX_RUNS, labels)
            write(out / f"{name}.json", {"provenance": prov, "method": name, "runs": runs})
    if "coverage" in steps and args.label == "injected":
        coverage_step(args.label, out)
    recorded = {name: json.loads((out / f"{name}.json").read_text(encoding="utf-8")) for name in ("b1_fixed_order", "perturbation")}
    series = {name: doc["runs"] for name, doc in recorded.items()}
    prov["runs_recorded"] = {name: {k: doc["provenance"][k] for k in ("command", "date_utc", "commit", "tracked_files_modified")}
                             for name, doc in recorded.items()}
    if "rq1" in steps:
        planted = REPO / args.out / "planted" / "b1_fixed_order.json"
        planted_runs = json.loads(planted.read_text(encoding="utf-8"))["runs"] if planted.is_file() else None
        write(out / "rq1.json", {"provenance": prov, **rq1(args.label, labels, series, out, planted_runs)})
    if "rq2" in steps:
        write(out / "rq2.json", {"provenance": prov, **rq2(labels, series["perturbation"])})
    return 0


if __name__ == "__main__":
    sys.exit(main())
