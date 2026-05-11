"""session-distill vendored parser — shared session parsing utilities.

**Derived from:** ``harness_mem/adapters/parser.py``
**Last synced:** 2026-04-27

This is a vendored subset of the canonical parser in the ``harness-mem``
package.  It includes only the functions needed by ``session-distill``:

- :func:`parse_claude_jsonl_session` — parse Claude Code ``.jsonl`` files
- :func:`list_session_files` — scan a directory for session files
- :func:`session_sort_key` — sort sessions by modification time
- :func:`select_turns_for_packet` — reduce long sessions to head + tail

When updating this file, sync changes back to
``harness_mem/adapters/parser.py`` and update the ``Last synced`` date.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Turn = dict[str, Any]
"""A single conversational turn: ``{"user": str, "assistant": list[str], "tools": list[dict]}``."""

# ---------------------------------------------------------------------------
# Claude Code .jsonl parser
# ---------------------------------------------------------------------------

def parse_claude_jsonl_session(
    session_path: Path,
    *,
    max_user_chars: int = 2000,
    max_assistant_chars: int = 1000,
    max_tool_input_chars: int = 300,
    filter_xml_directives: bool = False,
    on_error: str = "silent",
) -> list[Turn]:
    """Parse a Claude Code ``.jsonl`` session file into a list of turns.

    Parameters
    ----------
    session_path:
        Path to the ``.jsonl`` file.
    max_user_chars:
        Maximum characters to keep for each user message.
    max_assistant_chars:
        Maximum characters to keep for each assistant text block.
    max_tool_input_chars:
        Maximum characters to keep for tool-use ``input`` serialisation.
    filter_xml_directives:
        If ``True``, skip user messages whose content starts with ``<``
        (heuristic used by ``session-distill`` to skip XML/system directives).
    on_error:
        How to handle top-level parse errors:

        - ``"silent"`` — suppress the exception, return whatever was parsed
        - ``"warn"`` — print a warning to stderr
        - ``"raise"`` — let the exception propagate

    Returns
    -------
    list[Turn]
        Each turn is a dict with keys ``user``, ``assistant``, ``tools``.
        Returns an empty list when the file is empty or unparseable
        (unless ``on_error="raise"``).
    """
    turns: list[Turn] = []
    current_turn: Turn | None = None

    try:
        content = session_path.read_text(encoding="utf-8-sig", errors="replace")
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            record_type = record.get("type")

            if record_type == "user":
                message_content = record.get("message", {}).get("content", "")
                if isinstance(message_content, str) and message_content:
                    if filter_xml_directives and message_content.startswith("<"):
                        continue
                    current_turn = {
                        "user": message_content[:max_user_chars],
                        "assistant": [],
                        "tools": [],
                    }
                    turns.append(current_turn)

            elif record_type == "assistant" and current_turn:
                message = record.get("message", {})
                content_items = message.get("content", [])

                if isinstance(content_items, list):
                    for item in content_items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            if text and len(text) > 20:
                                current_turn["assistant"].append(text[:max_assistant_chars])

                        elif item.get("type") == "tool_use":
                            tool_name = item.get("name", "")
                            tool_input = item.get("input", {})
                            if tool_name:
                                current_turn["tools"].append({
                                    "name": tool_name,
                                    "input": str(tool_input)[:max_tool_input_chars],
                                })
    except Exception as exc:
        if on_error == "raise":
            raise
        elif on_error == "warn":
            import sys
            print(f"Warning: Error parsing session {session_path}: {exc}", file=sys.stderr)

    return turns


# ---------------------------------------------------------------------------
# Session file listing
# ---------------------------------------------------------------------------

def list_session_files(
    directory: Path,
    *,
    min_size_kb: int = 100,
    pattern: str = "*.jsonl",
) -> list[dict[str, Any]]:
    """List session files in *directory*, sorted by modification time (newest first).

    Returns
    -------
    list[dict]
        Each dict has keys ``path``, ``name``, ``session_id``, ``size_kb``,
        ``size``, ``lines``, ``mtime`` (as :class:`~datetime.datetime` with
        UTC timezone).
    """
    if not directory.is_dir():
        return []

    sessions: list[dict[str, Any]] = []
    for session_file in sorted(directory.glob(pattern)):
        size_kb = session_file.stat().st_size / 1024
        if size_kb >= min_size_kb:
            sessions.append({
                "path": session_file,
                "name": session_file.name,
                "session_id": session_file.stem,
                "size_kb": size_kb,
                "size": f"{size_kb:.1f}KB",
                "lines": len(
                    session_file.read_text(
                        encoding="utf-8-sig", errors="replace"
                    ).splitlines()
                ),
                "mtime": datetime.fromtimestamp(
                    session_file.stat().st_mtime, tz=UTC
                ),
            })
    return sorted(sessions, key=session_sort_key, reverse=True)


def session_sort_key(session: dict[str, Any]) -> datetime:
    """Extract the ``mtime`` key for sorting (fallback to epoch)."""
    mtime = session.get("mtime")
    if isinstance(mtime, datetime):
        return mtime
    return datetime.min.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Packet generation helpers
# ---------------------------------------------------------------------------

def select_turns_for_packet(turns: list[Turn], max_turns: int = 12) -> tuple[list[Turn], int]:
    """Keep the opening request and the ending resolution for long sessions.

    Returns ``(selected_turns, omitted_count)``.
    If *turns* is already at or under *max_turns*, returns all turns unchanged.
    """
    total = len(turns)
    if total <= max_turns:
        return turns, 0

    head_count = max_turns // 2
    tail_count = max_turns - head_count
    selected = turns[:head_count] + turns[-tail_count:]
    omitted = total - len(selected)
    return selected, omitted
