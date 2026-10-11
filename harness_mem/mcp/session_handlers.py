"""Read-only session inspection; no backend initialization or hidden ingest."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from harness_mem.commands.session_inventory import collect_session_inventory, read_session_page
from .handler_facade_proxy import tool_handlers_facade as _core


def tool_inspect_sessions(
    project_root: str, project_name: str | None = None, action: str = "inventory",
    clients: list[str] | None = None, session: dict | None = None,
    offset: int = 0, page_chars: int = 16000, batch_id: str | None = None,
    sessions: list[dict] | None = None, coverage: list[dict] | None = None,
    topics: list[dict] | None = None,
) -> dict:
    root = Path(project_root).expanduser()
    if not root.is_absolute() or not root.is_dir():
        return {"success": False, "error": "project_root must be an existing absolute directory"}
    name = project_name or root.resolve().name
    data_dir = Path(_core._observer_data_dir())
    try:
        if action != "overview" and any(value is not None for value in (sessions, coverage, topics)):
            raise ValueError("sessions, coverage and topics require overview action")
        if action != "source" and (session is not None or offset != 0 or page_chars != 16000):
            raise ValueError("source selection and paging require source action")
        if action != "inventory" and clients is not None:
            raise ValueError("clients only filters inventory")
        if batch_id is not None:
            if action != "inventory" or clients is not None:
                raise ValueError("batch status cannot also read a source")
            from harness_mem.commands.manual_distill import inspect_manual_batch
            return inspect_manual_batch(data_dir, project_name=name, project_root=root, batch_id=batch_id)
        if action == "inventory":
            return collect_session_inventory(data_dir, project_root=root, project_name=name, clients=clients).payload()
        if action == "source" and session is not None:
            return read_session_page(data_dir, project_root=root, project_name=name, session=session, offset=offset, page_chars=page_chars)
        if action == "overview":
            from harness_mem.commands.session_overview import build_session_overview
            return build_session_overview(data_dir, project_root=root, project_name=name,
                                          sessions=sessions or [], coverage=coverage or [], topics=topics or [])
        raise ValueError("use inventory, source with a session reference, or overview with fixed sessions")
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return {"success": False, "error": str(exc), "next_step": "Keep sources unchanged; inspect the selected scope again."}
