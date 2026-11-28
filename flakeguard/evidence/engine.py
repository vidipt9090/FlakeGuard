"""Unified evidence engine executing bisection, interventions, and static read/write mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flakeguard.contracts import EvidenceReport, EvidenceTier, InterventionRecord
from flakeguard.evidence.bisection import BisectionResult, bisect_polluter
from flakeguard.evidence.interventions import InterventionEngine
from flakeguard.evidence.read_write_map import extract_test_access_map, find_shared_state_overlap
from flakeguard.runner.events import EventLogger
from flakeguard.runner.sandbox import Sandbox


class EvidenceEngine:
    """Coordinates bisection, interventions, and static analysis to generate tiered EvidenceReports."""

    def __init__(
        self,
        repo_path: Path,
        sandbox: Sandbox | None = None,
        event_logger: EventLogger | None = None,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.sandbox = sandbox
        self.event_logger = event_logger
        self.intervention_engine = InterventionEngine(sandbox=sandbox)

    def diagnose_test(
        self,
        test_id: str,
        base_outcome: str = "PASS",
        execution_order: list[str] | None = None,
        observed_slices: list[str] | None = None,
        category_hint: str | None = None,
        timeout: float = 30.0,
    ) -> EvidenceReport:
        """Run full evidence pipeline on a suspect flaky test to produce an EvidenceReport."""
        if self.event_logger:
            self.event_logger.log(
                stage="evidence",
                event_type="started",
                test_id=test_id,
                data={
                    "base_outcome": base_outcome,
                    "observed_slices": observed_slices or [],
                    "category_hint": category_hint,
                },
            )

        tier = EvidenceTier.OBSERVED
        category = category_hint or "unknown"
        polluter_id: str | None = None
        interventions: list[InterventionRecord] = []
        shared_reads: list[str] = []
        shared_writes: list[str] = []
        details: dict[str, Any] = {}

        # 1. Parse AST access map for victim test
        test_file_str, _, test_name = test_id.partition("::")
        victim_file = self.repo_path / test_file_str
        victim_access = extract_test_access_map(victim_file, test_name, repo_root=self.repo_path)
        shared_reads = sorted(victim_access.reads)
        shared_writes = sorted(victim_access.writes)

        # 2. Polluter bisection for order-dependent failures
        bisection_res: BisectionResult | None = None
        if execution_order and len(execution_order) > 1:
            try:
                bisection_res = bisect_polluter(
                    repo_path=self.repo_path,
                    victim_id=test_id,
                    execution_order=execution_order,
                    sandbox=self.sandbox,
                    timeout=timeout,
                )
                if bisection_res.reproduced:
                    tier = EvidenceTier.REPRODUCED
                    if bisection_res.relationship == "polluter":
                        polluter_id = bisection_res.polluter_id
                        category = "order_dependent"
                        # Extract static overlap between polluter and victim
                        if polluter_id:
                            p_file_str, _, p_name = polluter_id.partition("::")
                            p_file = self.repo_path / p_file_str
                            p_access = extract_test_access_map(p_file, p_name, repo_root=self.repo_path)
                            overlap, env_overlap = find_shared_state_overlap(p_access, victim_access)
                            if overlap:
                                category = "shared_state"
                                details["shared_state_overlap"] = sorted(overlap)
                            if env_overlap:
                                details["env_overlap"] = sorted(env_overlap)
                    elif bisection_res.relationship == "setter":
                        category = "order_dependent"
                        details["state_setter_id"] = bisection_res.setter_id
                    details["minimal_reproducer"] = bisection_res.minimal_reproducer
            except Exception as e:
                details["bisection_error"] = str(e)

        # 3. Interventions
        # If not order-dependent, or if we want to confirm timing, clock, or seed effects
        if not (bisection_res and bisection_res.reproduced):
            try:
                interventions = self.intervention_engine.run_all(
                    repo_path=self.repo_path,
                    test_id=test_id,
                    base_outcome=base_outcome,
                    category_hint=category_hint,
                    timeout=timeout,
                )
                confirmed_rec = next((r for r in interventions if r.flipped), None)
                if confirmed_rec:
                    tier = EvidenceTier.INTERVENTION_CONFIRMED
                    if confirmed_rec.kind == "pin_seed":
                        category = "randomness"
                    elif confirmed_rec.kind in ("freeze_clock", "vary_tz"):
                        category = "time_tz"
                    elif confirmed_rec.kind == "add_delay":
                        category = "timing"
                    details["confirmed_intervention"] = confirmed_rec.kind
                    details["confirmation_details"] = confirmed_rec.details
            except Exception as e:
                details["interventions_error"] = str(e)

        report = EvidenceReport(
            test_id=test_id,
            tier=tier,
            category=category,
            polluter_test_id=polluter_id,
            interventions=interventions,
            shared_state_reads=shared_reads,
            shared_state_writes=shared_writes,
            details=details,
        )

        if self.event_logger:
            self.event_logger.log(
                stage="evidence",
                event_type="result",
                test_id=test_id,
                data={
                    "tier": report.tier.value,
                    "category": report.category,
                    "polluter_test_id": report.polluter_test_id,
                    "interventions_count": len(report.interventions),
                    "details": report.details,
                },
            )

        return report

