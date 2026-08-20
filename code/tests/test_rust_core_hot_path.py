"""Hot-path rust_core facade: policy, hybrid fusion, batch cosine."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from harness_mem import rust_core
from harness_mem.rust_core import (
    RustCoreRequiredError,
    batch_cosine_topk,
    fuse_hybrid_rrf,
    rust_core_status,
    rust_policy,
)


def test_rust_policy_defaults_to_prefer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_RUST", raising=False)
    assert rust_policy() == "prefer"


def test_rust_policy_invalid_value_falls_back_to_prefer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_RUST", "maybe")
    assert rust_policy() == "prefer"


def test_rust_core_status_reports_force_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_RUST", "force_python")
    status = rust_core_status()
    assert status.policy == "force_python"
    assert status.available is False
    assert status.mode == "python_fallback"


def test_fuse_hybrid_rrf_is_deterministic() -> None:
    ranked = fuse_hybrid_rrf(
        ["a", "b", "c"],
        fts_rank={"a": 0, "b": 2},
        vec_rank={"b": 0, "c": 1},
        fts_confidence={"a": 1.0, "b": 0.5},
        vec_confidence={"b": 1.0, "c": 0.8},
        rrf_k=40.0,
        fts_weight=2.0,
        vector_weight=6.0,
        limit=2,
    )
    assert len(ranked) == 2
    assert ranked[0][0] in {"a", "b", "c"}
    again = fuse_hybrid_rrf(
        ["a", "b", "c"],
        fts_rank={"a": 0, "b": 2},
        vec_rank={"b": 0, "c": 1},
        fts_confidence={"a": 1.0, "b": 0.5},
        vec_confidence={"b": 1.0, "c": 0.8},
        rrf_k=40.0,
        fts_weight=2.0,
        vector_weight=6.0,
        limit=2,
    )
    assert ranked == again


def test_batch_cosine_topk_matches_python_reference() -> None:
    query = [1.0, 0.0, 0.0]
    embeddings = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.0, 1.0, 0.0],
        "c": [0.5, 0.5, 0.0],
    }
    scores = batch_cosine_topk(query, embeddings)
    assert scores["a"] == pytest.approx(1.0)
    assert scores["b"] == pytest.approx(0.0)
    assert scores["c"] == pytest.approx(0.70710678, rel=1e-5)


def test_required_policy_raises_on_hot_path_without_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name == rust_core.NATIVE_MODULE_NAME:
            raise ModuleNotFoundError(name)
        return original_import(name, package)

    monkeypatch.setenv("HARNESS_MEM_RUST", "required")
    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(RustCoreRequiredError):
        fuse_hybrid_rrf(
            ["a"],
            fts_rank={"a": 0},
            vec_rank={},
            fts_confidence={"a": 1.0},
            vec_confidence={},
            limit=1,
        )


def test_required_policy_raises_for_batch_cosine_without_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name == rust_core.NATIVE_MODULE_NAME:
            raise ModuleNotFoundError(name)
        return original_import(name, package)

    monkeypatch.setenv("HARNESS_MEM_RUST", "required")
    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(RustCoreRequiredError):
        batch_cosine_topk([1.0, 0.0], {"a": [1.0, 0.0]})


def test_fuse_hybrid_rrf_native_matches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    if not rust_core_status().available:
        pytest.skip("harness_mem_core_rs native extension not installed")

    kwargs = {
        "fts_rank": {"a": 0, "b": 2},
        "vec_rank": {"b": 0, "c": 1},
        "fts_confidence": {"a": 1.0, "b": 0.5},
        "vec_confidence": {"b": 1.0, "c": 0.8},
        "rrf_k": 40.0,
        "fts_weight": 2.0,
        "vector_weight": 6.0,
        "limit": 3,
    }
    native = fuse_hybrid_rrf(["a", "b", "c"], **kwargs)
    monkeypatch.setattr(rust_core, "_native", lambda: None)
    fallback = fuse_hybrid_rrf(["a", "b", "c"], **kwargs)
    assert native == fallback


def test_batch_cosine_topk_native_matches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    if not rust_core_status().available:
        pytest.skip("harness_mem_core_rs native extension not installed")

    query = [1.0, 0.0, 0.0]
    embeddings = {"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]}
    native = batch_cosine_topk(query, embeddings)
    monkeypatch.setattr(rust_core, "_native", lambda: None)
    fallback = batch_cosine_topk(query, embeddings)
    assert native == pytest.approx(fallback, rel=1e-5, abs=1e-5)


def test_distribution_warnings_for_prefer_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import harness_mem.distribution as distribution

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("HARNESS_MEM_RUST", "prefer")
    monkeypatch.setattr(
        distribution,
        "rust_core_status",
        lambda: rust_core.RustCoreStatus(
            api_version="v4.0.2",
            mode="python_fallback",
            native_module="harness_mem_core_rs",
            available=False,
            fallback_reason="ModuleNotFoundError: no module",
            policy="prefer",
        ),
    )
    report = distribution.distribution_report(repo_root=tmp_path, data_dir=data_dir)
    assert any("python_fallback" in warning for warning in report.get("warnings", []))