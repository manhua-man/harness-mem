"""Centralized retrieval-signal write path."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast

from harness_mem.core.schemas import RetrievalSignal
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore

logger = logging.getLogger(__name__)


async def record_retrieval_signal(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    signal_type: str,
    target_kind: str,
    target_id: str,
    value: float | None = None,
    context: dict[str, Any] | None = None,
    recorded_at: datetime | None = None,
) -> RetrievalSignal | None:
    """Persist a retrieval signal as a best-effort shadow write."""

    try:
        signal = RetrievalSignal(
            project_name=project_name,
            signal_type=signal_type,
            target_kind=target_kind,
            target_id=target_id,
            value=value,
            context=context,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        store = cast(LocalStructuredStore, backend.structured_store)
        await store.save_retrieval_signal(signal)
        return signal
    except Exception:
        logger.exception(
            "Failed to record retrieval signal "
            "(project=%s, signal=%s, target=%s/%s)",
            project_name,
            signal_type,
            target_kind,
            target_id,
        )
        return None


__all__ = ["record_retrieval_signal"]
