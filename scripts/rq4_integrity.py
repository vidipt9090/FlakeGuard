"""RQ4 integrity checks. Read-only on results/injected/rq4.json and on .eval_cache; writes only
results/injected/rq4_integrity.json.

Nothing here rescored the RQ4 result: it reads the recorded answers and adds (a) confusion matrices, (b) a constant-guess
baseline, (c) Wilson intervals and exact McNemar tests on the same 26 tests, (d) which contexts contain words that name
the fault class, (e) the answers given for the shared_state and randomness tests.
"""
from __future__ import annotations

import collections
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

SETTINGS = ("none", "file", "ast", "ast_jedi")
CAUSES = ("order_dependence", "shared_state", "timing", "randomness", "time_or_timezone", "other")

# Words that name each fault class. Fixed here before looking at any context; a hit is a hint, not proof the model used it.
KEYWORDS = {
    # taken from the identifiers flakeguard/injector/operators.py inserts (read, not guessed)
    "order_dependence": r"_FLAKEGUARD_ORDER\w*",
    "shared_state": r"_FLAKEGUARD_SHARED\w*",
    "timing": r"sleep|Thread|threading|_race\w*",
    "randomness": r"\brandom\b|_fg_random|random\.\w+",
    "time_or_timezone": r"datetime|\bnow\(",
}


def wilson(k: int, n: int, z: float = 1.959964) -> list[float]:
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p from the discordant counts b (A right, B wrong) and c (A wrong, B right)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main() -> int:
    data = json.loads((REPO / "results" / "injected" / "rq4.json").read_text(encoding="utf-8"))
    rows = data["per_test"]
    by = {s: {r["id"]: r for r in rows if r["setting"] == s} for s in SETTINGS}
    ids = list(by["none"])
    truth = {i: by["none"][i]["known_cause"] for i in ids}
    out: dict = {"source": "results/injected/rq4.json (not changed)", "n_tests": len(ids),
                 "class_counts": dict(collections.Counter(truth.values()))}

    out["confusion_true_by_answered"] = {
        s: {t: dict(collections.Counter(by[s][i]["model_cause"] for i in ids if truth[i] == t))
            for t in sorted(set(truth.values()))} for s in SETTINGS}

    best_class, best_k = collections.Counter(truth.values()).most_common(1)[0]
    out["constant_guess"] = {"best_class": best_class, "k": best_k, "n": len(ids), "value": round(best_k / len(ids), 4),
                             "uniform_one_of_five": 0.2,
                             "note": "ties: the most common class is the one with the most tests; shared_state has 6, others 5"}

    ok = {s: {i: bool(by[s][i]["match"]) for i in ids} for s in SETTINGS}
    out["wilson95"] = {s: {"k": sum(ok[s].values()), "n": len(ids), "ci": wilson(sum(ok[s].values()), len(ids))} for s in SETTINGS}
    pairs = [("none", "ast"), ("none", "ast_jedi"), ("ast", "ast_jedi"), ("none", "file"), ("file", "ast_jedi")]
    out["mcnemar_exact_paired"] = {}
    for a, b in pairs:
        only_a = sum(ok[a][i] and not ok[b][i] for i in ids)
        only_b = sum(ok[b][i] and not ok[a][i] for i in ids)
        out["mcnemar_exact_paired"][f"{a}_vs_{b}"] = {
            f"right_only_in_{a}": only_a, f"right_only_in_{b}": only_b, "p_two_sided": round(mcnemar_exact(only_a, only_b), 4),
            "kind": "planned" if (a, b) in pairs[:3] else "exploratory",
            "note": "three pairs were asked for; the last two are extra and make five comparisons with no correction" if (a, b) in pairs[3:] else ""}

    out["mcnemar_multiplicity"] = {"planned_pairs": 3, "bonferroni_threshold": round(0.05 / 3, 4),
                                   "note": "planned = none vs ast, none vs ast_jedi, ast vs ast_jedi; exploratory pairs are not corrected and are not tested against this threshold"}

    sel = [i for i in ids if truth[i] in ("shared_state", "randomness")]
    out["shared_state_and_randomness_answers"] = {
        s: {t: dict(collections.Counter(by[s][i]["model_cause"] for i in sel if truth[i] == t)) for t in ("shared_state", "randomness")}
        for s in SETTINGS}
    out["shared_state_and_randomness_n"] = {t: sum(truth[i] == t for i in sel) for t in ("shared_state", "randomness")}

    # (d) words that name the fault class in the text the model was sent (rebuilt by the runner's own function).
    import run_rq4
    root = run_rq4.VIEW
    nav = run_rq4.AstNavigator(root)
    hits: dict = {}
    for s in ("ast", "ast_jedi"):
        hits[s] = {}
        for i in ids:
            text = run_rq4.context(s, "injected", i, nav, root)
            pat = KEYWORDS.get(truth[i])
            found = sorted(set(m.group(0) for m in re.finditer(pat, text))) if pat else []
            hits[s][i] = {"true_cause": truth[i], "names_the_fault": bool(found), "matches": found[:6], "chars": len(text)}
        out.setdefault("context_names_fault_summary", {})[s] = {
            "yes": sum(v["names_the_fault"] for v in hits[s].values()), "n": len(ids)}
        out["context_names_fault_summary"][s]["by_cause"] = {
            t: f"{sum(v['names_the_fault'] for v in hits[s].values() if v['true_cause'] == t)} of {sum(v['true_cause'] == t for v in hits[s].values())}"
            for t in sorted(set(truth.values()))}
    out["context_names_fault_per_test"] = hits
    out["keywords_used"] = KEYWORDS
    out["limitation"] = ("A keyword hit means the text sent to the model holds a word that names the fault class; it does not show the model used it. "
                         "No answer was rescored.")

    dest = REPO / "results" / "injected" / "rq4_integrity.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
