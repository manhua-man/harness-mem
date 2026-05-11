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
from uuid import uuid4

from harness_mem.adapters.protocol import SessionRecord
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.relation_fact import RelationFact

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

    malformed_lines = 0
    nonempty_lines = 0
    valid_records = 0

    for line in content.splitlines():
        if not line.strip():
            continue
        nonempty_lines += 1
        try:
            record = json.loads(line.strip())
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        valid_records += 1

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
# Heuristic extraction patterns (for ClaudeCodeAdapter.distill_session)
# ---------------------------------------------------------------------------

HEURISTIC_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bwe decided to use\b", re.I), "decision", "we decided to use"),
    (re.compile(r"\bwe chose\b", re.I), "decision", "we chose"),
    (re.compile(r"\bthe approach is\b", re.I), "decision", "the approach is"),
    (re.compile(r"\bI set up\b", re.I), "architecture", "I set up"),
    (re.compile(r"\bI configured\b", re.I), "architecture", "I configured"),
    (re.compile(r"\bI organized\b", re.I), "architecture", "I organized"),
    (re.compile(r"\bstandard is\b", re.I), "convention", "standard is"),
    (re.compile(r"\bconvention is\b", re.I), "convention", "convention is"),
    (re.compile(r"\bI always use\b", re.I), "convention", "I always use"),
    (re.compile(r"\balways use\b", re.I), "convention", "always use"),
    (re.compile(r"\bthe fix was\b", re.I), "bug", "the fix was"),
    (re.compile(r"\bworkaround[:\s]+\b", re.I), "bug", "workaround"),
    (re.compile(r"\bthe workaround is\b", re.I), "bug", "the workaround is"),
    (re.compile(r"\bthe root cause was\b", re.I), "bug", "the root cause was"),
    (re.compile(r"\bthe issue was fixed by\b", re.I), "bug", "the issue was fixed by"),
    (re.compile(r"\bfixed by\b", re.I), "bug", "fixed by"),
    (re.compile(r"\bI extracted\b", re.I), "architecture", "I extracted"),
    (re.compile(r"\bsplit into\b", re.I), "architecture", "split into"),
    (re.compile(r"\bfile structure[:\s]+\b", re.I), "convention", "file structure"),
    (re.compile(r"\bnaming[:\s]+(pattern|convention|rule)\b", re.I), "convention", "naming pattern"),
    (re.compile(r"\bapi[:\s]+(endpoint|format|contract)\b", re.I), "api", "api contract"),
]

RELATION_FACT_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"\b([A-Z][A-Za-z0-9_.-]{2,})\s+(depends on|relies on)\s+([A-Z][A-Za-z0-9_.-]{2,})\b"),
        "depends_on",
        "depends on",
    ),
    (
        re.compile(r"\b([A-Z][A-Za-z0-9_.-]{2,})\s+(delegates to|calls into)\s+([A-Z][A-Za-z0-9_.-]{2,})\b"),
        "delegates_to",
        "delegates to",
    ),
    (
        re.compile(r"\b([A-Z][A-Za-z0-9_.-]{2,})\s+(uses|backs onto)\s+([A-Z][A-Za-z0-9_.-]{2,})\b"),
        "uses",
        "uses",
    ),
]


