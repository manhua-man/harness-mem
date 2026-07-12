"""Shared session parsing utilities for Claude Code and Codex .jsonl formats.

This is the **single source of truth** for session file parsing.
Derived from the original implementations in:
  - :mod:`harness_mem.adapters.claude_code.adapter`
  - :mod:`harness_mem.adapters.codex.adapter`
  - ``session-distill/bin/session-distill.py``

Usage::

    from harness_mem.adapters.parser import parse_claude_jsonl_session, list_session_files
    turns = parse_claude_jsonl_session(Path("session.jsonl"), on_error="silent")
    for turn in turns:
        print(turn["user"], turn["assistant"])
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness_mem.adapters.protocol import SessionRecord
from harness_mem.rust_core import scan_jsonl

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Turn = dict[str, Any]
"""A single conversational turn: ``{"user": str, "assistant": list[str], "tools": list[dict]}``."""

Issue = dict[str, str]
"""Diagnostic issue: ``{"level": str, "code": str, "message": str, "path"?: str, "session_id"?: str}``."""

# ---------------------------------------------------------------------------
# Claude Code .jsonl parser
# ---------------------------------------------------------------------------

def extract_claude_session_cwd(session_path: Path, *, max_lines: int = 50) -> Path | None:
    """Return the first usable ``cwd`` recorded in a Claude Code session.

    Claude stores project identity under ``~/.claude/projects`` using a
    normalized name, but individual session records usually preserve the real
    working directory.  Runtime commands use that cwd to build a project profile
    from source files instead of scanning the Claude session cache.
    """
    try:
        content = session_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None

    for index, line in enumerate(content.splitlines()):
        if index >= max_lines:
            break
        if not line.strip():
            continue
        try:
            record = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        cwd = record.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            return Path(cwd).expanduser()

    return None


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
        for record in scan_jsonl(content).records:
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
# Cursor .jsonl parser
# ---------------------------------------------------------------------------

def parse_cursor_jsonl_session(
    session_path: Path,
    *,
    max_user_chars: int = 2000,
    max_assistant_chars: int = 1000,
    max_tool_input_chars: int = 300,
    issues: list[Issue] | None = None,
) -> list[Turn]:
    """Parse a Cursor agent transcript ``.jsonl`` session into turns.

    Cursor agent transcripts use role-based records with ``message.content``
    blocks similar to Claude assistant messages. Transcript files can also
    include non-conversation lifecycle records such as ``turn_ended``; those
    are ignored for memory ingestion.
    """
    issues = issues if issues is not None else []
    turns: list[Turn] = []
    current_turn: Turn | None = None

    try:
        content = session_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ValueError(
            f"unable to read file ({type(exc).__name__}: {exc})"
        ) from exc

    scan_result = scan_jsonl(content)
    malformed_lines = len(scan_result.errors)
    valid_records = len(scan_result.records)
    nonempty_lines = valid_records + malformed_lines

    for record in scan_result.records:
        role = record.get("role")
        message = record.get("message", {})
        content_items = message.get("content", []) if isinstance(message, dict) else []

        if role == "user":
            user_text = _render_cursor_content_items(content_items)
            if user_text:
                current_turn = {
                    "user": user_text[:max_user_chars],
                    "assistant": [],
                    "tools": [],
                }
                turns.append(current_turn)
            continue

        if role == "assistant":
            if current_turn is None:
                current_turn = {"user": "", "assistant": [], "tools": []}
                turns.append(current_turn)
            if isinstance(content_items, list):
                for item in content_items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text":
                        text = str(item.get("text") or "").strip()
                        if text:
                            current_turn["assistant"].append(text[:max_assistant_chars])
                    elif item.get("type") == "tool_use":
                        tool_name = str(item.get("name") or "")
                        tool_input = item.get("input", {})
                        if tool_name:
                            current_turn["tools"].append({
                                "name": tool_name,
                                "input": str(tool_input)[:max_tool_input_chars],
                            })
            continue

    if valid_records == 0 and nonempty_lines > 0:
        raise ValueError(
            f"no valid JSON records found; skipped {malformed_lines} malformed line(s)"
        )

    if malformed_lines > 0:
        _append_issue(
            issues,
            level="warning",
            code="session_malformed_lines_skipped",
            message=(
                f"Cursor session {session_path} skipped "
                f"{malformed_lines} malformed JSON line(s)"
            ),
            path=session_path,
        )

    if valid_records > 0 and not turns:
        _append_issue(
            issues,
            level="warning",
            code="session_empty_after_parse",
            message=(
                f"Cursor session {session_path} contained valid JSON records, "
                "but no transcript content was extracted"
            ),
            path=session_path,
        )

    return turns


def _render_cursor_content_items(content_items: Any) -> str:
    if not isinstance(content_items, list):
        return ""
    parts: list[str] = []
    for item in content_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Grok .jsonl parser
# ---------------------------------------------------------------------------

def parse_grok_jsonl_session(
    session_path: Path,
    *,
    max_user_chars: int = 2000,
    max_assistant_chars: int = 1000,
    max_tool_input_chars: int = 300,
    issues: list[Issue] | None = None,
) -> list[Turn]:
    """Parse a Grok CLI ``chat_history.jsonl`` session into turns."""

    issues = issues if issues is not None else []
    turns: list[Turn] = []
    current_turn: Turn | None = None

    try:
        content = session_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ValueError(
            f"unable to read file ({type(exc).__name__}: {exc})"
        ) from exc

    scan_result = scan_jsonl(content)
    malformed_lines = len(scan_result.errors)
    valid_records = len(scan_result.records)
    nonempty_lines = valid_records + malformed_lines

    for record in scan_result.records:
        record_type = record.get("type")
        if record_type == "user":
            user_text = _render_grok_content(record.get("content"))
            if user_text:
                current_turn = {
                    "user": user_text[:max_user_chars],
                    "assistant": [],
                    "tools": [],
                }
                turns.append(current_turn)
            continue

        if record_type == "assistant":
            if current_turn is None:
                current_turn = {"user": "", "assistant": [], "tools": []}
                turns.append(current_turn)
            assistant_text = _render_grok_content(record.get("content"))
            if assistant_text:
                current_turn["assistant"].append(assistant_text[:max_assistant_chars])
            for tool_call in record.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                tool_name = str(tool_call.get("name") or "")
                if tool_name:
                    current_turn["tools"].append(
                        {
                            "name": tool_name,
                            "input": str(tool_call.get("arguments") or "")[
                                :max_tool_input_chars
                            ],
                        }
                    )

    if valid_records == 0 and nonempty_lines > 0:
        raise ValueError(
            f"no valid JSON records found; skipped {malformed_lines} malformed line(s)"
        )

    if malformed_lines > 0:
        _append_issue(
            issues,
            level="warning",
            code="session_malformed_lines_skipped",
            message=(
                f"Grok session {session_path} skipped "
                f"{malformed_lines} malformed JSON line(s)"
            ),
            path=session_path,
        )

    if valid_records > 0 and not turns:
        _append_issue(
            issues,
            level="warning",
            code="session_empty_after_parse",
            message=(
                f"Grok session {session_path} contained valid JSON records, "
                "but no transcript content was extracted"
            ),
            path=session_path,
        )

    return turns


def _render_grok_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Hermes .json parser
# ---------------------------------------------------------------------------

def parse_hermes_json_session(
    session_path: Path,
    *,
    max_user_chars: int = 2000,
    max_assistant_chars: int = 1000,
    max_tool_input_chars: int = 300,
    issues: list[Issue] | None = None,
) -> list[Turn]:
    """Parse a Hermes ``session_*.json`` transcript into turns."""

    issues = issues if issues is not None else []
    try:
        data = json.loads(session_path.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError as exc:
        raise ValueError(
            f"unable to read file ({type(exc).__name__}: {exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Hermes JSON session: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Hermes session root must be a JSON object")
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Hermes session is missing messages[]")

    turns: list[Turn] = []
    current_turn: Turn | None = None
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        content = _render_hermes_content(message.get("content"))
        if not content:
            content = _render_hermes_codex_message_items(
                message.get("codex_message_items")
            )

        if role == "user":
            if content:
                current_turn = {
                    "user": content[:max_user_chars],
                    "assistant": [],
                    "tools": [],
                }
                turns.append(current_turn)
            continue

        if role == "assistant":
            if current_turn is None:
                current_turn = {"user": "", "assistant": [], "tools": []}
                turns.append(current_turn)
            if content:
                current_turn["assistant"].append(content[:max_assistant_chars])
            current_turn["tools"].extend(
                _extract_hermes_tools(
                    message.get("codex_message_items"),
                    max_tool_input_chars=max_tool_input_chars,
                )
            )

    if messages and not turns:
        _append_issue(
            issues,
            level="warning",
            code="session_empty_after_parse",
            message=(
                f"Hermes session {session_path} contained messages, "
                "but no transcript content was extracted"
            ),
            path=session_path,
        )

    return turns


def read_hermes_session_id(session_path: Path) -> str | None:
    """Return the ``session_id`` from a Hermes session file when present."""

    try:
        data = json.loads(session_path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    session_id = data.get("session_id")
    if not isinstance(session_id, str):
        return None
    cleaned = session_id.strip()
    return cleaned or None


def _render_hermes_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "content", "message"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") in {None, "text", "output_text", "input_text"}:
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _render_hermes_codex_message_items(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            rendered = _render_hermes_content(item.get("content"))
            if rendered:
                parts.append(rendered)
    return "\n".join(parts).strip()


def _extract_hermes_tools(
    items: Any,
    *,
    max_tool_input_chars: int,
) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    tools: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        name = str(item.get("name") or item.get("tool_name") or "").strip()
        if item_type not in {"function_call", "tool_use", "tool_call"} and not name:
            continue
        if not name:
            name = str(item_type or "tool")
        tool_input = item.get("input")
        if tool_input is None:
            tool_input = item.get("arguments")
        tools.append(
            {
                "name": name,
                "input": json.dumps(tool_input, ensure_ascii=False)[:max_tool_input_chars]
                if isinstance(tool_input, (dict, list))
                else str(tool_input or "")[:max_tool_input_chars],
            }
        )
    return tools


# ---------------------------------------------------------------------------
# Codex .jsonl parser
# ---------------------------------------------------------------------------

def parse_codex_jsonl_session(
    session_path: Path,
    *,
    max_user_chars: int = 2000,
    max_assistant_chars: int = 1000,
    issues: list[Issue] | None = None,
) -> list[Turn]:
    """Parse a Codex CLI ``.jsonl`` session file into a list of turns.

    Codex format differs from Claude Code — records use ``role``
    (``"user"`` / ``"assistant"``) with content in ``record["content"]``,
    and tool calls appear as ``tool_calls`` / ``function_call`` fields
    rather than content blocks.

    Parameters
    ----------
    session_path:
        Path to the ``.jsonl`` file.
    max_user_chars:
        Maximum characters to keep for each user message.
    max_assistant_chars:
        Maximum characters to keep for each assistant message.
    issues:
        Optional mutable list to append warnings to.

    Returns
    -------
    list[Turn]
        Each turn is a dict with keys ``user``, ``assistant``.

    Raises
    ------
    ValueError
        If the file contains lines but **no** valid ``.jsonl`` records.
    """
    issues = issues if issues is not None else []
    turns: list[Turn] = []
    current_turn: Turn | None = None

    try:
        content = session_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ValueError(
            f"unable to read file ({type(exc).__name__}: {exc})"
        ) from exc

    scan_result = scan_jsonl(content)
    malformed_lines = len(scan_result.errors)
    valid_records = len(scan_result.records)
    nonempty_lines = valid_records + malformed_lines

    for record in scan_result.records:

        role = record.get("role", "")
        message_content = ""

        if role == "user":
            message_content = record.get("content", "") or ""
        elif role == "assistant":
            message_content = record.get("content", "") or ""

        # Also check type-based format (Codex sometimes uses Claude-style)
        rec_type = record.get("type", "")
        if rec_type == "user":
            message_content = record.get("message", {}).get("content", "") or ""

        if message_content and isinstance(message_content, str) and message_content.strip():
            if current_turn is None:
                current_turn = {"user": "", "assistant": []}
                turns.append(current_turn)

            if role == "user" or rec_type == "user":
                current_turn["user"] = message_content[:max_user_chars]
            else:
                current_turn["assistant"].append(message_content[:max_assistant_chars])
        else:
            tool_calls = record.get("tool_calls", []) or record.get("function_call", {})
            if tool_calls:
                if current_turn is None:
                    current_turn = {"user": "", "assistant": []}
                    turns.append(current_turn)
                if isinstance(tool_calls, list):
                    for tc in tool_calls[:5]:
                        fn = tc.get("function", {})
                        current_turn["assistant"].append(
                            f"[tool: {fn.get('name', '?')}] {fn.get('arguments', '')[:200]}"
                        )
                elif isinstance(tool_calls, dict):
                    # function_call dict: keys are "name" and "arguments" directly
                    current_turn["assistant"].append(
                        f"[tool: {tool_calls.get('name', '?')}] {tool_calls.get('arguments', '')[:200]}"
                    )

    if valid_records == 0 and nonempty_lines > 0:
        raise ValueError(
            f"no valid JSON records found; skipped {malformed_lines} malformed line(s)"
        )

    if malformed_lines > 0:
        _append_issue(
            issues,
            level="warning",
            code="session_malformed_lines_skipped",
            message=(
                f"Codex session {session_path} skipped "
                f"{malformed_lines} malformed JSON line(s)"
            ),
            path=session_path,
        )

    if valid_records > 0 and not turns:
        _append_issue(
            issues,
            level="warning",
            code="session_empty_after_parse",
            message=(
                f"Codex session {session_path} contained valid JSON records, "
                "but no transcript content was extracted"
            ),
            path=session_path,
        )

    return turns


# ---------------------------------------------------------------------------
# Codex Archive .jsonl parser (from session-distill)
# ---------------------------------------------------------------------------

BOILERPLATE_USER_PREFIXES = (
    "# Context from my IDE setup:",
    "## My request for Codex:",
)
IDE_CONTEXT_PREFIX = "# Context from my IDE setup:"
IDE_REQUEST_MARKER = "## My request for Codex:"
AGENTS_CONTEXT_PREFIX = "# AGENTS.md instructions"
TURN_ABORTED_REGEX = re.compile(r"<turn_aborted>.*?</turn_aborted>", re.DOTALL)


def extract_archived_text(content: Any) -> str:
    """Extract and normalize text from various Codex content formats."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n\n".join(parts).strip()


