from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def prevent_unmarked_real_embedding_loads(request, monkeypatch):
    """Keep normal pytest runs deterministic and free of real model startup."""

    if request.node.get_closest_marker("embedding_integration") is not None:
        return

    from harness_mem.embedding.model_loader import EmbeddingModelLoader

    def fail_real_load(_self) -> None:
        raise AssertionError(
            "real embedding model loading is disabled in default tests; "
            "mark the test embedding_integration"
        )

    monkeypatch.setattr(EmbeddingModelLoader, "_ensure_loaded", fail_real_load)
