"""Codex adapter — ingest Codex CLI sessions into harness-mem."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas.observation import Observation
from harness_mem.core.interfaces.memory_backend import MemoryBackend

# Default Codex session directory
DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


class CodexAdapter:
    """Adapter for ingesting Codex CLI sessions.

    Reads session data from ~/.codex/sessions/ and converts them
    to Observations for search-only (V1) use. Distillation/correction
    flows go through the Claude Code adapter.
    """

    def __init__(self, backend: MemoryBackend, sessions_dir: Path | None = None):
        self.backend = backend
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR

    def list_sessions(self, min_size_kb: int = 1) -> list[dict[str, Any]]:
        """List session files from the sessions directory."""
        if not self.sessions_dir.exists():
            return []

        sessions: list[dict[str, Any]] = []
        for session_file in self.sessions_dir.glob("**/*.jsonl"):
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
        return sorted(sessions, key=self._session_sort_key, reverse=True)

    def parse_jsonl_session(self, session_path: Path) -> list[dict[str, Any]]:
        """Parse a Codex .jsonl session file into turns."""
        turns: list[dict[str, Any]] = []
        current_turn: dict[str, Any] | None = None

        try:
            content = session_path.read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, PermissionError, UnicodeDecodeError) as e:
            import sys
            print(f"Error reading session file {session_path}: {e}", file=sys.stderr)
            return turns

        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            # Codex session record types vary; handle common patterns
            role = record.get("role", "")
            message_content = ""

            if role == "user":
                message_content = record.get("content", "") or ""
            elif role == "assistant":
                message_content = record.get("content", "") or ""

            # Also check for type-based format
            rec_type = record.get("type", "")
            if rec_type == "user":
                message_content = record.get("message", {}).get("content", "") or ""

            if message_content and isinstance(message_content, str) and message_content.strip():
                if current_turn is None:
                    current_turn = {"user": "", "assistant": []}
                    turns.append(current_turn)

                if role == "user" or rec_type == "user":
                    current_turn["user"] = message_content[:2000]
                else:
                    current_turn["assistant"].append(message_content[:1000])
            else:
                # Tool calls / function results
                if current_turn is None:
                    current_turn = {"user": "", "assistant": []}
                    turns.append(current_turn)

                tool_calls = record.get("tool_calls", []) or record.get("function_call", {})
                if tool_calls:
                    if isinstance(tool_calls, list):
                        for tc in tool_calls[:5]:
                            fn = tc.get("function", {})
                            current_turn["assistant"].append(
                                f"[tool: {fn.get('name', '?')}] {fn.get('arguments', '')[:200]}"
                            )
                    elif isinstance(tool_calls, dict):
                        fn = tool_calls.get("function", {})
                        current_turn["assistant"].append(
                            f"[tool: {fn.get('name', '?')}] {fn.get('arguments', '')[:200]}"
                        )

        return turns

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
    ) -> Observation:
        """Convert a parsed session to a single Observation."""
        turns = self.parse_jsonl_session(session_path)

        lines = [f"# Codex Session: {session_id}"]
        for i, turn in enumerate(turns[:20], 1):
            lines.append(f"\n## Turn {i}")
            if turn.get("user"):
                lines.append(f"\nUser: {turn['user'][:500]}")
            if turn.get("assistant"):
                for resp in turn["assistant"][:3]:
                    lines.append(f"\nAssistant: {resp[:500]}")

        raw_content = "\n".join(lines)
        if len(raw_content) > 50000:
            raw_content = raw_content[:50000] + "\n\n[TRUNCATED]"

        metadata = {"sessions_dir": str(self.sessions_dir)}
        if project_name:
            metadata["project_name"] = project_name

        return Observation(
            id=str(uuid4()),
            session_id=session_id,
            client="codex",
            raw_content=raw_content,
            content_type="transcript",
            timestamp=datetime.fromtimestamp(
                session_path.stat().st_mtime, tz=timezone.utc
            ),
            metadata=metadata,
            tags=["session", "codex"],
        )

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 1,
    ) -> dict:
        """Ingest recent Codex sessions.

        Returns dict with counts of ingested observations.
        """
        sessions = self.list_sessions(min_size_kb)
        sessions = sessions[:limit]

        ingested = 0
        errors = 0

        for session in sessions:
            try:
                session_id = session["name"].replace(".jsonl", "")
                obs = self.session_to_observation(session["path"], session_id, project_name)
                await self.backend.verbatim_store.save(obs)
                ingested += 1
            except Exception:
                errors += 1

        return {
            "sessions_found": len(self.list_sessions(0)),
            "ingested": ingested,
            "errors": errors,
        }

    @staticmethod
    def _session_sort_key(session: dict[str, Any]) -> datetime:
        mtime = session.get("mtime")
        if isinstance(mtime, datetime):
            return mtime
        return datetime.min.replace(tzinfo=timezone.utc)
