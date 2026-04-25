"""Lightweight local event log for harness-mem.

Tracks command usage and next-step adoption for learning loop analytics.
All logs are written to the local data directory only.
"""

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class EventType(StrEnum):
    """Event types tracked by the event log."""
    COMMAND_INVOKED = "command_invoked"
    NEXT_STEP_SHOWN = "next_step_shown"
    NEXT_STEP_ADOPTED = "next_step_adopted"
    SESSION_INGESTED = "session_ingested"
    MEMORY_DISTILLED = "memory_distilled"
    RULE_CONFIRMED = "rule_confirmed"
    RULE_REJECTED = "rule_rejected"
    LEARNING_LOOP_COMPLETE = "learning_loop_complete"


class EventLogger:
    """Append-only event log written to local data directory.

    Events are stored as newline-delimited JSON (NDJSON) in data_dir/events.log
    """

    def __init__(self, data_dir: Path):
        self._path = Path(data_dir) / "events.log"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _write_event(self, event: dict[str, Any]) -> None:
        """Append a single event to the log file (synchronous)."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    async def log(
        self,
        event_type: EventType,
        project_name: str | None = None,
        command: str | None = None,
        next_step: str | None = None,
        session_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """Log an event.

        Args:
            event_type: Type of event
            project_name: Project context (if any)
            command: CLI command invoked
            next_step: Recommended next step shown/adopted
            session_id: Session context (if any)
            extra: Additional event-specific data
        """
        async with self._lock:
            event: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type.value,
                "project_name": project_name,
                "command": command,
                "next_step": next_step,
                "session_id": session_id,
            }
            if extra:
                event["extra"] = extra
            self._write_event(event)

    def log_sync(
        self,
        event_type: EventType,
        project_name: str | None = None,
        command: str | None = None,
        next_step: str | None = None,
        session_id: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """Synchronous version of log() for use in non-async contexts."""
        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type.value,
            "project_name": project_name,
            "command": command,
            "next_step": next_step,
            "session_id": session_id,
        }
        if extra:
            event["extra"] = extra
        self._write_event(event)

    def get_stats(self, project_name: str | None = None, days: int = 30) -> dict:
        """Get event statistics.

        Args:
            project_name: Filter by project (None = all projects)
            days: Only count events from the last N days

        Returns:
            Dict with event counts by type and command adoption metrics.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        stats: dict = {
            "total_events": 0,
            "by_type": {},
            "commands_invoked": {},
            "next_step_shown": 0,
            "next_step_adopted": 0,
            "adoption_rate": 0.0,
        }

        if not self._path.exists():
            return stats

        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = event.get("timestamp", "")
                try:
                    event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if event_time.timestamp() < cutoff:
                    continue

                if project_name and event.get("project_name") != project_name:
                    continue

                stats["total_events"] += 1
                evt_type = event.get("type", "unknown")
                stats["by_type"][evt_type] = stats["by_type"].get(evt_type, 0) + 1

                cmd = event.get("command")
                if cmd:
                    stats["commands_invoked"][cmd] = stats["commands_invoked"].get(cmd, 0) + 1

                if evt_type == EventType.NEXT_STEP_SHOWN.value:
                    stats["next_step_shown"] += 1
                elif evt_type == EventType.NEXT_STEP_ADOPTED.value:
                    stats["next_step_adopted"] += 1

        if stats["next_step_shown"] > 0:
            stats["adoption_rate"] = round(
                stats["next_step_adopted"] / stats["next_step_shown"], 3
            )

        return stats


# Global logger instance (initialized lazily)
_event_logger: EventLogger | None = None


def get_event_logger(data_dir: Path | None = None) -> EventLogger:
    """Get or create the global event logger."""
    global _event_logger
    from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR

    resolved_data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    if _event_logger is None or _event_logger._path.parent != resolved_data_dir:
        _event_logger = EventLogger(resolved_data_dir)
    return _event_logger
