"""Claude Code adapter — ingest Claude Code sessions into harness-mem."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas import Observation, MemoryEntry
from harness_mem.core.interfaces.memory_backend import MemoryBackend


# Default Claude Code session directory
DEFAULT_SESSIONS_DIR = Path.home() / ".claude" / "projects"


class ClaudeCodeAdapter:
    """Adapter for ingesting Claude Code sessions.

    Reads .jsonl session files from ~/.claude/projects/{project_name}/
    and converts them to Observations + MemoryEntries.
    """

    def __init__(self, backend: MemoryBackend, sessions_dir: Path | None = None):
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR

    def list_project_sessions(
        self,
        project_name: str,
        min_size_kb: int = 100,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List session files for a project."""
        project_dir = self.sessions_dir / project_name
        if not project_dir.exists():
            return []

        sessions: list[dict[str, Any]] = []
        for session_file in project_dir.glob("*.jsonl"):
            size_kb = session_file.stat().st_size / 1024
            if size_kb >= min_size_kb:
                sessions.append({
                    "path": session_file,
                    "name": session_file.name,
                    "session_id": session_file.stem,
                    "size_kb": size_kb,
                    "size": f"{size_kb:.1f}KB",
                    "lines": len(session_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()),
                    "mtime": datetime.fromtimestamp(session_file.stat().st_mtime, tz=timezone.utc),
                })
        sessions = sorted(sessions, key=self._session_sort_key, reverse=True)
        if limit is not None:
            return sessions[:limit]
        return sessions

    def parse_jsonl_session(self, session_path: Path) -> list[dict[str, Any]]:
        """Parse a Claude Code .jsonl session file into turns."""
        turns: list[dict[str, Any]] = []
        current_turn: dict[str, Any] | None = None

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
                        current_turn = {
                            "user": message_content[:2000],
                            "assistant": [],
                            "tools": [],
                        }
                        turns.append(current_turn)

                elif record_type == "assistant" and current_turn:
                    message = record.get("message", {})
                    content_items = message.get("content", [])

                    if isinstance(content_items, list):
                        for item in content_items:
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    text = item.get("text", "")
                                    if text and len(text) > 20:
                                        current_turn["assistant"].append(text[:1000])

                                elif item.get("type") == "tool_use":
                                    tool_name = item.get("name", "")
                                    tool_input = item.get("input", {})
                                    if tool_name:
                                        current_turn["tools"].append({
                                            "name": tool_name,
                                            "input": str(tool_input)[:300],
                                        })
        except Exception:
            pass

        return turns

    def turns_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
    ) -> Observation:
        """Convert parsed session to a single Observation."""
        turns = self.parse_jsonl_session(session_path)

        # Summarize turns into a readable transcript
        lines = [f"# Session: {session_id}"]
        for i, turn in enumerate(turns[:20], 1):  # Cap at 20 turns
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for resp in turn["assistant"][:2]:
                    lines.append(f"\nAssistant: {resp[:500]}")
            if turn.get("tools"):
                tool_names = [t["name"] for t in turn["tools"][:5]]
                lines.append(f"\nTools: {', '.join(tool_names)}")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="claude-code",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata={"project_name": project_name},
            tags=["session", "claude-code"],
        )

    async def ingest_project(
        self,
        project_name: str,
        limit: int = 10,
        min_size_kb: int = 100,
    ) -> dict:
        """Ingest recent sessions for a project.

        Returns dict with counts of ingested observations.
        """
        sessions = self.list_project_sessions(project_name, min_size_kb)
        sessions = sessions[:limit]

        ingested = 0
        errors = 0

        for session in sessions:
            try:
                session_id = session["session_id"]
                obs = self.turns_to_observation(session["path"], session_id, project_name)
                await self.backend.verbatim_store.save(obs)
                ingested += 1
            except Exception:
                errors += 1

        return {
            "project_name": project_name,
            "sessions_found": len(self.list_project_sessions(project_name, 0)),
            "ingested": ingested,
            "errors": errors,
        }

    async def distill_session(
        self,
        session_id: str,
        project_name: str,
        category: str | None = None,
    ) -> list[MemoryEntry]:
        """Extract MemoryEntries from a session using heuristic pattern matching.

        Scans session transcript for reusable project knowledge:
        - technical decisions ("we decided to use X")
        - conventions ("I always use X", "the standard is Y")
        - bug workarounds ("the fix was X", "workaround: Y")
        - architecture notes ("I organized X into Y")

        If category is specified, only entries matching that category are returned/saved.
        Returns all newly saved entries for this session.
        """
        project_dir = self.sessions_dir / project_name
        if not project_dir.exists():
            return []

        # Find the session file
        session_file = None
        for sf in project_dir.glob("*.jsonl"):
            if session_id in sf.name:
                session_file = sf
                break

        if not session_file:
            return []

        turns = self.parse_jsonl_session(session_file)
        entries = self._extract_entries(turns, project_name, session_id)

        # Filter by category if specified
        if category:
            entries = [e for e in entries if e.category == category]

        if not entries:
            return []

        existing_entries = await self.backend.structured_store.list_memory_entries(
            project_name,
            limit=10000,
        )
        existing_keys = {
            self._entry_key(entry.category, entry.content, entry.source)
            for entry in existing_entries
        }

        saved_entries: list[MemoryEntry] = []
        for entry in entries:
            entry_key = self._entry_key(entry.category, entry.content, entry.source)
            if entry_key in existing_keys:
                continue
            await self.backend.structured_store.save_memory_entry(entry)
            existing_keys.add(entry_key)
            saved_entries.append(entry)

        return saved_entries

    def _extract_entries(
        self,
        turns: list[dict[str, Any]],
        project_name: str,
        session_id: str,
    ) -> list[MemoryEntry]:
        """Run heuristic extraction over parsed turns."""

        entries: list[MemoryEntry] = []
        seen_content: set[str] = set()

        def add(content: str, category: str, confidence: float, tags: list[str]) -> None:
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

        decision_patterns = [
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
            (re.compile(r"\berror[:\s]+\b(?!http)", re.I), "bug", "error"),
            (re.compile(r"\bfailed with\b", re.I), "bug", "failed with"),
            (re.compile(r"\bexception\b", re.I), "bug", "exception"),
            (re.compile(r"\bI extracted\b", re.I), "architecture", "I extracted"),
            (re.compile(r"\bsplit into\b", re.I), "architecture", "split into"),
            (re.compile(r"\bfile structure[:\s]+\b", re.I), "convention", "file structure"),
            (re.compile(r"\bnaming[:\s]+(pattern|convention|rule)\b", re.I), "convention", "naming pattern"),
            (re.compile(r"\bapi[:\s]+(endpoint|format|contract)\b", re.I), "api", "api contract"),
        ]

        # Only learn from assistant outputs. User prompts often contain desired
        # end states or hypothetical instructions and should not become memory.
        for turn in turns:
            assistant_texts = turn.get("assistant", [])
            if not assistant_texts:
                continue

            all_text = " ".join(assistant_texts)[:10000]

            for pattern, category, label in decision_patterns:
                m = pattern.search(all_text)
                if not m:
                    continue
                match_start = m.start()
                # Extract surrounding context: 100 chars before, 100 after
                ctx_start = max(0, match_start - 100)
                ctx_end = min(len(all_text), match_start + 200)
                sentence = all_text[ctx_start:ctx_end].strip()
                if len(sentence) > 20:
                    confidence = 0.6 if category == "bug" else 0.7
                    add(
                        sentence,
                        category,
                        confidence,
                        [category, "heuristic", f"pattern-source:{label}"],
                    )

        return entries

    @staticmethod
    def _entry_key(category: str, content: str, source: str) -> tuple[str, str, str]:
        normalized = " ".join(content.lower().split())
        return (category, normalized, source)

    @staticmethod
    def _session_sort_key(session: dict[str, Any]) -> datetime:
        mtime = session.get("mtime")
        if isinstance(mtime, datetime):
            return mtime
        return datetime.min.replace(tzinfo=timezone.utc)
