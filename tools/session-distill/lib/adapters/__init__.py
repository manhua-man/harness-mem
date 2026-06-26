"""Source adapters for session-distill packetization."""

from .base import SourceAdapter, exclude_self_sessions, source_is_self_session
from .clients import ClaudeSourceAdapter, CodexSourceAdapter, GenericJsonlSourceAdapter

__all__ = [
    "ClaudeSourceAdapter",
    "CodexSourceAdapter",
    "GenericJsonlSourceAdapter",
    "SourceAdapter",
    "exclude_self_sessions",
    "source_is_self_session",
]
