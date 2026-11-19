"""Shared fixture helpers for the isolated read probe and local experiment callers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness_mem.core.schemas import (  # noqa: E402
    AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_messages(text: str) -> list[tuple[str, str]]:
    """Decode this fixture's explicit role delimiters, not its semantics.

    Source .txt bytes remain intact for full reading. Markdown turn headings
    are structural metadata; an unheaded project preamble stays in the first
    user record rather than being discarded.
    """
    matches = list(re.finditer(r"(?m)^(User|Assistant): ", text))
    if not matches:
        raise ValueError("fixture has no explicit dialogue roles")
    messages = []
    prefix = text[:matches[0].start()].strip()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        body = re.split(r"\n## Turn \d+ \([^\n]*\)\n", body, maxsplit=1)[0].strip()
        if index == 0 and prefix and not prefix.startswith("# F"):
            body = prefix + "\n" + body
        messages.append((match[1].lower(), body))
    return messages


def native_records(source: dict, project: Path, session_id: str, ordinal: int) -> list[dict]:
    date = datetime(2026, 10, 7, tzinfo=timezone.utc) + timedelta(minutes=ordinal)
    stamp = date.isoformat().replace("+00:00", "Z")
    records = [{"timestamp": stamp, "type": "session_meta", "payload": {
        "id": session_id, "cwd": str(project), "timestamp": stamp, "source": "cli",
        "originator": "fictional-quality-baseline",
    }}]
    turn = 0
    for role, body in source_messages(source["text"]):
        if role == "user" or turn == 0:
            turn += 1
            records.append({"timestamp": stamp, "type": "turn_context", "payload": {
                "turn_id": f"fictional-turn-{turn}", "cwd": str(project),
            }})
        records.append({"timestamp": stamp, "type": "response_item", "payload": {
            "type": "message", "role": role, "phase": "final_answer" if role == "assistant" else None,
            "content": [{"type": "output_text" if role == "assistant" else "input_text", "text": body}],
        }})
    return records


async def seed_isolated_backend(data: Path, project: Path, rows: list[dict]) -> None:
    """Seed equal initial state via existing transaction APIs, not direct SQL."""
    backend = LocalMemoryBackend(data)
    await backend.init()
    try:
        store = backend.structured_store.knowledge_store
        entries = [KnowledgeEntry(project_name=project.name, module_path=["Initial knowledge"],
                                  title=row["title"], statement=row["statement"],
                                  verified_at=datetime.now(timezone.utc)) for row in rows]
        candidate = KnowledgeCandidate(id="fixture-initial-state", project_name=project.name,
                                       candidate_type="memory", statement="Frozen initial state.")
        decision = AssimilationDecision(id="fixture-initial-state", project_name=project.name,
                                        candidate_id=candidate.id, disposition="add",
                                        canonical_truth_ids=[entry.id for entry in entries],
                                        reason="Equal pre-existing fictional state; not an extraction result.")
        await store.save_candidate(candidate)
        source = project / "initial-knowledge.md"
        ref = ProjectKnowledgeSourceRef(label=source.name, target=source.resolve().as_uri(),
                                       kind="repository", digest=digest(source))
        await store.apply_current_change(
            candidate_before=candidate, candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision, added_entries=entries, predecessor_entries=[],
            source_refs_by_entry={entry.id: [ref] for entry in entries},
        )
    finally:
        await backend.close()


if __name__ == "__main__":
    raise SystemExit("The matched model comparison has been retired. This module provides fixture helpers only.")
