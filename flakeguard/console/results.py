"""Turns the recorded runs in ``results/<label>/*.json`` into what the Results screen shows.

Every cell is read from a file written by ``scripts/run_eval.py``, ``run_rq3.py`` or ``run_rq4.py``. A number that is not in a
file is ``None`` and shows as a dash; nothing here estimates, rounds up or fills a gap. Only the three label folders are ever read:
``results/eval3`` (the superseded numbers that were typed into a script) is never served.
"""

from __future__ import annotations

import json
from pathlib import Path

from flakeguard.console import models as m

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
LABELS = ("injected", "natural", "planted")
SETTING_NAMES = {"none": "No code", "file": "The whole file", "ast": "AST tree only", "ast_jedi": "AST + Jedi tree"}
METHOD_NAMES = {
    "b1_fixed_order": "Rerun in the same order (B1)",
    "perturbation": "Shuffled runs (perturbation)",
    "b2_coverage_diff": "Coverage diff (B2)",
    "b3": "Trained classifier, run and code features (B3)",
    "b3_run_features_only": "Trained classifier, run features only (B3)",
}
TIME_TZ_NOTE = "The clock-dependent (time_tz) faults can fail only outside 08:00 to 18:00 local time. All runs were made inside that window, so no method can find them here; the sensitivity scope sets them aside."
NO_NATURAL = "No natural dataset: no flakes from real projects were available, so every natural figure is a dash."


