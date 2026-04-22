"""Claude Code adapter — ingest Claude Code sessions into harness-mem."""

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
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

    def list_project_sessions(self, project_name: str, min_size_kb: int = 100) -> list[dict]:
        """List session files for a project."""
        project_dir = self.sessions_dir / project_name
        if not project_dir.exists():
            return []

        sessions = []
        for session_file in project_dir.glob("*.jsonl"):
            size_kb = session_file.stat().st_size / 1024
            if size_kb >= min_size_kb:
                sessions.append({
                    "path": session_file,
                    "name": session_file.name,
                    "size_kb": size_kb,
                    "size": f"{size_kb:.1f}KB",
                    "lines": len(session_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()),
                    "mtime": datetime.fromtimestamp(session_file.stat().st_mtime, tz=timezone.utc),
                })
        return sorted(sessions, key=lambda s: s["mtime"], reverse=True)

    def parse_jsonl_session(self, session_path: Path) -> list[dict]:
        """Parse a Claude Code .jsonl session file into turns."""
        turns = []
        current_turn = None

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
                session_id = session["name"].replace(".jsonl", "")
                obs = self.turns_to_observation(session["path"], session_id, project_name)
                await self.backend.verbatim_store.save(obs)
                ingested += 1
            except Exception as e:
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
    ) -> MemoryEntry | None:
        """Extract a MemoryEntry from a session (simple heuristic version).

        This is a stub — full distillation requires LLM involvement.
        Returns None for now; real distillation happens via separate CLI.
        """
        return None
