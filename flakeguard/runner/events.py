"""FlakeGuard Event Schema and JSONL Event Logger.

The JSONL event log (data/events/<run_id>.jsonl) is the single source of truth
for downstream consumers (PR comments, evidence engine, frontend dashboard).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field

Stage = Literal[
    "ingest",
    "discover",
    "run",
    "evidence",
    "stats",
    "llm",
    "generate",
    "report",
]

EventType = Literal[
    "started",
    "progress",
    "result",
    "error",
]


class Event(BaseModel):
    """Single event item in the event log (contract schema)."""

    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 UTC timestamp",
    )
    run_id: str
    stage: Stage
    type: EventType
    test_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class EventLogger:
    """Manages appending and reading events from a run's JSONL log file."""

    def __init__(self, run_id: str, output_path: str | Path | None = None) -> None:
        self.run_id = run_id
        if output_path is not None:
            self.path = Path(output_path)
        else:
            self.path = Path("data") / "events" / f"{run_id}.jsonl"

        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Touch file if missing
        if not self.path.exists():
            self.path.touch()

    def log(
        self,
        stage: Stage,
        event_type: EventType,
        test_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Event:
        """Create and write an event line, flushing immediately for streaming readers."""
        event = Event(
            run_id=self.run_id,
            stage=stage,
            type=event_type,
            test_id=test_id,
            data=data or {},
        )
        line = event.model_dump_json() + "\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
        return event

    def read_events(self) -> Iterator[Event]:
        """Iterate over all recorded events in this run's log."""
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    yield Event.model_validate_json(stripped)
