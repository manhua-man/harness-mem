"""Offline semantic candidates over caller-supplied *current* knowledge.

This optional BGE Chinese ONNX channel discovers neighbors, not applicable
facts. Every token window participates; callers retain the full task and fact
for their own relevance/condition judgment. No query or task text is cached.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any

from harness_mem.embedding.model_loader import embeddings_disabled


MODEL_DIRECTORY_ENV = "HARNESS_MEM_CURRENT_SEMANTIC_MODEL_DIR"
PREPROCESSING_VERSION = "bge-zh-cls-lowercase-single-window-max-v2"
_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
_ARTIFACTS = ("model_int8.onnx", "tokenizer.json", "config.json", "tokenizer_config.json")
_LOCK = RLock()
_ENCODERS: OrderedDict[str, Any] = OrderedDict()
_DOCUMENT_CACHES: OrderedDict[tuple[str, str], dict[str, tuple[str, Any]]] = OrderedDict()


@dataclass(frozen=True)
class SemanticResult:
    ordered_ids: list[str]
    binding: str
    status: str
    reason: str | None = None
    metrics: dict[str, int | float] = field(default_factory=dict)


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    result = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _artifacts(directory: Path) -> tuple[dict[str, str], str | None]:
    observed: dict[str, str] = {}
    for name in _ARTIFACTS:
        path = directory / name
        try:
            observed[name] = _file_digest(path)
        except (OSError, ValueError):
            observed[name] = "unreadable"
    return observed, ("Local semantic model files are missing or unreadable."
                      if "unreadable" in observed.values() else None)


def _dependency_versions() -> dict[str, str]:
    found = {}
    for name in ("numpy", "onnxruntime", "tokenizers"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = "unavailable"
    return found


class _Encoder:
    def __init__(self, directory: Path):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        from tokenizers.normalizers import Lowercase, Sequence

        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        tokenizer_config = json.loads((directory / "tokenizer_config.json").read_text(encoding="utf-8"))
        if (config.get("model_type") != "bert" or config.get("hidden_size") != 512
                or config.get("max_position_embeddings") != 512
                or tokenizer_config.get("tokenizer_class") != "BertTokenizer"):
            raise ValueError("Only the BGE small Chinese BERT artifact contract is supported.")
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        normalizer = self.tokenizer.normalizer
        self.tokenizer.normalizer = Sequence([Lowercase(), normalizer] if normalizer else [Lowercase()])
        self.cls = self.tokenizer.token_to_id("[CLS]")
        self.sep = self.tokenizer.token_to_id("[SEP]")
        self.pad = self.tokenizer.token_to_id("[PAD]")
        if None in (self.cls, self.sep, self.pad):
            raise ValueError("BERT special tokens are missing.")
        self.instruction = self.tokenizer.encode(_QUERY_INSTRUCTION, add_special_tokens=False).ids
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        options.enable_mem_pattern = False
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(str(directory / "model_int8.onnx"),
            sess_options=options, providers=["CPUExecutionProvider"])
        self.inputs = {item.name for item in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"}.issubset(self.inputs) or self.inputs - {
                "input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("Unsupported ONNX inputs.")
        if "last_hidden_state" not in {item.name for item in self.session.get_outputs()}:
            raise ValueError("CLS hidden-state output is missing.")

    def windows(self, text: str, *, query: bool = False) -> list[list[int]]:
        """Disable tokenizer truncation and partition every content token once."""
        tokens = self.tokenizer.encode(text, add_special_tokens=False).ids
        prefix = self.instruction if query else []
        width = 510 - len(prefix)
        if width < 1:
            raise ValueError("Query instruction exceeds the model capacity.")
        return [[self.cls, *prefix, *tokens[start:start + width], self.sep]
                for start in range(0, max(1, len(tokens)), width)]

    def encode(self, texts: list[str], *, query: bool = False) -> list[Any]:
        np = self.np
        work = [(index, window) for index, text in enumerate(texts)
                for window in self.windows(text, query=query)]
        work.sort(key=lambda pair: len(pair[1]))
        grouped: list[list[Any]] = [[] for _ in texts]
        # The int8 model's output depends on other windows in its inference
        # batch. Encode each window independently so cache history and corpus
        # changes cannot alter an unchanged document's vector or read cursor.
        for item in work:
            batch = [item]
            width = max(len(tokens) for _, tokens in batch)
            ids = np.full((len(batch), width), self.pad, dtype=np.int64)
            mask = np.zeros_like(ids)
            for index, (_, tokens) in enumerate(batch):
                ids[index, :len(tokens)] = tokens
                mask[index, :len(tokens)] = 1
            inputs = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                inputs["token_type_ids"] = np.zeros_like(ids)
            output = self.session.run(["last_hidden_state"], inputs)[0]
            if output.ndim != 3 or output.shape[0] != len(batch) or output.shape[2] != 512:
                raise ValueError("Unexpected BGE hidden-state shape.")
            vectors = output[:, 0, :].copy()
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if not np.isfinite(vectors).all() or not np.isfinite(norms).all() or (norms <= 0).any():
                raise ValueError("Invalid semantic vectors.")
            vectors /= norms
            for (index, _), vector in zip(batch, vectors):
                grouped[index].append(vector)
        return [np.stack(group) for group in grouped]


def semantic_discovery(
    documents: list[tuple[str, str]], *, query: str, task_context: str, namespace: str,
    minimum_score: float | None = None,
) -> SemanticResult:
    """Rank all supplied current identities; unavailable never means no match.

    The directory is explicit and local. Document vectors are derived and
    namespace/content/model keyed; every call evicts rows the caller removed.
    Query vectors, task text, scores and decisions exist only within this call.
    """
    started = perf_counter()
    identity: dict[str, object] = {"preprocessing": PREPROCESSING_VERSION}

    def unavailable(reason: str) -> SemanticResult:
        return SemanticResult([], _digest({**identity, "status": "unavailable", "reason": reason}),
                              "unavailable", reason)

    if embeddings_disabled():
        return unavailable("Semantic discovery is disabled.")
    configured = os.environ.get(MODEL_DIRECTORY_ENV, "").strip()
    if not configured:
        return unavailable("No local semantic model directory is configured.")
    try:
        directory = Path(configured).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return unavailable("Local semantic model directory is invalid or unreadable.")
    artifacts, error = _artifacts(directory)
    identity.update({"artifacts": artifacts, "runtime": _dependency_versions()})
    if error:
        return unavailable(error)
    if len({key for key, _ in documents}) != len(documents):
        return unavailable("Current semantic document identities must be unique.")
    binding = _digest({**identity, "status": "available"})
    try:
        with _LOCK:
            encoder = _ENCODERS.get(binding)
            if encoder is None:
                encoder = _Encoder(directory)
                # Detect artifacts changing during model construction.
                if _artifacts(directory)[0] != artifacts:
                    return unavailable("Local semantic model files changed while loading.")
                _ENCODERS.clear()
                _DOCUMENT_CACHES.clear()
                _ENCODERS[binding] = encoder
            cache_key = binding, namespace
            cached = _DOCUMENT_CACHES.get(cache_key, {})
            content = {key: sha256(text.encode()).hexdigest() for key, text in documents}
            missing = [(key, text) for key, text in documents
                       if key not in cached or cached[key][0] != content[key]]
            fresh_vectors = encoder.encode([text for _, text in missing]) if missing else []
            current = {key: cached[key] for key, _ in documents
                       if key in cached and cached[key][0] == content[key]}
            for (key, _), vectors in zip(missing, fresh_vectors):
                current[key] = content[key], vectors
            _DOCUMENT_CACHES[cache_key] = current
            _DOCUMENT_CACHES.move_to_end(cache_key)
            while len(_DOCUMENT_CACHES) > 4:
                _DOCUMENT_CACHES.popitem(last=False)
            task = f"任务背景：{task_context}\n当前问题：{query}" if task_context else query
            query_vectors = encoder.encode([task], query=True)[0]
            # Max is a discovery heuristic; it does not establish conjunction,
            # exclusions or relevance. Full-text Agent review remains required.
            scores = [(key, float((current[key][1] @ query_vectors.T).max())) for key, _ in documents]
            ordered = [key for key, score in sorted(scores, key=lambda item: (-item[1], item[0]))
                       if minimum_score is None or score >= minimum_score]
            metrics = {"documents": len(documents), "encoded_documents": len(missing),
                       "document_windows": sum(len(value[1]) for value in current.values()),
                       "query_windows": len(query_vectors),
                       "seconds": round(perf_counter() - started, 6)}
        return SemanticResult(ordered, binding, "available", metrics=metrics)
    except Exception:
        # Optional native-runtime failures may have backend-specific exception
        # classes. Keep ordinary lexical retrieval usable without leaking paths.
        return unavailable("Local semantic encoding failed; lexical discovery remains available.")
