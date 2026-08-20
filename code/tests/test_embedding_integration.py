from __future__ import annotations

import os

import pytest


@pytest.mark.embedding_integration
@pytest.mark.skipif(
    os.environ.get("HARNESS_MEM_RUN_EMBEDDING_INTEGRATION") != "1",
    reason="set HARNESS_MEM_RUN_EMBEDDING_INTEGRATION=1 to load the real model",
)
def test_real_embedding_batch_shape() -> None:
    from harness_mem.embedding import get_model_loader

    loader = get_model_loader("all-MiniLM-L6-v2")
    vectors = loader.encode(["alpha", "beta"])
    assert len(vectors) == 2
    assert len(vectors[0]) == loader.dimensions
