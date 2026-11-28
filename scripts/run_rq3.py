"""RQ3: false-red PRs cleared and real failures wrongly quarantined. A SIMULATION over labelled tests.

    python scripts/run_rq3.py planted
    python scripts/run_rq3.py injected

No pull request is opened and FlakeGuard's PR flow is not run. Each labelled test is treated as the one new test of a PR whose
other changes are fine, and the pipelines are applied to the runs recorded in results/<label>/ by scripts/run_eval.py.
The definition is in docs/EVAL.md (section RQ3), written before this was run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_eval", REPO / "scripts" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

N_VALUES = run_eval.N_VALUES
MAX_RUNS = run_eval.MAX_RUNS


def decisions(labels: list[dict], fixed: list[dict], shuffled: list[dict]) -> dict[str, dict[str, str]]:
    """What each pipeline says about each test: flaky | real | none_seen (| undecided for adaptive)."""
    ids = [x["id"] for x in labels]

    def seq(runs: list[dict], tid: str) -> list[str]:
        return [r["outcomes"][tid] for r in runs if tid in r["outcomes"]]

    out = {
        "naive_ci_one_fixed_order_run": {i: ("real" if seq(fixed, i)[:1] == ["FAIL"] else "none_seen") for i in ids},
        f"b1_fixed_order_rerun_n{MAX_RUNS}": {i: run_eval.classify(seq(fixed, i)[:MAX_RUNS]) for i in ids},
    }
    for n in N_VALUES:
        out[f"flakeguard_shuffled_runs_n{n}"] = {i: run_eval.classify(seq(shuffled, i)[:n]) for i in ids}
    out["flakeguard_adaptive_stopping"] = {i: run_eval.adaptive_decision(i, seq(shuffled, i))["decision"] for i in ids}
    return out


def table(labels: list[dict], fixed: list[dict], shuffled: list[dict]) -> dict:
    ids_by = {k: [x["id"] for x in labels if x["label"] == k] for k in ("flaky", "real", "stable")}
    dec = decisions(labels, fixed, shuffled)
    naive = dec["naive_ci_one_fixed_order_run"]
    false_red = [i for i in ids_by["flaky"] if naive[i] == "real"]
    never_red = [i for i in ids_by["flaky"] if not any(r["outcomes"].get(i) == "FAIL" for r in fixed + shuffled)]
    rows = {}
    for name, d in dec.items():
        def count(ids: list[str], word: str) -> int:
            return sum(d[i] == word for i in ids)

        rows[name] = {
            "false_red_prs": {
                "n_red_flaky_prs": len(false_red),
                "cleared_called_flaky": run_eval.rate(count(false_red, "flaky"), len(false_red)),
                "still_blocked_called_real": run_eval.rate(count(false_red, "real"), len(false_red)),
                "no_evidence_or_undecided": run_eval.rate(len(false_red) - count(false_red, "flaky") - count(false_red, "real"), len(false_red)),
            },
            "flaky_tests_called_real": {**run_eval.rate(count(ids_by["flaky"], "real"), len(ids_by["flaky"])),
                                        "ids": [i for i in ids_by["flaky"] if d[i] == "real"],
                                        "meaning": "a PR with this test would be blocked as a real bug"},
            "real_failures": {
                "called_real": run_eval.rate(count(ids_by["real"], "real"), len(ids_by["real"])),
                "wrongly_quarantined_called_flaky": {**run_eval.rate(count(ids_by["real"], "flaky"), len(ids_by["real"])),
                                                     "ids": [i for i in ids_by["real"] if d[i] == "flaky"]},
            },
            "stable_tests_wrongly_flagged_flaky": {**run_eval.rate(count(ids_by["stable"], "flaky"), len(ids_by["stable"])),
                                                   "ids": [i for i in ids_by["stable"] if d[i] == "flaky"]},
        }
    # Every one of the 20 recorded fixed-order runs, read as a separate hypothetical CI run: pairs of (test, run).
    pairs = {}
    for kind in ("flaky", "real", "stable"):
        n = sum(1 for i in ids_by[kind] for r in fixed if i in r["outcomes"])
        k = sum(r["outcomes"].get(i) == "FAIL" for i in ids_by[kind] for r in fixed)
        pairs[kind] = run_eval.rate(k, n)
    return {
        "n_by_label": {k: len(v) for k, v in ids_by.items()},
        "pipelines": rows,
        "naive_ci_over_all_recorded_fixed_order_runs": {
            "meaning": "fraction of (test, fixed-order run) pairs that are red, each run read as one hypothetical CI run",
            "red_pairs_by_label": pairs},
        "flaky_tests_that_never_failed_in_any_recorded_run": {"k": len(never_red), "n": len(ids_by["flaky"]), "ids": never_red,
                                                              "meaning": "cannot be red in this simulation (for injected: the time_tz faults, daytime runs)"},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", choices=["planted", "injected"])
    args = ap.parse_args(argv)
    labels = run_eval.prepare(args.label)
    out = REPO / "results" / args.label
    fixed = json.loads((out / "b1_fixed_order.json").read_text(encoding="utf-8"))["runs"]
    shuffled = json.loads((out / "perturbation.json").read_text(encoding="utf-8"))["runs"]
    command = "python " + " ".join(["scripts/run_rq3.py", *(argv if argv is not None else sys.argv[1:])])
    prov = run_eval.provenance(args.label, labels, command)
    prov["tolerances"] = {"b1_fixed_order": run_eval.B1_TOLERANCE,
                          "everything_else": "exact given the recorded runs; the runs themselves are re-made by run_eval.py"}
    prov["runs_recorded"] = {n: {k: d["provenance"][k] for k in ("command", "date_utc", "commit")}
                             for n, d in (("b1_fixed_order", json.loads((out / "b1_fixed_order.json").read_text(encoding="utf-8"))),
                                          ("perturbation", json.loads((out / "perturbation.json").read_text(encoding="utf-8"))))}
    doc = {
        "provenance": prov,
        "simulation": "SIMULATION over labelled tests. No pull request was opened and no FlakeGuard PR flow was run. Each labelled test is "
                      "treated as the one new test of a PR whose other changes are fine; the pipelines below are applied to the recorded runs. "
                      "'Naive CI' is one fixed-order run: any failure turns the PR red.",
        "definitions": "docs/EVAL.md, section RQ3",
        "primary": table(labels, fixed, shuffled),
    }
    second = run_eval.sensitivity(args.label, labels, {"b1": fixed, "perturbation": shuffled})
    if second is not None:
        doc["sensitivity"] = {"scope": second[1], **table(second[0], fixed, shuffled)}
    doc["natural"] = {"status": "not run", "note": "no natural dataset: shown as dashes"}
    doc["real_pull_requests"] = {
        "note": "Two real pull requests of the demo repository, mentioned as anecdotes only. They are not data for any figure above.",
        "pr3": "act1-deterministic-test: a clean change; FlakeGuard's comment said no evidence of flakiness in 10 shuffled runs.",
        "pr4": "act2-seeded-faults: a revert that brings four faulty tests back; the comment named test_report_total flaky and order-dependent, test_reserve_negative a real failure, test_sync_timeout unknown.",
    }
    run_eval.write(out / "rq3.json", doc)
    for name, row in doc["primary"]["pipelines"].items():
        fr = row["false_red_prs"]
        print(f"{name:34} false-red cleared {fr['cleared_called_flaky']['k']}/{fr['n_red_flaky_prs']}  flaky called real {row['flaky_tests_called_real']['k']}/{row['flaky_tests_called_real']['n']}"
              f"  real quarantined {row['real_failures']['wrongly_quarantined_called_flaky']['k']}/{row['real_failures']['called_real']['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
