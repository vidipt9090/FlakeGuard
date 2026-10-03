"""Score the navigator against the hand-written gold set (work package B3).

    python -m flakeguard.navigator.evaluate --repo ../cachetools \
        --gold docs/eval1/nav-gold.json

Three numbers, all over code-under-test chunks:

  precision  of what the navigator returned, how much was right
  recall     of what it should have found, how much it found
  top-3      share of tests where at least one correct definition is in the
             first three results. This is the one that matters in practice:
             the evidence bundle C builds only has room for a few chunks.

A predicted chunk matches a gold entry when the path is equal and the gold
start line falls inside the predicted span. Spans are compared loosely on
purpose: jedi and ast disagree by a line on where a class body ends, and a
navigator that finds the right function should not be marked wrong for that.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from flakeguard.contracts import Chunk
from flakeguard.navigator.ast_nav import AstNavigator

TOP_K = 3


@dataclass
class Score:
    test_id: str
    tp: int
    fp: int
    fn: int
    hit_at_k: bool
    missed: list[str]
    spurious: list[str]
    smells_found: list[str]
    smells_expected: list[str]

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0


def matches(chunk: Chunk, gold: dict) -> bool:
    return chunk.path == gold["path"] and chunk.start_line <= gold["start_line"] <= chunk.end_line


def score_one(nav: AstNavigator, case: dict) -> Score:
    result = nav.related(case["test_id"])
    predicted = result.code_under_test
    gold = case["code_under_test"]

    matched_gold: set[int] = set()
    matched_pred: set[int] = set()
    for gi, g in enumerate(gold):
        for pi, p in enumerate(predicted):
            if matches(p, g):
                matched_gold.add(gi)
                matched_pred.add(pi)

    hit_at_k = any(
        matches(p, g) for p in predicted[:TOP_K] for g in gold
    )

    return Score(
        test_id=case["test_id"],
        tp=len(matched_gold),
        fp=len(predicted) - len(matched_pred),
        fn=len(gold) - len(matched_gold),
        hit_at_k=hit_at_k,
        missed=[g["name"] for gi, g in enumerate(gold) if gi not in matched_gold],
        spurious=[
            f"{p.path}:{p.start_line}"
            for pi, p in enumerate(predicted)
            if pi not in matched_pred
        ],
        smells_found=result.smells,
        smells_expected=case.get("expected_smells", []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m flakeguard.navigator.evaluate")
    parser.add_argument("--repo", required=True, help="path to the target checkout")
    parser.add_argument("--gold", default="docs/eval1/nav-gold.json")
    parser.add_argument("--markdown", action="store_true", help="emit a markdown table")
    args = parser.parse_args(argv)

    spec = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    nav = AstNavigator(args.repo, repo=spec["repo"], sha=spec["sha"][:7])
    scores = [score_one(nav, case) for case in spec["tests"]]

    tp = sum(s.tp for s in scores)
    fp = sum(s.fp for s in scores)
    fn = sum(s.fn for s in scores)
    micro_p = tp / (tp + fp) if (tp + fp) else 0.0
    micro_r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) else 0.0
    top_k = sum(s.hit_at_k for s in scores) / len(scores)

    if args.markdown:
        print("| test | TP | FP | FN | precision | recall | correct in top 3 |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for s in scores:
            short = s.test_id.split("::", 1)[-1]
            mark = "yes" if s.hit_at_k else "no"
            print(
                f"| `{short}` | {s.tp} | {s.fp} | {s.fn} | "
                f"{s.precision:.2f} | {s.recall:.2f} | {mark} |"
            )
        print(
            f"| **overall ({len(scores)} tests)** | {tp} | {fp} | {fn} | "
            f"**{micro_p:.2f}** | **{micro_r:.2f}** | **{top_k:.0%}** |"
        )
    else:
        for s in scores:
            print(f"{s.test_id}")
            print(
                f"   tp={s.tp} fp={s.fp} fn={s.fn} "
                f"p={s.precision:.2f} r={s.recall:.2f} top{TOP_K}={'Y' if s.hit_at_k else 'N'}"
            )
            if s.missed:
                print(f"   missed:   {', '.join(s.missed)}")
            if s.spurious:
                print(f"   spurious: {', '.join(s.spurious)}")
            if set(s.smells_expected) - set(s.smells_found):
                print(f"   smells missed: {sorted(set(s.smells_expected) - set(s.smells_found))}")
        print(
            f"\nmicro precision {micro_p:.3f}  recall {micro_r:.3f}  "
            f"f1 {f1:.3f}  correct-in-top-{TOP_K} {top_k:.1%}  ({len(scores)} tests)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
