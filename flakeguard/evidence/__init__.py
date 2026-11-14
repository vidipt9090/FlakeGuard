"""flakeguard.evidence package: bisection, interventions, AST read/write mapping, and evidence reporting."""

from flakeguard.evidence.bisection import BisectionResult, bisect_polluter
from flakeguard.evidence.engine import EvidenceEngine
from flakeguard.evidence.interventions import InterventionEngine
from flakeguard.evidence.read_write_map import (
    AccessMap,
    extract_test_access_map,
    find_shared_state_overlap,
)
from flakeguard.evidence.template import EvidenceBundle, EvidenceSnippet, build_evidence_bundle

__all__ = [
    "AccessMap",
    "BisectionResult",
    "EvidenceBundle",
    "EvidenceEngine",
    "EvidenceSnippet",
    "InterventionEngine",
    "bisect_polluter",
    "build_evidence_bundle",
    "extract_test_access_map",
    "find_shared_state_overlap",
]
