"""Embedding model management for harness-mem."""

from harness_mem.embedding.model_registry import (
    ModelSpec,
    SUPPORTED_MODELS,
    get_model_spec,
)
from harness_mem.embedding.model_loader import (
    EmbeddingModelLoader,
    embeddings_disabled,
    get_model_loader,
    has_local_model_snapshot,
)

__all__ = [
    "ModelSpec",
    "SUPPORTED_MODELS",
    "get_model_spec",
    "EmbeddingModelLoader",
    "embeddings_disabled",
    "get_model_loader",
    "has_local_model_snapshot",
]
