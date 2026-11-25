"""Analysis of the masked RQ4 rerun. Read-only on results/injected/rq4.json and rq4_masked.json; writes rq4_masked_analysis.json.

Planned comparisons (registered in docs/EVAL.md before the run): masked ast vs none, masked ast_jedi vs none, masked vs unmasked ast,
masked vs unmasked ast_jedi; two-sided exact McNemar on the same 26 tests, Bonferroni threshold 0.05 / 4. Nothing is rescored.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from rq4_integrity import mcnemar_exact, wilson  # noqa: E402

SETTINGS = ("ast", "ast_jedi")


def rows(doc: dict, setting: str) -> dict[str, dict]:
    return {r["id"]: r for r in doc["per_test"] if r["setting"] == setting}


def describe(rs: dict[str, dict]) -> dict:
    k = sum(bool(r["match"]) for r in rs.values())
    causes = sorted({r["known_cause"] for r in rs.values()})
    return {
        "k": k, "n": len(rs), "wilson95": wilson(k, len(rs)),
        "by_known_cause": {c: {"k": sum(bool(r["match"]) for r in rs.values() if r["known_cause"] == c), "n": sum(r["known_cause"] == c for r in rs.values())} for c in causes},
        "answers": dict(collections.Counter(r["model_cause"] for r in rs.values())),
        "confusion_true_by_answered": {c: dict(collections.Counter(r["model_cause"] for r in rs.values() if r["known_cause"] == c)) for c in causes},
        "unreadable_replies": sum(not r["readable"] for r in rs.values()),
        "replies_saying_random": sum(r["model_cause"] == "random" for r in rs.values()),
        "prompts_that_filled_the_context": sum(bool(r["truncated"]) for r in rs.values()),
    }


def pair(a: dict[str, dict], b: dict[str, dict], name_a: str, name_b: str) -> dict:
    ids = list(a)
    only_a = sum(bool(a[i]["match"]) and not b[i]["match"] for i in ids)
    only_b = sum(bool(b[i]["match"]) and not a[i]["match"] for i in ids)
    return {f"right_only_in_{name_a}": only_a, f"right_only_in_{name_b}": only_b, "p_two_sided": round(mcnemar_exact(only_a, only_b), 4), "kind": "planned"}


def main() -> int:
    res = REPO / "results" / "injected"
    base = json.loads((res / "rq4.json").read_text(encoding="utf-8"))
    masked = json.loads((res / "rq4_masked.json").read_text(encoding="utf-8"))
    none = rows(base, "none")
    out: dict = {"source": "results/injected/rq4.json (not changed) and rq4_masked.json", "mask": masked["provenance"].get("mask"),
                 "bonferroni_threshold": round(0.05 / 4, 4), "planned_pairs": 4, "n_tests": len(none), "settings": {}, "mcnemar_exact_paired": {}}
    for s in SETTINGS:
        un, ma = rows(base, s), rows(masked, s)
        assert list(un) == list(ma) == list(none), "the masked run must cover the same 26 tests in the same order"
        changed = [i for i in un if un[i]["code_chars"] != ma[i]["code_chars"]]
        out["settings"][s] = {
            "unmasked": describe(un), "masked": describe(ma),
            "prompts_changed_by_masking": len(changed),
            "answers_changed_among_changed_prompts": sum(un[i]["model_cause"] != ma[i]["model_cause"] for i in changed),
            "answers_changed_among_unchanged_prompts": sum(un[i]["model_cause"] != ma[i]["model_cause"] for i in un if i not in changed),
            "per_test": [{"id": i, "true_cause": un[i]["known_cause"], "prompt_changed": i in changed, "unmasked_answer": un[i]["model_cause"],
                          "masked_answer": ma[i]["model_cause"], "unmasked_match": bool(un[i]["match"]), "masked_match": bool(ma[i]["match"])} for i in un],
        }
        out["mcnemar_exact_paired"][f"masked_{s}_vs_none"] = pair(none, ma, "none", f"masked_{s}")
        out["mcnemar_exact_paired"][f"masked_{s}_vs_unmasked_{s}"] = pair(un, ma, f"unmasked_{s}", f"masked_{s}")
    out["none"] = describe(none)
    dest = res / "rq4_masked_analysis.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