def extract_heuristic_entries(
    turns: list[Turn],
    project_name: str,
    session_id: str,
    patterns: list[tuple[re.Pattern, str, str]] | None = None,
    *,
    max_text_length: int = 10000,
    context_before: int = 100,
    context_after: int = 200,
    min_sentence_length: int = 20,
    confidence_bug: float = 0.6,
    confidence_other: float = 0.7,
) -> list[MemoryEntry]:
    """Run heuristic pattern matching over assistant turn text.

    Only assistant messages are examined (user prompts often contain
    hypotheticals and should not become memory).

    Parameters
    ----------
    turns:
        Parsed session turns.
    project_name:
        Project to associate entries with.
    session_id:
        Source session identifier (stored in ``entry.source``).
    patterns:
        List of ``(compiled_regex, category, label)`` tuples.
        Defaults to :data:`HEURISTIC_PATTERNS`.
    max_text_length:
        Maximum characters of joined assistant text to scan per turn.
    context_before:
        Characters of context to keep **before** a match.
    context_after:
        Characters of context to keep **after** a match.
    min_sentence_length:
        Minimum extracted sentence length (shorter snippets are discarded).
    confidence_bug:
        Confidence score for ``"bug"`` category entries.
    confidence_other:
        Confidence score for all other category entries.

    Returns
    -------
    list[MemoryEntry]
        Deduplicated entries (no two entries share the same normalised content).
    """
    if patterns is None:
        patterns = HEURISTIC_PATTERNS

    entries: list[MemoryEntry] = []
    seen_content: set[str] = set()

    def _add(content: str, category: str, confidence: float, tags: list[str]) -> None:
        normalized = content.lower()[:100]
        if normalized and normalized not in seen_content:
            seen_content.add(normalized)
            entries.append(MemoryEntry(
                id=str(uuid4()),
                project_name=project_name,
                category=category,
                content=content,
                confidence=confidence,
                source=f"session:{session_id}",
                tags=tags,
            ))

    for turn in turns:
        assistant_texts = turn.get("assistant", [])
        if not assistant_texts:
            continue

        all_text = " ".join(assistant_texts)[:max_text_length]

        for pattern, category, label in patterns:
            m = pattern.search(all_text)
            if not m:
                continue
            match_start = m.start()
            ctx_start = max(0, match_start - context_before)
            ctx_end = min(len(all_text), match_start + context_after)
            sentence = all_text[ctx_start:ctx_end].strip()
            if len(sentence) > min_sentence_length:
                confidence = confidence_bug if category == "bug" else confidence_other
                _add(
                    sentence,
                    category,
                    confidence,
                    [category, "heuristic", f"pattern-source:{label}"],
                )

    return entries


def extract_relation_facts(
    turns: list[Turn],
    project_name: str,
    session_id: str,
    patterns: list[tuple[re.Pattern, str, str]] | None = None,
    *,
    max_text_length: int = 10000,
) -> list[RelationFact]:
    """Extract explicit entity-to-entity facts from assistant turn text.

    This is intentionally conservative. It only matches capitalized entity
    tokens around explicit relation verbs, which keeps ordinary prose from
    becoming graph facts.
    """
    if patterns is None:
        patterns = RELATION_FACT_PATTERNS

    facts: list[RelationFact] = []
    seen: set[tuple[str, str, str]] = set()

    def _sentence_around(text: str, start: int, end: int) -> str:
        left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
        right_candidates = [
            idx for idx in (text.find(".", end), text.find("\n", end)) if idx != -1
        ]
        right = min(right_candidates) if right_candidates else min(len(text), end + 160)
        sentence_start = 0 if left == -1 else left + 1
        return " ".join(text[sentence_start:right].split())

    for turn in turns:
        assistant_texts = turn.get("assistant", [])
        if not assistant_texts:
            continue

        all_text = " ".join(assistant_texts)[:max_text_length]
        for pattern, relation_type, label in patterns:
            for match in pattern.finditer(all_text):
                source_entity = match.group(1)
                target_entity = match.group(3)
                key = (source_entity.lower(), relation_type, target_entity.lower())
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    RelationFact(
                        id=str(uuid4()),
                        project_name=project_name,
                        source_entity=source_entity,
                        target_entity=target_entity,
                        relation_type=relation_type,
                        confidence=0.65,
                        evidence=_sentence_around(all_text, match.start(), match.end()),
                        source=f"session:{session_id}",
                        tags=["relation", "heuristic", f"pattern-source:{label}"],
                    )
                )

    return facts


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
    "parse_codex_jsonl_session",
    "list_session_files",
    "session_sort_key",
    "select_turns_for_packet",
    "HEURISTIC_PATTERNS",
    "extract_heuristic_entries",
]
