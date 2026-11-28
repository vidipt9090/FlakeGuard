"""FlakeGuard Event Schema, Logger, and Streaming Event Append.

The JSONL event log (data/events/<run_id>.jsonl) is the single source of truth
for downstream consumers (PR comments, evidence engine, frontend dashboard).
"""

from __future__ import annotations

from typing import Any

from flakeguard.runner.events import Event, EventLogger, EventType, Stage


def append_event(
    run_id: str,
    stage: Stage,
    event_type: EventType,
    data: dict[str, Any] | None = None,
    test_id: str | None = None,
    output_path: str | None = None,
) -> Event:
    """Append a validated event to the single-source-of-truth JSONL event log."""
    logger = EventLogger(run_id=run_id, output_path=output_path)
    return logger.log(stage=stage, event_type=event_type, test_id=test_id, data=data)


__all__ = ["Event", "EventLogger", "Stage", "EventType", "append_event"]

