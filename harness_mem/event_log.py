"""Lightweight local event log for harness-mem.

Tracks command usage and next-step adoption for learning loop analytics.
All logs are written to the local data directory only.
"""

from __future__ import annotations
import json
import asyncio
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator


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
    MCP_SURFACE_COST = "mcp_surface_cost"


class StateEventType(StrEnum):
    """Review/governance state changes recorded for audit/replay."""

    CANDIDATE_CREATED = "candidate_created"
    CANDIDATE_REVIEWED = "candidate_reviewed"
    TRUTH_CONFIRMED = "truth_confirmed"
    TRUTH_REJECTED = "truth_rejected"
    SUPERSEDE_COMPLETED = "supersede_completed"


STATE_EVENTS_FILE = "state-events.log"


def _state_event_path(data_dir: Path, *, create_parent: bool = False) -> Path:
    path = Path(data_dir) / STATE_EVENTS_FILE
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_state_event(
    data_dir: Path,
    *,
    event_type: StateEventType | str,
    project_name: str | None,
    target_kind: str,
    target_id: str,
    status: str | None = None,
    source_surface: str | None = None,
    actor: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Append one governance state event to the local audit ledger.

    This ledger is separate from command telemetry because it describes durable
    memory governance transitions that should be inspectable and replayable.
    """

    event_id = f"state-{uuid.uuid4().hex[:12]}"
    event = {
        "id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": str(event_type.value if isinstance(event_type, StateEventType) else event_type),
        "project_name": project_name,
        "target_kind": target_kind,
        "target_id": target_id,
        "status": status,
        "source_surface": source_surface,
        "actor": actor,
        "payload": payload or {},
    }
    with open(_state_event_path(data_dir, create_parent=True), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, sort_keys=True) + "\n")
    return event_id


def iter_state_events(
    data_dir: Path,
    *,
    project_name: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    event_type: StateEventType | str | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate state audit events in append order, skipping corrupt lines."""

    path = _state_event_path(data_dir)
    if not path.exists():
        return
    expected_type = (
        event_type.value if isinstance(event_type, StateEventType) else event_type
    )
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project_name is not None and event.get("project_name") != project_name:
                continue
            if target_kind is not None and event.get("target_kind") != target_kind:
                continue
            if target_id is not None and event.get("target_id") != target_id:
                continue
            if expected_type is not None and event.get("type") != expected_type:
                continue
            yield event


def state_audit_summary(data_dir: Path, *, project_name: str | None = None) -> dict[str, Any]:
    """Return simple counts for the state audit ledger."""

    by_type: dict[str, int] = {}
    by_target_kind: dict[str, int] = {}
    total = 0
    last_event_at = None
    for event in iter_state_events(data_dir, project_name=project_name):
        total += 1
        evt_type = str(event.get("type") or "unknown")
        kind = str(event.get("target_kind") or "unknown")
        by_type[evt_type] = by_type.get(evt_type, 0) + 1
        by_target_kind[kind] = by_target_kind.get(kind, 0) + 1
        last_event_at = event.get("timestamp") or last_event_at
    return {
        "event_count": total,
        "project_name": project_name,
        "by_type": by_type,
        "by_target_kind": by_target_kind,
        "last_event_at": last_event_at,
        "ledger": str(_state_event_path(data_dir)),
    }


def replay_state_events(
    data_dir: Path,
    *,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Replay the governance ledger into latest target states.

    This is intentionally conservative: it does not mutate storage or claim to
    rebuild source blobs. It proves that the append-only state ledger can be
    replayed into an auditable latest-state projection.
    """

    targets: dict[str, dict[str, Any]] = {}
    event_count = 0
    for event in iter_state_events(data_dir, project_name=project_name):
        event_count += 1
        target_kind = str(event.get("target_kind") or "unknown")
        target_id = str(event.get("target_id") or "")
        if not target_id:
            continue
        key = f"{target_kind}:{target_id}"
        prior = targets.get(key, {})
        history = [*prior.get("event_ids", []), event.get("id")]
        targets[key] = {
            "target_kind": target_kind,
            "target_id": target_id,
            "project_name": event.get("project_name"),
            "latest_type": event.get("type"),
            "latest_status": event.get("status"),
            "latest_event_at": event.get("timestamp"),
            "latest_source_surface": event.get("source_surface"),
            "event_ids": history,
        }
    return {
        "schema_version": "harness_mem.state_event_replay.v1",
        "project_name": project_name,
        "event_count": event_count,
        "target_count": len(targets),
        "targets": targets,
    }


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
