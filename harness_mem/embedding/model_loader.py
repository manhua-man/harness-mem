"""Embedding model loader with lazy initialization."""

from __future__ import annotations
import os
from typing import Any

from harness_mem.embedding.model_registry import get_model_spec, ModelSpec

_DISABLE_ENV_VAR = "HARNESS_MEM_DISABLE_EMBEDDINGS"
_TRUTHY = {"1", "true", "yes", "on"}
_LOCAL_SNAPSHOT_AVAILABILITY: dict[tuple[str, str, str], bool] = {}


def embeddings_disabled() -> bool:
    """Return True when embedding model loading is disabled via env.

    Set ``HARNESS_MEM_DISABLE_EMBEDDINGS`` to a truthy value (``1``, ``true``,
    ``yes``, ``on``; case-insensitive) to skip all sentence-transformers model
    loading. This is an opt-out escape hatch for environments where importing
    the embedding stack hangs or is unavailable (for example a CI box without a
    cached model, or a broken ``torch`` install). When set, embedding writes
    and search-time embedding are skipped instead of loading the model.
    """
    return os.environ.get(_DISABLE_ENV_VAR, "").strip().lower() in _TRUTHY


def has_local_model_snapshot(model_id: str) -> bool:
    """Return True when the embedding model is already cached locally.

    Write-path embedding persistence is best-effort. Interactive write tools
    should not trigger a first-time Hugging Face download just to add a vec row,
    because that can stall MCP writes for tens of seconds on a fresh home.
    """

    cache_key = (
        model_id,
        os.environ.get("HF_HOME", ""),
        os.environ.get("SENTENCE_TRANSFORMERS_HOME", ""),
    )
    cached = _LOCAL_SNAPSHOT_AVAILABILITY.get(cache_key)
    if cached is not None:
        return cached

    spec = get_model_spec(model_id)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        # If the hub helper is unavailable, do not block write-path embeddings
        # on a cache probe we cannot perform.
        _LOCAL_SNAPSHOT_AVAILABILITY[cache_key] = True
        return True

    try:
        snapshot_download(spec.hf_model_name, local_files_only=True)
    except Exception:
        _LOCAL_SNAPSHOT_AVAILABILITY[cache_key] = False
        return False

    _LOCAL_SNAPSHOT_AVAILABILITY[cache_key] = True
    return True


class EmbeddingModelLoader:
    """Lazy-loading embedding model wrapper.

    Loads the sentence-transformers model on first encode call,
    not at import time. Falls back gracefully if dependencies missing.
    """

    def __init__(self, model_id: str):
        self.model_id = model_id
        self.spec: ModelSpec = get_model_spec(model_id)  # Validates model_id
        self._model: Any | None = None
        self._model_version: str | None = None

    def _ensure_loaded(self) -> None:
        """Load model on first use (lazy loading)."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install 'harness-mem[hybrid]'"
            ) from e

        self._model = SentenceTransformer(self.spec.hf_model_name)

        # Extract model version from package or model metadata
        try:
            import sentence_transformers
            self._model_version = sentence_transformers.__version__
        except (ImportError, AttributeError):
            self._model_version = "unknown"

    def encode(self, texts: list[str] | str) -> Any:
        """Encode text(s) to embeddings. Returns numpy array."""
        self._ensure_loaded()
        assert self._model is not None  # mypy hint: _ensure_loaded guarantees this
        return self._model.encode(texts, convert_to_numpy=True)

    @property
    def model_version(self) -> str:
        """Get model version (loads model if not yet loaded)."""
        self._ensure_loaded()
        return self._model_version or "unknown"

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions."""
        return self.spec.dimensions


# Global model loader instance (lazy-initialized)
_model_loader: EmbeddingModelLoader | None = None


def get_model_loader(model_id: str) -> EmbeddingModelLoader:
    """Get or create the global model loader instance.

    Args:
        model_id: Model identifier (e.g., "all-MiniLM-L6-v2")

    Returns:
        EmbeddingModelLoader instance

    Raises:
        ValueError: If model_id is not supported (HM-203)
    """
    global _model_loader
    if _model_loader is None or _model_loader.model_id != model_id:
        _model_loader = EmbeddingModelLoader(model_id)
    return _model_loader
