from __future__ import annotations

import atexit
import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.core.schemas import MemoryEntry, Observation


_TEST_LOOP: asyncio.AbstractEventLoop | None = None


def _get_test_loop() -> asyncio.AbstractEventLoop:
    global _TEST_LOOP
    if _TEST_LOOP is None or _TEST_LOOP.is_closed():
        _TEST_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_TEST_LOOP)
    return _TEST_LOOP


def _close_test_loop() -> None:
    if _TEST_LOOP is None or _TEST_LOOP.is_closed():
        return
    pending = [task for task in asyncio.all_tasks(_TEST_LOOP) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        _TEST_LOOP.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    _TEST_LOOP.run_until_complete(_TEST_LOOP.shutdown_asyncgens())
    _TEST_LOOP.run_until_complete(_TEST_LOOP.shutdown_default_executor())
    _TEST_LOOP.close()


atexit.register(_close_test_loop)


def run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _get_test_loop().run_until_complete(coro)
    raise RuntimeError("tests.helpers.run() cannot be called while an event loop is running")



def _embeddings_disabled() -> bool:
    """True when HARNESS_MEM_DISABLE_EMBEDDINGS opts embeddings out."""
    return os.environ.get("HARNESS_MEM_DISABLE_EMBEDDINGS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Skip marker for tests that need a real embedding model (vector rows, hybrid
# mode, dimension checks). When HARNESS_MEM_DISABLE_EMBEDDINGS is set the model
# is never loaded, so these assertions cannot hold — skip rather than fail.
requires_embeddings = pytest.mark.skipif(
    _embeddings_disabled(),
    reason="embeddings disabled via HARNESS_MEM_DISABLE_EMBEDDINGS",
)


def read_events(data_dir: Path) -> list[dict]:
    events_path = data_dir / "events.log"
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_claude_session(
    sessions_root: Path,
    project_name: str,
    session_id: str,
    user_text: str,
    assistant_texts: list[str],
) -> Path:
    project_dir = sessions_root / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    session_path = project_dir / f"{session_id}.jsonl"
    records = [
        {"type": "user", "message": {"content": user_text}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": text} for text in assistant_texts],
            },
        },
    ]
    session_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return session_path


def write_codex_session(sessions_root: Path, session_id: str, text: str) -> Path:
    session_path = sessions_root / f"{session_id}.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps({"role": "user", "content": text}) + "\n", encoding="utf-8")
    return session_path


def write_codex_archive_session(
    archive_root: Path,
    session_id: str,
    *,
    user_text: str,
    assistant_text: str,
    cwd: str | None = None,
) -> Path:
    session_path = archive_root / f"rollout-{session_id}.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "timestamp": "2026-05-17T00:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-05-17T00:00:00.000Z",
                "cwd": cwd or str(Path.cwd()),
            },
        },
        {
            "timestamp": "2026-05-17T00:00:01.000Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "turn_id": "turn-1",
                "message": user_text,
            },
        },
        {
            "timestamp": "2026-05-17T00:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": assistant_text}],
                "turn_id": "turn-1",
            },
        },
    ]
    session_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return session_path


def patch_cli_adapters(
    monkeypatch,
    *,
    claude_sessions_root: Path | None = None,
    codex_sessions_root: Path | None = None,
    codex_archive_root: Path | None = None,
) -> None:
    if claude_sessions_root is not None:
        monkeypatch.setitem(
            AdapterRegistry._adapters,
            "claude-code",
            lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
        )
    if codex_sessions_root is not None:
        monkeypatch.setitem(
            AdapterRegistry._adapters,
            "codex",
            lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
        )
        monkeypatch.setattr(
            cli,
            "CodexAdapter",
            lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
        )
    if codex_archive_root is not None:
        monkeypatch.setitem(
            AdapterRegistry._adapters,
            "codex-archive",
            lambda backend: CodexArchiveAdapter(backend, archive_dir=codex_archive_root),
        )


def fake_embed_texts(self, texts: list[str]) -> list[list[float]]:
    return [[1.0, float(len(text))] for text in texts]


class FakeEmbeddingLoader:
    dimensions = 2
    model_version = "test"


def patch_fake_embedding_loader(monkeypatch) -> None:
    import harness_mem.embedding as embedding

    monkeypatch.setattr(embedding, "embeddings_disabled", lambda: False)
    monkeypatch.setattr(embedding, "get_model_loader", lambda _model_id: FakeEmbeddingLoader())


class FakeWriteEmbeddingLoader:
    dimensions = 384
    model_version = "test"

    def encode(self, texts):
        import hashlib
        import re

        import numpy as np

        one_text = isinstance(texts, str)
        items = [texts] if one_text else list(texts)
        vectors: list[np.ndarray] = []
        for text in items:
            vector = np.zeros(self.dimensions, dtype=np.float32)
            tokens = re.findall(r"[a-z0-9]+", str(text).lower())
            for token in tokens:
                key = token[:-1] if len(token) > 4 and token.endswith("s") else token
                digest = hashlib.sha256(key.encode("utf-8")).digest()
                vector[int.from_bytes(digest[:4], "little") % self.dimensions] += 1.0
            if not np.any(vector):
                vector[0] = 1.0
            vectors.append(vector)
        arr = np.vstack(vectors)
        return arr[0] if one_text else arr


def patch_fake_write_embedding_loader(monkeypatch) -> None:
    import harness_mem.embedding as embedding
    from harness_mem.storage import sqlite_index

    sqlite_index._EMBEDDING_WRITE_TIMED_OUT_MODELS.clear()
    sqlite_index._EMBEDDING_WRITE_UNCACHED_MODELS.clear()
    monkeypatch.setattr(embedding, "embeddings_disabled", lambda: False)
    monkeypatch.setattr(embedding, "has_local_model_snapshot", lambda _model_id: True)
    monkeypatch.setattr(
        embedding,
        "get_model_loader",
        lambda _model_id: FakeWriteEmbeddingLoader(),
    )


def seed_persisted_embedding(backend, entry_id: str, values: tuple[float, float] = (1.0, 1.0)) -> None:
    import numpy as np

    from harness_mem.commands.support import get_embedding_model_id

    conn = backend.structured_store._index._conn_write()
    embedding = np.asarray(values, dtype=np.float32)
    conn.execute(
        """
        INSERT OR REPLACE INTO vec_embeddings
            (entry_id, model_id, model_version, embedding, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            entry_id,
            get_embedding_model_id(),
            "test",
            embedding.tobytes(),
            int(time.time()),
        ),
    )
    conn.commit()


def no_embed_texts(self, texts: list[str]) -> None:
    return None


async def seed_search_backend(
    backend,
    *,
    project_name: str = "test-project",
    session_id: str = "test-session-001",
) -> None:
    observation = Observation(
        session_id=session_id,
        client="claude-code",
        raw_content="We decided to use SQLite FTS5 for full-text search in this project.",
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session", "claude-code"],
    )
    await backend.verbatim_store.save(observation)

    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="SQLite FTS5 is used for full-text search indexing",
        confidence=0.9,
        source="manual",
        tags=["architecture", "search"],
    )
    await backend.structured_store.save_memory_entry(entry)
