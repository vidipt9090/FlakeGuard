from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceSnippet:
    evidence_id: str
    title: str
    kind: str  # "code_under_test" | "fixture" | "shared_state" | "log" | "test_body"
    content: str


@dataclass
class EvidenceBundle:
    test_id: str
    run_stats: dict[str, Any]
    log_excerpt: str
    test_body: str
    snippets: list[EvidenceSnippet] = field(default_factory=list)

    def render(self) -> str:
        """Render the complete evidence bundle as text for LLM consumption."""
        lines = [
            f"=== EVIDENCE BUNDLE FOR TEST: {self.test_id} ===",
            "",
            "--- 1. RUN STATISTICS ---",
            f"Total Runs: {self.run_stats.get('total_runs', 20)}",
            f"Pass Rate: {self.run_stats.get('pass_rate', '50%')}",
            f"Fail Rate: {self.run_stats.get('fail_rate', '50%')}",
            f"Failing Seeds / Orders: {self.run_stats.get('failing_seeds', 'Seed 1, Seed 3, Seed 7')}",
            "",
            "--- 2. LOG EXCERPT ---",
            self.log_excerpt.strip(),
            "",
            "--- 3. TEST BODY ---",
            self.test_body.strip(),
            "",
            "--- 4. CODE & CONTEXT SNIPPETS ---",
        ]

        for snip in self.snippets:
            lines.extend(
                [
                    f"[{snip.evidence_id}] ({snip.kind.upper()}: {snip.title})",
                    "```python",
                    snip.content.strip(),
                    "```",
                    "",
                ]
            )

        return "\n".join(lines)


def build_evidence_bundle(
    test_id: str,
    run_stats: dict[str, Any],
    log_excerpt: str,
    test_body: str,
    snippets: list[EvidenceSnippet],
) -> str:
    """Build and render an evidence bundle string."""
    bundle = EvidenceBundle(
        test_id=test_id,
        run_stats=run_stats,
        log_excerpt=log_excerpt,
        test_body=test_body,
        snippets=snippets,
    )
    return bundle.render()