def _load(label: str, name: str, root: Path) -> dict | None:
    path = root / label / name
    if label not in LABELS or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_file(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _prov(label: str, doc: dict | None) -> m.Provenance:
    if doc is None:
        return m.Provenance(dataset=None, labelType=label, n=None, command=None, date=None, commit=None)  # type: ignore[arg-type]
    p = doc["provenance"]
    d = p["dataset"]
    base = d.get("base") or d["suite"]
    by = ", ".join(f"{k} {v}" for k, v in sorted(d["n_by_label"].items()))
    return m.Provenance(dataset=f"{label}: {base} ({by})", labelType=label, n=d["n_tests"], command=p["command"],
                        date=p["date_utc"], commit=p["commit"][:7] + (" (files modified)" if p.get("tracked_files_modified") else ""))


def _rate(r: dict | None, what: str = "") -> str | None:
    if not r or r.get("value") is None:
        return None
    lo, hi = r["ci95_wilson"]
    return f"{r['k']} of {r['n']}{what} (95% CI {lo:.2f} to {hi:.2f})"


def _count(r: dict | None, what: str = "") -> str | None:
    return None if not r else f"{r['k']} of {r['n']}{what}"


def _scopes(row: dict) -> dict:
    return {"primary": row["all_tests"], **({"sensitivity": row["sensitivity"]} if "sensitivity" in row else {})}


def baselines_table(label: str, doc: dict | None) -> m.TableWithProvenance:
    cols = ["Method", "Flaky tests found", "Wrongly flagged", "CI minutes used"]
    if doc is None:
        return m.TableWithProvenance(table=m.ResultsTable(columns=cols, rows=[]), provenance=_prov(label, None))
    rows: list[list[str | None]] = []
    for r in doc["rows"]:
        a = r["all_tests"]
        name = METHOD_NAMES.get(r["method"], r["method"].replace("_", " "))
        extra = r.get("variant")
        found = f"{a['flaky_found']['k']} of {a['flaky_found']['n']} flaky (recall {a['recall']['value']:.2f}, 95% CI {a['recall']['ci95_wilson'][0]:.2f} to {a['recall']['ci95_wilson'][1]:.2f})"
        if r["method"] in ("b1_fixed_order", "b2_coverage_diff"):
            found += "; varies by 1 to 2 tests between executions (see the notes)"
        if r["method"].startswith("b3"):
            found += "; varies a lot between executions (see the notes)"
        wrong = f"{a['wrongly_flagged_flaky']['k']} of {a['wrongly_flagged_flaky']['n']} not flaky"
        rows.append([f"{name}, N={r['full_suite_runs']} runs" + (f" ({extra})" if extra else ""), found, wrong,
                     f"{r['minutes_measured']:.2f} min (budget {doc['provenance']['budget_minutes']:.0f})"])
    for name, why in doc.get("methods_not_run", {}).items():
        rows.append([f"{METHOD_NAMES.get(name, name)}: not run on this set ({why})", None, None, None])
    return m.TableWithProvenance(table=m.ResultsTable(columns=cols, rows=rows), provenance=_prov(label, doc))


def ablation_table(label: str, rq4: dict | None) -> m.TableWithProvenance:
    cols = ["Context given to the model", "Diagnosis matches the known cause", "Fix passes validation under shuffle", "Code sent to the model"]
    if label == "injected" and rq4 is not None:
        rows = []
        for s, r in rq4["results"].items():
            fx = r.get("fix")
            rows.append([SETTING_NAMES.get(s, s), _rate(r["diagnosis_matches"], " flaky tests")
                         + (f"; {r['unreadable_replies_counted_as_failures']} unreadable replies counted as failures" if r["unreadable_replies_counted_as_failures"] else "")
                         + (f" (if the word 'random' were accepted as randomness: {r['sensitivity_if_random_were_accepted_as_randomness']['k']} of {r['sensitivity_if_random_were_accepted_as_randomness']['n']}; not the result)"
                            if r.get("sensitivity_if_random_were_accepted_as_randomness", {}).get("replies_saying_random") else ""),
                         f"{fx['validated']} of {fx['n']} (N={fx['n']}, counts not rates)" if fx else None,
                         f"mean {r['code_chars_sent']['mean']:.0f} characters, {r['prompt_tokens']['mean']:.0f} tokens per prompt"
                         if r["prompt_tokens"]["mean"] is not None else None])
        return m.TableWithProvenance(table=m.ResultsTable(columns=cols, rows=rows), provenance=_prov(label, rq4))
    rows = [[SETTING_NAMES[s], None, None, None] for s in SETTING_NAMES]
    return m.TableWithProvenance(table=m.ResultsTable(columns=cols, rows=rows), provenance=_prov(label, None))


def triage_table(label: str, rq3: dict | None) -> m.TableWithProvenance:
    cols = ["Pipeline (simulation)", "False-red PRs cleared", "Flaky tests it would block as real bugs", "Real failures wrongly quarantined", "Stable tests wrongly flagged"]
    if rq3 is None:
        return m.TableWithProvenance(table=m.ResultsTable(columns=cols, rows=[]), provenance=_prov(label, None))
    rows = []
    for name, p in rq3["primary"]["pipelines"].items():
        fr = p["false_red_prs"]
        rows.append([name.replace("_", " "),
                     None if not fr["n_red_flaky_prs"] else _count(fr["cleared_called_flaky"], f" red flaky PRs (N={fr['n_red_flaky_prs']})"),
                     _count(p["flaky_tests_called_real"], " flaky tests"),
                     _count(p["real_failures"]["wrongly_quarantined_called_flaky"], " real failures"),
                     _count(p["stable_tests_wrongly_flagged_flaky"], " stable tests")])
    return m.TableWithProvenance(table=m.ResultsTable(columns=cols, rows=rows), provenance=_prov(label, rq3))


def load_results(label: str, root: Path | None = None) -> m.ResultsData:
    if label not in LABELS:
        raise ValueError(f"no results for {label!r}")
    root = root or RESULTS_DIR
    rq1, rq2, rq3, rq4 = (_load(label, f"{n}.json", root) for n in ("rq1", "rq2", "rq3", "rq4"))
    notes: list[str] = []
    if label == "natural":
        notes.append(NO_NATURAL)
    if label == "planted":
        notes.append("RQ4 (context ablation) is evaluated on the injected set only. The planted set was used to tune the prompt, so its RQ4 cells are dashes here; the tuning scores are in docs/EVAL.md and are not a result.")
    if rq1 is not None:
        notes += [*rq1["provenance"]["limitations"], "B1 (and B2, which is built from the same fixed-order runs) found-flaky counts vary between executions by about 1 test, and by up to 2 at N=5 and N=10 in the clean re-run (unseeded randomness tests)."]
        if label == "injected" and "b3" in rq1["provenance"]["tolerances"]:
            notes.append(rq1["provenance"]["tolerances"]["b3"])
    if label == "injected":
        notes += [TIME_TZ_NOTE] if TIME_TZ_NOTE not in notes else []
    again = _load_file(root / "clean_rerun_comparison.json")
    if again is not None and rq1 is not None:
        mine = next((d for d in again["labels"] if d["label"] == label), None)
        if mine:
            g = mine["max_found_difference_by_family"]
            notes.append(f"Observed on a re-run from a clean checkout: found-flaky counts differed by at most {g.get('b1', 0)} for B1, {g.get('b2', 0)} for B2 and "
                         f"{g.get('b3', 0)} for B3 (B3's wrongly-flagged counts differed much more); shuffled-run (perturbation) calls differed by {g.get('perturbation', 0)}.")
    if rq3 is not None:
        notes.append("RQ3 is a simulation over labelled tests. No pull request was opened and FlakeGuard's PR flow was not run.")
    if rq4 is not None:
        notes += [x for x in rq4["provenance"]["limitations"] if x not in notes]
    fixed = adaptive = red = real_q = None
    if rq2 is not None:
        a = rq2["runs_to_decision_adaptive"]
        t = rq2["tradeoff"]
        fixed = f"{rq2['runs_to_decision_fixed']['N=20']['mean']:.0f} runs for every test (N={a['n_tests']} tests)"
        adaptive = (f"mean {a['mean']:.1f} runs per test (95% bootstrap CI {a['mean_ci95_bootstrap'][0]:.2f} to {a['mean_ci95_bootstrap'][1]:.2f}, N={a['n_tests']} tests); "
                    f"saves {t['whole_suite_runs_saved']['k']} of {t['whole_suite_runs_saved']['n']} whole-suite runs; finds {t['flaky_found_adaptive']['k']} of "
                    f"{t['flaky_found_adaptive']['n']} flaky tests where fixed 20 finds {t['flaky_found_fixed_20']['k']}. The stop rule is existing code, not tuned by us.")
    if rq3 is not None:
        p = rq3["primary"]["pipelines"]["flakeguard_shuffled_runs_n10"]
        fr = p["false_red_prs"]
        red = _count(fr["cleared_called_flaky"], f" red flaky PRs (N={fr['n_red_flaky_prs']}, shuffled runs N=10)") if fr["n_red_flaky_prs"] else None
        real_q = _count(p["real_failures"]["wrongly_quarantined_called_flaky"], " real failures (shuffled runs N=10)")
    return m.ResultsData(
        ablation=ablation_table(label, rq4),
        baselines=baselines_table(label, rq1),
        runsToDecision=m.RunsToDecision(fixed=fixed, adaptive=adaptive),
        triage=m.TriageNumbers(redPrsCleared=red, realQuarantined=real_q),
        triageTable=triage_table(label, rq3),
        notes=notes,
        status=("not run" if label == "natural" else "run" if rq1 is not None else "not run"),
    )
