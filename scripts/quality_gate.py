"""The quality gate: the point where testing stops and delivery begins.

A test suite answers "did the code run?". This answers "is this build good
enough to ship?", which is a different and higher bar, and it is the step that
turns a CI pipeline into a CI/CD pipeline: nothing downstream of the gate --
no report, no Pages deploy, no release -- runs unless every check here passes.

Each check names the artifact it reads, the threshold, and why the threshold
is where it is. Thresholds sit *below* the numbers we actually measure, with
headroom, so the gate catches a regression rather than fencing in the current
result. Where a number is already at its ceiling the gate holds the floor it
has to clear, not the ceiling.

Run locally exactly as CI runs it:

    python scripts/quality_gate.py
    python scripts/quality_gate.py --strict      # warnings fail too

Writes ``results/pipeline_status.json`` (which the dashboard reads) and, when
``GITHUB_STEP_SUMMARY`` is set, a markdown table into the job summary.
Exit code 0 means promote, 1 means stop.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS = REPO_ROOT / "results"

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"


def show(value: float, unit: str = "") -> str:
    """Format a measurement so a rate still reads as a rate.

    ``%g`` turns a false-quarantine rate of 1.0 into "1", which reads as a
    count of one rather than "every single one". Anything on a 0-1 scale
    keeps its decimals; counts stay integers.
    """
    if unit:
        return f"{value:g}{unit}"
    if value == int(value) and abs(value) > 1.0:
        return f"{int(value)}"
    return f"{value:.2f}"


@dataclass
class Check:
    """One gate condition and what it found."""

    name: str
    stage: str
    status: str
    detail: str
    why: str
    measured: float | None = None
    threshold: float | None = None
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Gate:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    def at_least(
        self,
        name: str,
        stage: str,
        measured: float | None,
        threshold: float,
        why: str,
        source: str,
        unit: str = "",
        required: bool = True,
    ) -> Check:
        """Fail when ``measured`` is below ``threshold``, or missing."""
        if measured is None:
            return self.add(
                Check(
                    name=name,
                    stage=stage,
                    status=FAIL if required else SKIP,
                    detail=f"not found in {source}",
                    why=why,
                    threshold=threshold,
                    source=source,
                )
            )
        ok = measured >= threshold
        return self.add(
            Check(
                name=name,
                stage=stage,
                status=PASS if ok else (FAIL if required else WARN),
                detail=f"{show(measured, unit)} (needs >= {show(threshold, unit)})",
                why=why,
                measured=measured,
                threshold=threshold,
                source=source,
            )
        )

    def at_most(
        self,
        name: str,
        stage: str,
        measured: float | None,
        threshold: float,
        why: str,
        source: str,
        unit: str = "",
        required: bool = True,
    ) -> Check:
        if measured is None:
            return self.add(
                Check(
                    name=name,
                    stage=stage,
                    status=FAIL if required else SKIP,
                    detail=f"not found in {source}",
                    why=why,
                    threshold=threshold,
                    source=source,
                )
            )
        ok = measured <= threshold
        return self.add(
            Check(
                name=name,
                stage=stage,
                status=PASS if ok else (FAIL if required else WARN),
                detail=f"{show(measured, unit)} (needs <= {show(threshold, unit)})",
                why=why,
                measured=measured,
                threshold=threshold,
                source=source,
            )
        )

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]


# --------------------------------------------------------------- artifacts


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_csv(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def git_sha() -> str:
    for env in ("GITHUB_SHA", "GIT_COMMIT"):
        if os.environ.get(env):
            return os.environ[env][:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ------------------------------------------------------------------- checks


def run_checks(gate: Gate) -> None:
    # --- stage: navigate -------------------------------------------------
    # Does the navigator still reach code from a failing test id? This is the
    # check that would have caught the jedi-version drift we hit locally: a
    # navigator that resolves nothing produces an empty evidence bundle, and
    # every downstream number stays green while meaning nothing.
    nav = read_json(RESULTS / "nav_trace_summary.json")
    source = "results/nav_trace_summary.json"
    if nav is None:
        gate.add(
            Check(
                name="navigator export present",
                stage="navigate",
                status=FAIL,
                detail=f"{source} missing — run scripts/export_knowledge_trees.py",
                why="nothing downstream can be trusted without it",
                source=source,
            )
        )
    else:
        gate.at_least(
            "navigator resolves its cases",
            "navigate",
            as_float(nav.get("resolution_rate")),
            0.95,
            "measured 1.00 on all 31 planted cases; below 0.95 means test ids "
            "stopped resolving, which silently empties the evidence bundle",
            source,
        )
        gate.at_least(
            "jedi hit rate",
            "navigate",
            as_float(nav.get("jedi_hit_rate")),
            0.80,
            "measured 1.00 synthetic / 0.90 on cachetools; a collapse here means "
            "the environment changed under us (jedi version, missing package)",
            source,
        )
        gate.at_least(
            "mean knowledge tree size",
            "navigate",
            as_float(nav.get("mean_tree_nodes")),
            3.0,
            "measured 12.4 nodes; a tree of one node is a test with no context",
            source,
            unit=" nodes",
        )
        gate.at_least(
            "trees reaching hop 2",
            "navigate",
            as_float(nav.get("trees_with_depth_2plus")),
            1.0,
            "a bare floor, and deliberately not more: the synthetic benchmark "
            "is a flat module, so only one of its trees has a second hop at "
            "all. The real guard on the expansion pass is the external check "
            "below, where all 10 cachetools trees reach hop 2",
            source,
        )
        gate.at_most(
            "navigation latency",
            "navigate",
            as_float(nav.get("max_ms")),
            5000.0,
            "measured max 1.0 s on synthetic, 1.6 s on cachetools; a live demo "
            "cannot afford more than a few seconds per test",
            source,
            unit=" ms",
        )

    # --- stage: generalise -----------------------------------------------
    # The navigator was tuned on cachetools, so scoring it there measures fit.
    # What these checks defend is the *mechanism*: cachetools' API is its class
    # hierarchy and its operators, so if `jedi.infer` or the expansion hop
    # breaks, this set collapses while the synthetic set above stays green.
    # Absent is a warning, not a failure: the external checkout is a separate
    # pipeline stage and may legitimately not have run locally.
    external = read_json(RESULTS / "cachetools" / "nav_trace_summary.json")
    source = "results/cachetools/nav_trace_summary.json"
    if external is None:
        gate.add(
            Check(
                name="external repo navigated",
                stage="generalise",
                status=WARN,
                detail=f"{source} missing — the navigate-external stage did not run",
                why="a navigator scored only on its own fixtures proves nothing; "
                "run the export against ../cachetools",
                source=source,
            )
        )
    else:
        gate.at_least(
            "external resolution rate",
            "generalise",
            as_float(external.get("resolution_rate")),
            0.90,
            "10/10 gold cases resolve on cachetools at the pinned SHA",
            source,
        )
        gate.at_least(
            "external jedi hit rate",
            "generalise",
            as_float(external.get("jedi_hit_rate")),
            0.75,
            "measured 0.90. Lower than synthetic because a container library "
            "resolves a lot of stdlib; a collapse means jedi.infer broke",
            source,
        )
        gate.at_least(
            "external trees reach a second hop",
            "generalise",
            as_float(external.get("trees_with_depth_2plus")),
            8.0,
            "all 10 reach hop 2 today. cachetools' API *is* its class "
            "hierarchy, so this is the check that the expansion hop still "
            "works -- the synthetic set is too flat to notice",
            source,
            unit=" trees",
        )

    # --- stage: evaluate -------------------------------------------------
    # The research question: can the LLM name the root cause well enough to
    # be worth shipping? 0.70 is the target written into the charter.
    llm = read_csv(RESULTS / "llm_metrics.csv")
    source = "results/llm_metrics.csv"
    if not llm:
        gate.add(
            Check(
                name="prompt evaluation present",
                stage="evaluate",
                status=WARN,
                detail=f"{source} missing",
                why="the eval harness needs a local Ollama, so CI may not have run it",
                source=source,
            )
        )
    else:
        best = max(llm, key=lambda row: as_float(row.get("f1")) or 0.0)
        gate.at_least(
            "best prompt F1",
            "evaluate",
            as_float(best.get("f1")),
            0.70,
            f"the charter's target. Best recorded is {best.get('prompt_version')} "
            f"at F1 {best.get('f1')}",
            source,
        )
        gate.at_most(
            "JSON parse failures (best prompt)",
            "evaluate",
            as_float(best.get("parse_failures")),
            0.0,
            "v3 parses cleanly on all 31 cases; any parse failure means the "
            "schema contract with the model broke",
            source,
        )
        # This one is a warning rather than a block, and the reason is a frozen
        # project decision, not convenience: v1 never quarantines on its own --
        # a person approves every quarantine. So a false-quarantine *rate* is a
        # model-quality signal, not a shipped risk. It is a bad signal: at 1.0
        # the best prompt calls all six real bugs flaky, which is the direct
        # cost of its recall being 1.0. It must stay visible, and `--strict`
        # does block on it, so the number cannot quietly become normal.
        gate.at_most(
            "false quarantine rate",
            "evaluate",
            as_float(best.get("false_quarantine_rate")),
            0.10,
            "a real failure called flaky hides a real bug. Does not block "
            "delivery because a human approves every quarantine (frozen "
            "decision), but at 1.0 the prompt mislabels every real bug and "
            "cannot be trusted unattended",
            source,
            required=False,
        )

    baselines = read_csv(RESULTS / "baseline_metrics.csv")
    source = "results/baseline_metrics.csv"
    if not baselines:
        gate.add(
            Check(
                name="baseline present",
                stage="evaluate",
                status=FAIL,
                detail=f"{source} missing",
                why="a result without a baseline is not a result",
                source=source,
            )
        )
    else:
        best_baseline = max(baselines, key=lambda row: as_float(row.get("f1")) or 0.0)
        best_llm_f1 = (
            max((as_float(row.get("f1")) or 0.0) for row in llm) if llm else None
        )
        baseline_f1 = as_float(best_baseline.get("f1")) or 0.0
        if best_llm_f1 is None:
            gate.add(
                Check(
                    name="LLM beats the baseline",
                    stage="evaluate",
                    status=SKIP,
                    detail="no LLM metrics to compare",
                    why="the comparison is the whole claim",
                    source=source,
                )
            )
        else:
            gate.add(
                Check(
                    name="LLM beats the baseline",
                    stage="evaluate",
                    status=PASS if best_llm_f1 > baseline_f1 else FAIL,
                    detail=(
                        f"LLM F1 {best_llm_f1:.3f} vs rerun baseline {baseline_f1:.3f}"
                    ),
                    why="if the rerun baseline wins, the LLM is not earning its cost",
                    measured=best_llm_f1,
                    threshold=baseline_f1,
                    source=source,
                )
            )

    # --- stage: data -----------------------------------------------------
    nav_csv = read_csv(RESULTS / "navigation.csv")
    source = "results/navigation.csv"
    if nav_csv:
        resolved = sum(1 for row in nav_csv if row.get("success") == "1")
        gate.at_least(
            "navigation success on planted cases",
            "data",
            resolved / len(nav_csv),
            0.95,
            f"{resolved}/{len(nav_csv)} cases resolve today",
            source,
        )

    labels = read_json(REPO_ROOT / "labels" / "labels.json")
    source = "labels/labels.json"
    if isinstance(labels, list):
        gate.at_least(
            "benchmark size",
            "data",
            float(len(labels)),
            31.0,
            "the benchmark is 31 neutralised cases; shrinking it quietly would "
            "make every rate above look better than it is",
            source,
            unit=" cases",
        )
        causes = {item.get("root_cause") for item in labels} - {None, ""}
        gate.at_least(
            "root-cause coverage",
            "data",
            float(len(causes)),
            5.0,
            "five planted root-cause families plus 'none'; fewer means a whole "
            "failure class left the benchmark",
            source,
            unit=" causes",
        )


# -------------------------------------------------------------- reporting


SYMBOL = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN", SKIP: "SKIP"}
MARK = {PASS: "✅", FAIL: "❌", WARN: "⚠️", SKIP: "⏭️"}


def print_report(gate: Gate) -> None:
    width = max(len(c.name) for c in gate.checks) + 2
    stage = None
    for check in gate.checks:
        if check.stage != stage:
            stage = check.stage
            print(f"\n  [{stage}]")
        print(f"    {SYMBOL[check.status]}  {check.name:<{width}} {check.detail}")
        if check.status in {FAIL, WARN}:
            print(f"          why: {check.why}")


def write_step_summary(gate: Gate, promote: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Quality gate",
        "",
        f"**{'PROMOTE' if promote else 'BLOCKED'}** — "
        f"{sum(1 for c in gate.checks if c.status == PASS)} passed, "
        f"{len(gate.failed)} failed, {len(gate.warned)} warned.",
        "",
        "| | Check | Stage | Result | Threshold |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in gate.checks:
        lines.append(
            f"| {MARK[check.status]} | {check.name} | {check.stage} | "
            f"{check.detail} | {check.why} |"
        )
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as failures too"
    )
    parser.add_argument(
        "--out",
        default=str(RESULTS / "pipeline_status.json"),
        help="where to write the machine-readable status",
    )
    args = parser.parse_args(argv)

    gate = Gate()
    run_checks(gate)

    promote = not gate.failed and (not args.strict or not gate.warned)

    print("=" * 78)
    print("  FlakeGuard quality gate — the testing/delivery boundary")
    print("=" * 78)
    print_report(gate)
    print("\n" + "=" * 78)
    passed = sum(1 for c in gate.checks if c.status == PASS)
    print(
        f"  {passed} passed · {len(gate.failed)} failed · "
        f"{len(gate.warned)} warned · "
        f"{sum(1 for c in gate.checks if c.status == SKIP)} skipped"
    )
    print(f"  VERDICT: {'PROMOTE' if promote else 'BLOCKED'}")
    print("=" * 78)
    if gate.failed:
        print("\n  Delivery stopped by:")
        for check in gate.failed:
            print(f"    - {check.name}: {check.detail}")

    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": git_sha(),
        "branch": os.environ.get("GITHUB_REF_NAME", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER", ""),
        "workflow": os.environ.get("GITHUB_WORKFLOW", "local"),
        "actor": os.environ.get("GITHUB_ACTOR", ""),
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "strict": args.strict,
        "promote": promote,
        "verdict": "promote" if promote else "blocked",
        "counts": {
            "pass": passed,
            "fail": len(gate.failed),
            "warn": len(gate.warned),
            "skip": sum(1 for c in gate.checks if c.status == SKIP),
        },
        "checks": [check.to_dict() for check in gate.checks],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"\n  status -> {out_path}")

    write_step_summary(gate, promote)
    return 0 if promote else 1


if __name__ == "__main__":
    raise SystemExit(main())
