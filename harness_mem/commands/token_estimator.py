"""Token estimator for v2.3.1 content-based replay-window cap.

The metabolism replay-window selector (task 3.2) calls
:func:`count_tokens` once per selected id's content to compute a
content-aware ``soft_token_budget``. This module is the only place
that touches ``tiktoken`` so the selector stays free of the optional
dependency's import noise.

Tokenizer choice: ``cl100k_base`` (GPT-4 / GPT-4o family). See
``openspec/changes/v231-metabolism-suggestion-pass/design.md`` open
question on tokenizer selection — cl100k stays the default until v2.4
re-anchors on a different consumer.

Fallback: ``len(text) // 4`` is a coarse heuristic that's better than
nothing on environments where ``tiktoken`` isn't available (e.g.
minimal install profiles) or where the encoding download fails. The
caller learns which path resolved by reading :data:`tokenizer_kind`
after the call.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Module-level state. ``tokenizer_kind`` is the caller-visible flag;
# the lock + cached encoder are internal so concurrent calls share
# one tiktoken handle.
tokenizer_kind: str = "unknown"
_lock = threading.Lock()
_encoder: Any = None  # tiktoken.Encoding | None — lazily loaded
_encoder_load_failed: bool = False


def _get_encoder() -> Any:
    """Lazily load and cache the cl100k_base encoder.

    Returns the encoder on success, ``None`` on any failure
    (ImportError, encoding download failure, sandboxed environment,
    etc.). Failure is sticky — once we know tiktoken can't load, we
    don't keep retrying.
    """
    global _encoder, _encoder_load_failed
    if _encoder is not None:
        return _encoder
    if _encoder_load_failed:
        return None
    with _lock:
        # Re-check inside the lock in case another thread loaded it.
        if _encoder is not None:
            return _encoder
        if _encoder_load_failed:
            return None
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
            return _encoder
        except Exception:
            logger.exception(
                "token_estimator: tiktoken cl100k_base load failed; "
                "falling back to char-heuristic"
            )
            _encoder_load_failed = True
            return None


def count_tokens(text: str) -> int:
    """Estimate token count for ``text``.

    Returns ``0`` for empty / falsy input. Uses ``tiktoken`` with the
    ``cl100k_base`` encoding when available; falls back to a simple
    ``len(text) // 4`` heuristic when tiktoken can't be imported or
    the encoding fails to load.

    The caller can inspect the module-level flag :data:`tokenizer_kind`
    after the first call to learn which path was taken — used by
    ``select_replay_window`` (task 3.2) to attach a
    ``tokenizer_fallback: char-heuristic`` audit note when the
    fallback fired.
    """
    global tokenizer_kind
    if not text:
        # Don't change tokenizer_kind for empty input — it's not
        # informative about which path is wired.
        return 0
    encoder = _get_encoder()
    if encoder is None:
        tokenizer_kind = "char-heuristic"
        return len(text) // 4
    try:
        n = len(encoder.encode(text))
        tokenizer_kind = "tiktoken"
        return n
    except Exception:
        # Unexpected per-call failure: fall back this call but keep the
        # encoder cached for the next call (don't poison _encoder).
        logger.exception(
            "token_estimator: tiktoken encode failed for one input; "
            "falling back to char-heuristic"
        )
        tokenizer_kind = "char-heuristic"
        return len(text) // 4


def reset_for_tests() -> None:
    """Reset module-level state. Tests-only.

    The cached encoder, the failure flag, and ``tokenizer_kind`` all
    need to be reset between tests that monkey-patch the import path
    so each test starts with a known clean state.
    """
    global _encoder, _encoder_load_failed, tokenizer_kind
    with _lock:
        _encoder = None
        _encoder_load_failed = False
        tokenizer_kind = "unknown"
