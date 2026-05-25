"""Centralized retrieval-signal write path.

v2.3.0: every shadow-write of a `RetrievalSignal` from existing wake /
search / review / skill / supersede call sites goes through
`record_retrieval_signal`. The helper enforces the "main task must not
be held hostage" rule from `docs/roadmap-v23-v24.md`: signal-write
failures are logged and swallowed, never raised back to the caller.
"""

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
    """Persist a retrieval signal as a shadow write.

    Returns the persisted ``RetrievalSignal`` on success, ``None`` when the
    write fails. Callers MUST NOT propagate the return value into the
    user-visible response — this stays implementation detail.

    Failure is logged with full traceback so doctor / dashboards can
    surface a chronic write failure, but the caller continues with its
    primary mutation.

    Note: ``save_retrieval_signal`` lives on the concrete
    :class:`LocalStructuredStore` rather than the
    :class:`StructuredStore` Protocol because writers are kept
    implementation-side (mirrors how ``touch_*`` helpers were left off
    the Protocol). The cast is the single place that crosses that
    boundary; if a non-local backend ever shows up, a ``hasattr`` guard
    or a writer Protocol can replace this cast without touching call
    sites.
    """
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
