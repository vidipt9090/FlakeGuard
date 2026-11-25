"""Leakage split for the RQ4 contexts. Read-only on results and on the dataset; writes results/injected/rq4_leakage_split.json.

For every flaky test and each of the file, ast and ast_jedi settings, the text sent to the model is rebuilt with the runner's own
``context`` function, once from the injected suite (as the model saw it) and once from the pristine cachetools 8.0.2 sources.
Then, per test and setting:

(a) injector-specific: identifiers that start with an underscore inside the blocks flakeguard/injector/operators.py inserts
    (``_FLAKEGUARD_*``, ``_race_flag``, ``_fg_random``, ``_bg_job``, ``_th``, ``_hour``), plus marker words left in the text
    (``Injected``, ``FlakeGuard``, ``mutant``). Real code would not contain them.
(b) natural cues the injection introduced: a cue word (sleep, random, datetime, now, Thread, threading, global) that occurs more
    often in the injected text than in the pristine text. A real tool would also see these in real flaky code.
(c) cachetools' own: a cue word that occurs in the pristine text of the same test and setting.
    A cue can be in both (b) and (c) when the injection added occurrences to a word the library already had.

Nothing is rescored; prompts, labels and results are not changed.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import run_rq4  # noqa: E402

from flakeguard.injector import operators  # noqa: E402

CUES = ("sleep", "random", "datetime", "now", "Thread", "threading", "global")
MARKERS = ("Injected", "FlakeGuard", "mutant")
TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def injector_only_identifiers() -> set[str]:
    """Underscore-prefixed identifiers found in the blocks the operators insert (read from operators.py, not typed here)."""
    found: set[str] = set()
    for cls in vars(operators).values():
        if isinstance(cls, type) and issubclass(cls, operators.MutationOperator) and cls is not operators.MutationOperator:
            blocks = []
            for name in ("block", "setup_block"):
                fn = getattr(cls, name, None)
                if fn is not None:
                    try:
                        blocks += fn(cls.__new__(cls))
                    except Exception:  # an operator whose block needs state is skipped and reported below
                        pass
            for line in blocks:
                found |= {t for t in TOKEN.findall(line) if t.startswith("_") and not t.startswith("__")}
    return found


def counts(text: str) -> collections.Counter:
    return collections.Counter(TOKEN.findall(text))


def main() -> int:
    rq4 = json.loads((REPO / "results" / "injected" / "rq4.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in rq4["per_test"] if r["setting"] == "none"]
    cause = {r["id"]: r["known_cause"] for r in rq4["per_test"] if r["setting"] == "none"}
    only = injector_only_identifiers()
    inj_root, pri_root = run_rq4.VIEW, run_rq4.PRISTINE
    inj_nav, pri_nav = run_rq4.AstNavigator(inj_root), run_rq4.AstNavigator(pri_root)

    table, summary = [], {}
    for setting in ("file", "ast", "ast_jedi"):
        for tid in ids:
            a_text = run_rq4.context(setting, "injected", tid, inj_nav, inj_root)
            try:
                p_text = run_rq4.context(setting, "injected", tid, pri_nav, pri_root)
                pristine_ok = True
            except Exception as exc:  # recorded, not hidden
                p_text, pristine_ok = "", f"{type(exc).__name__}: {exc}"
            ca, cp = counts(a_text), counts(p_text)
            a_ids = {t: ca[t] for t in sorted(only) if ca[t]}
            a_marks = {m: len(re.findall(m, a_text)) for m in MARKERS if re.search(m, a_text)}
            b = {w: [cp[w], ca[w]] for w in CUES if ca[w] > cp[w]}
            c = {w: cp[w] for w in CUES if cp[w] > 0}
            table.append({"id": tid, "true_cause": cause[tid], "setting": setting, "chars": len(a_text),
                          "pristine_context_built": pristine_ok,
                          "a_injector_specific": a_ids, "a_markers": a_marks,
                          "b_natural_cues_added_by_injection": b,  # word: [count in pristine text, count in injected text]
                          "c_cachetools_own_cues": c})
        rows = [t for t in table if t["setting"] == setting]
        summary[setting] = {
            "tests": len(rows),
            "a_has_injector_specific_identifier": sum(bool(t["a_injector_specific"] or t["a_markers"]) for t in rows),
            "b_has_natural_cue_added": sum(bool(t["b_natural_cues_added_by_injection"]) for t in rows),
            "c_has_cachetools_own_cue": sum(bool(t["c_cachetools_own_cues"]) for t in rows),
            "a_only_no_natural_cue_added": sum(bool(t["a_injector_specific"] or t["a_markers"]) and not t["b_natural_cues_added_by_injection"]
                                               for t in rows),
            "neither_a_nor_b": sum(not (t["a_injector_specific"] or t["a_markers"]) and not t["b_natural_cues_added_by_injection"]
                                   for t in rows),
            "pristine_context_failed": sum(t["pristine_context_built"] is not True for t in rows),
        }

    out = {"source": "rebuilt contexts (scripts/run_rq4.py context()) from .eval_cache/injected_view and .eval_cache/dl/cachetools-8.0.2",
           "injector_only_identifiers_found": sorted(only), "marker_words": list(MARKERS), "cue_words": list(CUES),
           "definition": __doc__, "summary": summary, "per_test": table,
           "limitation": "A word in a context is not proof the model used it. Counts are of tests having the item, not of occurrences, unless a dict shows counts."}
    dest = REPO / "results" / "injected" / "rq4_leakage_split.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