def sanitize_archived_user_text(text: str) -> str:
    """Remove IDE boilerplate and aborted turn markers from Codex user messages."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned.startswith(AGENTS_CONTEXT_PREFIX) and IDE_REQUEST_MARKER not in cleaned:
        return ""
    if any(cleaned.startswith(prefix) for prefix in BOILERPLATE_USER_PREFIXES):
        # If it only contains boilerplate, it's effectively empty for memory
        if cleaned.startswith(IDE_CONTEXT_PREFIX) and IDE_REQUEST_MARKER in cleaned:
            cleaned = cleaned.split(IDE_REQUEST_MARKER, 1)[1].strip()
        else:
            return ""
    cleaned = TURN_ABORTED_REGEX.sub("", cleaned).strip()
    return cleaned


def parse_codex_archive_jsonl_session(
    session_path: Path,
    *,
    max_user_chars: int = 2000,
    max_assistant_chars: int = 1000,
    issues: list[Issue] | None = None,
) -> tuple[dict[str, Any], list[Turn]]:
    """Parse a Codex 'rollout-*.jsonl' archive file.

    Derived from the high-fidelity parser in session-distill.py.
    Returns (session_meta, turns).
    """
    session_meta: dict[str, Any] = {
        "session_id": session_path.stem,
        "cwd": "",
        "start_timestamp": "",
        "last_timestamp": "",
        "invalid_json_lines": 0,
    }
    turns: list[Turn] = []
    # Intermediary turn lookup to handle multi-line tool/message events
    turn_lookup: dict[str, Turn] = {}

    def _ensure_turn(turn_id: str | None) -> Turn:
        actual_id = turn_id or f"turn-{len(turns) + 1}"
        if actual_id not in turn_lookup:
            new_turn: Turn = {
                "turn_id": actual_id,
                "user": "",
                "assistant": [],
                "tools": [],
                "timestamp": "",
            }
            turn_lookup[actual_id] = new_turn
            turns.append(new_turn)
        return turn_lookup[actual_id]

    try:
        content = session_path.read_text(encoding="utf-8", errors="replace")
        archive_scan = scan_jsonl(content)
        session_meta["invalid_json_lines"] = len(archive_scan.errors)
        for record in archive_scan.records:
            top_level_type = record.get("type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue

            if top_level_type == "session_meta":
                session_meta["session_id"] = payload.get("id") or session_meta["session_id"]
                session_meta["cwd"] = payload.get("cwd") or session_meta["cwd"]
                session_meta["start_timestamp"] = payload.get("timestamp") or session_meta["start_timestamp"]
                continue

            # Every event-carrying record should have a turn_id
            turn_id = payload.get("turn_id")
            turn = _ensure_turn(turn_id)

            if top_level_type == "turn_context":
                turn["timestamp"] = payload.get("current_date") or turn["timestamp"]
                continue

            if top_level_type == "event_msg":
                event_type = payload.get("type")
                if event_type == "user_message":
                    msg = sanitize_archived_user_text(str(payload.get("message") or ""))
                    if msg:
                        turn["user"] = (turn["user"] + "\n" + msg).strip()[:max_user_chars]
                elif event_type == "agent_message":
                    msg = str(payload.get("message") or "")
                    phase = str(payload.get("phase") or "")
                    if msg and phase in ("commentary", "final_answer"):
                        turn["assistant"].append(msg[:max_assistant_chars])
                continue

            if top_level_type == "response_item":
                item_type = payload.get("type")
                if item_type == "message":
                    role = payload.get("role")
                    text = extract_archived_text(payload.get("content"))
                    if role == "user":
                        sanitized = sanitize_archived_user_text(text)
                        if sanitized:
                            turn["user"] = (turn["user"] + "\n" + sanitized).strip()[:max_user_chars]
                    elif role == "assistant" and text:
                        turn["assistant"].append(text[:max_assistant_chars])
                elif item_type == "function_call":
                    tool_name = str(payload.get("name") or "")
                    args = str(payload.get("arguments") or "")
                    turn["tools"].append({
                        "name": tool_name,
                        "input": args[:300],
                    })

    except Exception as exc:
        _append_issue(issues, level="error", code="parse_failed", message=str(exc), path=session_path)

    # Clean up empty turns
    valid_turns = [
        t for t in turns
        if t["user"] or t["assistant"] or t["tools"]
    ]
    return session_meta, valid_turns


# ---------------------------------------------------------------------------
# Session file listing
# ---------------------------------------------------------------------------

def list_session_files(
    directory: Path,
    *,
    min_size_kb: int = 100,
    pattern: str = "*.jsonl",
) -> list[SessionRecord]:
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

    sessions: list[SessionRecord] = []
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


def session_sort_key(session: SessionRecord) -> datetime:
    """Extract the ``mtime`` key for sorting (fallback to epoch)."""
    mtime = session.get("mtime")
    if isinstance(mtime, datetime):
        return mtime
    return datetime.min.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Packet generation helpers (session-distill compatibility)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_issue(
    level: str,
    code: str,
    message: str,
    path: Path | None = None,
    session_id: str | None = None,
) -> Issue:
    issue: Issue = {
        "level": level,
        "code": code,
        "message": message,
    }
    if path is not None:
        issue["path"] = str(path)
    if session_id is not None:
        issue["session_id"] = session_id
    return issue


def _append_issue(
    issues: list[Issue] | None,
    *,
    level: str,
    code: str,
    message: str,
    path: Path | None = None,
    session_id: str | None = None,
) -> None:
    if issues is None:
        return
    issues.append(_build_issue(level, code, message, path, session_id))


__all__ = [
    "Turn",
    "Issue",
    "extract_claude_session_cwd",
    "parse_claude_jsonl_session",
    "parse_cursor_jsonl_session",
    "parse_grok_jsonl_session",
    "parse_codex_jsonl_session",
    "parse_codex_archive_jsonl_session",
    "list_session_files",
    "session_sort_key",
    "select_turns_for_packet",
]
