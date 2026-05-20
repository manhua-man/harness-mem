"""Embedding model registry for harness-mem.

Defines supported embedding models and their metadata.
"""

from __future__ import annotations
from typing import NamedTuple


class ModelSpec(NamedTuple):
    """Embedding model specification."""
    model_id: str
    hf_model_name: str
    dimensions: int
    size_mb: int
    license: str


# Supported embedding models (v1.6.2)
SUPPORTED_MODELS: dict[str, ModelSpec] = {
    "all-MiniLM-L6-v2": ModelSpec(
        model_id="all-MiniLM-L6-v2",
        hf_model_name="sentence-transformers/all-MiniLM-L6-v2",
        dimensions=384,
        size_mb=22,
        license="Apache 2.0",
    ),
    "bge-small-en-v1.5": ModelSpec(
        model_id="bge-small-en-v1.5",
        hf_model_name="BAAI/bge-small-en-v1.5",
        dimensions=384,
        size_mb=130,
        license="MIT",
    ),
    "nomic-embed-text-v1.5": ModelSpec(
        model_id="nomic-embed-text-v1.5",
        hf_model_name="nomic-ai/nomic-embed-text-v1.5",
        dimensions=768,
        size_mb=130,
        license="Apache 2.0",
    ),
}


def get_model_spec(model_id: str) -> ModelSpec:
    """Get model spec by ID, raise HM-203 if unsupported."""
    if model_id not in SUPPORTED_MODELS:
        supported_list = ", ".join(SUPPORTED_MODELS.keys())
        raise ValueError(
            f"HM-203: Unsupported embedding model '{model_id}'. "
            f"Supported: {supported_list}"
        )
    return SUPPORTED_MODELS[model_id]
