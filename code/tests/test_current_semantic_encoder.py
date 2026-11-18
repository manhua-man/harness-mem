"""Current semantic candidates never own tasks, eligibility or memory truth."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import numpy as np
import pytest

from harness_mem.embedding import current_semantic as semantic


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("HARNESS_MEM_CURRENT_SEMANTIC_MODEL_DIR", raising=False)
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    semantic._ENCODERS.clear()
    semantic._DOCUMENT_CACHES.clear()
    yield
    semantic._ENCODERS.clear()
    semantic._DOCUMENT_CACHES.clear()


def _discover(documents=None, **overrides):
    return semantic.semantic_discovery(
        documents or [("apple", "apple"), ("orange", "orange")],
        **{"query": "which", "task_context": "apple", "namespace": "store-a", **overrides},
    )


def _directory(tmp_path, monkeypatch):
    for name in semantic._ARTIFACTS:
        (tmp_path / name).write_text(name, encoding="utf-8")
    monkeypatch.setenv(semantic.MODEL_DIRECTORY_ENV, str(tmp_path))
    return tmp_path


class FakeEncoder:
    def __init__(self, directory):
        self.calls = []

    def encode(self, texts, *, query=False):
        self.calls.append((list(texts), query))
        return [np.asarray([[1.0, 0.0] if "apple" in text else [0.0, 1.0]]) for text in texts]


def _fake(tmp_path, monkeypatch):
    path = _directory(tmp_path, monkeypatch)
    monkeypatch.setattr(semantic, "_Encoder", FakeEncoder)
    return path


def test_missing_directory_is_unavailable_not_empty_answer():
    result = _discover()
    assert result.status == "unavailable" and not result.ordered_ids
    assert "configured" in result.reason


def test_invalid_directory_does_not_break_lexical_fallback(monkeypatch):
    monkeypatch.setenv(semantic.MODEL_DIRECTORY_ENV, "unreadable-directory")

    def denied(path):
        raise OSError("Cannot resolve local artifact directory")

    monkeypatch.setattr(semantic.Path, "resolve", denied)
    result = _discover()
    assert result.status == "unavailable" and not result.ordered_ids


def test_disable_flag_prevents_loading_even_with_explicit_directory(tmp_path, monkeypatch):
    _directory(tmp_path, monkeypatch)
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    monkeypatch.setattr(semantic, "_Encoder", lambda _: pytest.fail("Loaded disabled model"))
    assert _discover().reason == "Semantic discovery is disabled."


def test_missing_artifact_is_distinct_and_recovery_changes_binding(tmp_path, monkeypatch):
    path = _fake(tmp_path, monkeypatch)
    complete = _discover()
    (path / "model_int8.onnx").unlink()
    missing = _discover()
    assert complete.status == "available"
    assert missing.status == "unavailable" and "missing" in missing.reason
    assert missing.binding != complete.binding


def test_corrupt_model_fails_honestly_and_binding_covers_its_bytes(tmp_path, monkeypatch):
    path = _directory(tmp_path, monkeypatch)
    first = _discover()
    assert first.status == "unavailable" and "failed" in first.reason
    (path / "model_int8.onnx").write_bytes(b"different corrupt model")
    assert _discover().binding != first.binding


def test_task_context_changes_results_without_task_cache(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    apple = _discover(task_context="apple")
    orange = _discover(task_context="orange")
    assert apple.ordered_ids == ["apple", "orange"]
    assert orange.ordered_ids == ["orange", "apple"]
    assert apple.binding == orange.binding  # Caller separately binds exact task context.
    encoder = next(iter(semantic._ENCODERS.values()))
    assert [texts for texts, query in encoder.calls if query] == [
        ["任务背景：apple\n当前问题：which"], ["任务背景：orange\n当前问题：which"],
    ]
    assert all(isinstance(value, tuple) and isinstance(value[0], str)
               for cache in semantic._DOCUMENT_CACHES.values() for value in cache.values())


def test_simultaneous_tasks_do_not_inherit_each_other_context(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    contexts = ["apple", "orange"] * 8
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda text: _discover(task_context=text), contexts))
    assert [result.ordered_ids[0] for result in results] == contexts


def test_document_cache_reuses_only_unchanged_current_rows(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    assert _discover().metrics["encoded_documents"] == 2
    assert _discover().metrics["encoded_documents"] == 0
    changed = _discover([("apple", "changed orange"), ("new", "apple")])
    assert changed.metrics["encoded_documents"] == 2
    assert set(changed.ordered_ids) == {"apple", "new"}
    assert set(next(iter(semantic._DOCUMENT_CACHES.values()))) == {"apple", "new"}


def test_cache_namespace_prevents_same_id_cross_store_reuse(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    first = _discover([("same", "apple")], namespace="a")
    second = _discover([("same", "orange")], namespace="b")
    assert first.metrics["encoded_documents"] == second.metrics["encoded_documents"] == 1
    caches = semantic._DOCUMENT_CACHES
    assert caches[(first.binding, "a")]["same"][0] != caches[(second.binding, "b")]["same"][0]


@pytest.mark.parametrize("name", semantic._ARTIFACTS)
def test_every_model_artifact_change_invalidates_derived_cache(tmp_path, monkeypatch, name):
    path = _fake(tmp_path, monkeypatch)
    first = _discover()
    (path / name).write_text("changed", encoding="utf-8")
    second = _discover()
    assert second.binding != first.binding
    assert second.metrics["encoded_documents"] == 2


def test_runtime_and_preprocessing_versions_are_bound(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    first = _discover()
    monkeypatch.setattr(semantic, "PREPROCESSING_VERSION", "new preprocessing")
    second = _discover()
    monkeypatch.setattr(semantic, "_dependency_versions", lambda: {"runtime": "another"})
    third = _discover()
    assert len({first.binding, second.binding, third.binding}) == 3


def test_changed_while_loading_does_not_publish_mixed_model(tmp_path, monkeypatch):
    path = _directory(tmp_path, monkeypatch)

    def changed(directory):
        (path / "model_int8.onnx").write_bytes(b"changed while loading")
        return FakeEncoder(directory)

    monkeypatch.setattr(semantic, "_Encoder", changed)
    result = _discover()
    assert result.status == "unavailable" and "changed" in result.reason
    assert not semantic._ENCODERS and not semantic._DOCUMENT_CACHES


def test_duplicate_identity_refuses_ambiguous_vectors(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    result = _discover([("same", "apple"), ("same", "orange")])
    assert result.status == "unavailable" and "unique" in result.reason


@pytest.mark.parametrize("query", [False, True])
@pytest.mark.parametrize("length", [0, 1, 509, 510, 511, 1020, 1803])
def test_windows_cover_every_token_including_last_condition(query, length):
    encoder = object.__new__(semantic._Encoder)
    tokens = list(range(1000, 1000 + length))
    encoder.tokenizer = SimpleNamespace(encode=lambda text, **kwargs: SimpleNamespace(ids=tokens))
    encoder.cls, encoder.sep, encoder.instruction = 101, 102, [71, 72, 73]
    windows = encoder.windows("all original text", query=query)
    prefix = 4 if query else 1
    assert all(len(window) <= 512 for window in windows)
    assert [token for window in windows for token in window[prefix:-1]] == tokens
    assert all(window[0] == 101 and window[-1] == 102 for window in windows)


@pytest.mark.parametrize("query", [False, True])
def test_encoding_is_independent_of_other_windows_and_call_history(query):
    encoder = object.__new__(semantic._Encoder)
    encoder.np = np
    encoder.cls, encoder.sep, encoder.pad, encoder.instruction = 101, 102, 0, [71, 72]
    encoder.inputs = {"input_ids", "attention_mask"}
    encoder.tokenizer = SimpleNamespace(encode=lambda text, **kwargs:
        SimpleNamespace(ids=[ord(character) for character in text]))

    class BatchSensitiveSession:
        def __init__(self):
            self.shapes = []

        def run(self, outputs, inputs):
            ids = inputs["input_ids"]
            self.shapes.append(ids.shape)
            result = np.zeros((*ids.shape, 512), dtype=np.float32)
            result[:, 0, 0] = ids[:, 1] + 1
            result[:, 0, 1] = ids.sum() + 1  # Expose cross-row coupling like dynamic quantization.
            result[:, 0, 2] = inputs["attention_mask"].sum(axis=1)
            return [result]

    encoder.session = BatchSensitiveSession()
    target = "condition at the end " * 60
    standalone = encoder.encode([target], query=query)[0]
    accompanied = encoder.encode(["other fact", target, "different long content " * 45], query=query)[1]
    repeated = encoder.encode([target], query=query)[0]
    np.testing.assert_array_equal(standalone, accompanied)
    np.testing.assert_array_equal(standalone, repeated)
    assert all(shape[0] == 1 for shape in encoder.session.shapes)


def test_model_shape_rejection_is_unavailable(tmp_path, monkeypatch):
    path = _directory(tmp_path, monkeypatch)
    (path / "config.json").write_text(json.dumps({"model_type": "bert", "hidden_size": 256,
        "max_position_embeddings": 512}), encoding="utf-8")
    (path / "tokenizer_config.json").write_text(json.dumps({"tokenizer_class": "BertTokenizer"}), encoding="utf-8")
    result = _discover()
    assert result.status == "unavailable" and not semantic._ENCODERS
