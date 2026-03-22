"""
shared/timeline.py — Pipeline Timeline Tracker

HOW IT WORKS:
─────────────
Records every step the pipeline executes, in chronological order.
Each entry captures: step number, event type, summary, timestamp, and duration.

The final timeline.json is saved to S3 at:
    events/<repo-slug>/<event-id>/timeline.json

WHY:
    - Full audit trail of what happened and when
    - Debug tool: see exactly where the pipeline stalled or failed
    - Analytics: measure step durations over time

USAGE:
    from shared.timeline import Timeline

    tl = Timeline(event_id="evt-...")
    tl.record(step=1, event_type="webhook_received", summary="Got workflow_run failure")
    tl.record(step=2, event_type="logs_downloaded", summary="512KB logs fetched")
    tl.to_dict()  →  [{"step": 1, ...}, {"step": 2, ...}]

COMMUNICATION:
─────────────
Step 2 (worker) creates a Timeline instance.
Each sub-step (log fetch, triage, plan, policy, PR) records into it.
At the end, worker serializes it and uploads to S3.
"""

import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class TimelineEntry:
    """A single step in the pipeline timeline."""
    step: int
    event_type: str
    summary: str
    timestamp: str = ""
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "step": self.step,
            "type": self.event_type,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class Timeline:
    """
    Collects timeline entries for one pipeline execution.

    Thread-safe for sequential pipeline steps.
    Not designed for concurrent writes (pipeline is sequential).
    """

    def __init__(self, event_id: str):
        self.event_id = event_id
        self._entries: List[TimelineEntry] = []
        self._step_timers: Dict[int, float] = {}

    def start_step(self, step: int) -> None:
        """Begin timing a step. Call before the step executes."""
        self._step_timers[step] = time.monotonic()

    def record(
        self,
        step: int,
        event_type: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a completed step.

        If start_step() was called for this step number,
        the duration is automatically calculated.
        """
        duration_ms = None
        if step in self._step_timers:
            elapsed = time.monotonic() - self._step_timers.pop(step)
            duration_ms = round(elapsed * 1000, 2)

        entry = TimelineEntry(
            step=step,
            event_type=event_type,
            summary=summary,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
        self._entries.append(entry)

    def record_error(
        self,
        step: int,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Shorthand for recording an error at a step."""
        self.record(
            step=step,
            event_type="error",
            summary=error,
            metadata=metadata,
        )

    def to_dict(self) -> List[Dict[str, Any]]:
        """Serialize all entries to a list of dicts (for JSON)."""
        return [entry.to_dict() for entry in self._entries]

    def __len__(self) -> int:
        return len(self._entries)
