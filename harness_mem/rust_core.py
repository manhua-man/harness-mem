"""Stable Python facade for the v4.0 Rust core hot path.

Read-path helpers route through this module.  When ``harness_mem_core_rs`` is
installed the native implementation is used; otherwise a parity-tested Python
fallback runs.  ``HARNESS_MEM_RUST`` controls whether fallback is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import math
import os
import re
from typing import Any, Iterable, Literal, Sequence


RUST_CORE_API_VERSION = "v4.0.3"
NATIVE_MODULE_NAME = "harness_mem_core_rs"
RUST_POLICY_ENV = "HARNESS_MEM_RUST"
RustPolicy = Literal["prefer", "required", "force_python"]
_VALID_RUST_POLICIES = frozenset({"prefer", "required", "force_python"})


class RustCoreRequiredError(RuntimeError):
    """Raised when ``HARNESS_MEM_RUST=required`` and the native extension is missing."""


@dataclass(frozen=True)
class RustCoreStatus:
    api_version: str
    mode: str
    native_module: str
    available: bool
    fallback_reason: str | None
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "mode": self.mode,
            "native_module": self.native_module,
            "available": self.available,
            "fallback_reason": self.fallback_reason,
            "policy": self.policy,
        }


def rust_policy() -> RustPolicy:
    """Return the active Rust runtime policy from ``HARNESS_MEM_RUST``."""

    raw = os.environ.get(RUST_POLICY_ENV, "prefer").strip().lower()
    if raw in _VALID_RUST_POLICIES:
        return raw  # type: ignore[return-value]
    return "prefer"


@dataclass(frozen=True)
class JsonlScanResult:
    records: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "errors": self.errors,
            "record_count": len(self.records),
            "error_count": len(self.errors),
        }


def rust_core_status() -> RustCoreStatus:
    """Return native/fallback mode without raising on missing extensions."""

    policy = rust_policy()
    if policy == "force_python":
        return RustCoreStatus(
            api_version=RUST_CORE_API_VERSION,
            mode="python_fallback",
            native_module=NATIVE_MODULE_NAME,
            available=False,
            fallback_reason="HARNESS_MEM_RUST=force_python",
            policy=policy,
        )

    try:
        module = importlib.import_module(NATIVE_MODULE_NAME)
    except Exception as exc:  # noqa: BLE001 - import failures are status, not crash.
        return RustCoreStatus(
            api_version=RUST_CORE_API_VERSION,
            mode="python_fallback",
            native_module=NATIVE_MODULE_NAME,
            available=False,
            fallback_reason=f"{exc.__class__.__name__}: {exc}",
            policy=policy,
        )
    version = getattr(module, "api_version", lambda: RUST_CORE_API_VERSION)
    return RustCoreStatus(
        api_version=str(version()),
        mode="rust",
        native_module=NATIVE_MODULE_NAME,
        available=True,
        fallback_reason=None,
        policy=policy,
    )


def scan_jsonl(text: str) -> JsonlScanResult:
    """Tolerant JSONL scanner used by session import hot-path tests."""

    native = _native()
    if native is not None and hasattr(native, "scan_jsonl"):
        payload = native.scan_jsonl(text)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return JsonlScanResult(
            records=list(payload.get("records") or []),
            errors=list(payload.get("errors") or []),
        )

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append(
                {
                    "line": line_no,
                    "code": "HM-410",
                    "message": exc.msg,
                }
            )
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            errors.append(
                {
                    "line": line_no,
                    "code": "HM-411",
                    "message": "JSONL record must be an object",
                }
            )
    return JsonlScanResult(records=records, errors=errors)


def build_bulk_index_rows(payloads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build deterministic searchable rows from payload JSON objects."""

    payload_list = [dict(payload) for payload in payloads]
    native = _native()
    if native is not None and hasattr(native, "build_bulk_index_rows"):
        payload = native.build_bulk_index_rows(
            json.dumps(payload_list, sort_keys=True, ensure_ascii=True)
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return [dict(row) for row in payload]

    rows: list[dict[str, Any]] = []
    for payload in payload_list:
        entity_id = str(payload.get("id") or "")
        text = _search_text(payload)
        rows.append(
            {
                "id": entity_id,
                "tokens": _tokens(text),
                "exact_terms": sorted(set(_tokens(text))),
                "trigrams": _trigrams(text),
                "metadata": {
                    "project_id": payload.get("project_name")
                    or (payload.get("metadata") or {}).get("project_name")
                    if isinstance(payload.get("metadata"), dict)
                    else payload.get("project_name"),
                    "truth_status": payload.get("status") or "pending",
                    "confidence": payload.get("confidence"),
                },
            }
        )
    return rows


def fuse_hybrid_rrf(
    candidate_ids: Iterable[str],
    *,
    fts_rank: dict[str, int],
    vec_rank: dict[str, int],
    fts_confidence: dict[str, float],
    vec_confidence: dict[str, float],
    rrf_k: float = 40.0,
    fts_weight: float = 2.0,
    vector_weight: float = 6.0,
    limit: int,
) -> list[tuple[str, float]]:
    """Weighted confidence RRF used by hybrid search."""

    candidate_list = list(candidate_ids)
    native = _native()
    if native is not None and hasattr(native, "fuse_hybrid_rrf"):
        payload = native.fuse_hybrid_rrf(
            json.dumps(
                {
                    "candidate_ids": candidate_list,
                    "fts_rank": fts_rank,
                    "vec_rank": vec_rank,
                    "fts_confidence": fts_confidence,
                    "vec_confidence": vec_confidence,
                    "rrf_k": rrf_k,
                    "fts_weight": fts_weight,
                    "vector_weight": vector_weight,
                    "limit": limit,
                },
                ensure_ascii=True,
            )
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return [(str(row_id), float(score)) for row_id, score in payload]

    fused_scores: dict[str, float] = {}
    for row_id in candidate_list:
        score = 0.0
        if row_id in fts_rank:
            score += (
                fts_weight
                * fts_confidence.get(row_id, 1.0)
                / (rrf_k + fts_rank[row_id])
            )
        if row_id in vec_rank:
            score += (
                vector_weight
                * vec_confidence.get(row_id, 1.0)
                / (rrf_k + vec_rank[row_id])
            )
        fused_scores[row_id] = score

    ranked = sorted(fused_scores.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:limit]


def batch_cosine_topk(
    query: Sequence[float],
    embeddings: dict[str, Sequence[float]],
) -> dict[str, float]:
    """Cosine similarity for a query vector against many document embeddings."""

    if not embeddings:
        return {}

    native = _native()
    if native is not None and hasattr(native, "batch_cosine_topk"):
        serializable = {
            row_id: _embedding_as_list(embedding)
            for row_id, embedding in embeddings.items()
        }
        payload = native.batch_cosine_topk(
            json.dumps([float(value) for value in query], ensure_ascii=True),
            json.dumps(serializable, ensure_ascii=True),
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return {str(row_id): float(score) for row_id, score in dict(payload).items()}

    try:
        import numpy as np
    except ImportError:
        return _batch_cosine_topk_python(query, embeddings)

    query_arr = np.asarray(query, dtype=np.float32)
    row_ids = list(embeddings.keys())
    matrix = np.stack(
        [np.asarray(embeddings[row_id], dtype=np.float32) for row_id in row_ids],
        axis=0,
    )
    query_norm = float(np.linalg.norm(query_arr))
    if query_norm == 0.0:
        return {row_id: 0.0 for row_id in row_ids}

    norms = np.linalg.norm(matrix, axis=1)
    dots = matrix @ query_arr
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = dots / (norms * query_norm)
    sims = np.where(norms == 0.0, 0.0, sims)
    return {row_id: float(sim) for row_id, sim in zip(row_ids, sims)}


def reciprocal_rank_fusion(
    ranked_lists: Iterable[Iterable[str]],
    *,
    k: int = 60,
) -> dict[str, float]:
    """Return deterministic RRF scores for ranked source-id lists."""

    native = _native()
    ranked_lists_list = [list(ranked) for ranked in ranked_lists]
    if native is not None and hasattr(native, "reciprocal_rank_fusion"):
        payload = native.reciprocal_rank_fusion(
            json.dumps(ranked_lists_list, ensure_ascii=True),
            float(k),
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, list):
            return {str(item_id): float(score) for item_id, score in payload}
        return {str(item_id): float(score) for item_id, score in dict(payload).items()}

    scores: dict[str, float] = {}
    for ranked in ranked_lists_list:
        for index, item_id in enumerate(ranked, 1):
            if not item_id:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + index))
    return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0])))


def rank_candidates(
    rows: Iterable[dict[str, Any]],
    *,
    query: str,
    source_diversity_penalty: float = 0.05,
) -> list[dict[str, Any]]:
    """Apply exact boost, metadata penalty, and source diversity tie-breaking."""

    row_list = [dict(row) for row in rows]
    native = _native()
    if native is not None and hasattr(native, "rank_candidates"):
        payload = native.rank_candidates(
            json.dumps(row_list, sort_keys=True, ensure_ascii=True),
            query,
            float(source_diversity_penalty),
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return [dict(row) for row in payload]

    query_tokens = set(_tokens(query))
    ranked: list[dict[str, Any]] = []
    source_seen: dict[str, int] = {}
    for row in row_list:
        row_id = str(row.get("id") or "")
        tokens = set(str(token) for token in row.get("tokens") or [])
        exact_overlap = len(query_tokens & tokens)
        confidence = _float_or(row.get("confidence"), 0.0)
        source_id = str(row.get("source_id") or row.get("project_id") or "")
        diversity_seen = source_seen.get(source_id, 0)
        source_seen[source_id] = diversity_seen + 1
        metadata_penalty = (
            0.0
            if row.get("truth_status")
            in {None, "auto_confirmed", "user_confirmed", "confirmed_current"}
            else 0.2
        )
        score = exact_overlap + confidence - metadata_penalty - diversity_seen * source_diversity_penalty
        ranked.append({**row, "id": row_id, "score": round(score, 6)})
    ranked.sort(key=lambda item: (-_float_or(item.get("score"), 0.0), str(item.get("id"))))
    return ranked


def error_to_hm_code(exc: BaseException) -> dict[str, str]:
    """Map facade/native errors into stable HM error payloads."""

    if isinstance(exc, json.JSONDecodeError):
        return {"code": "HM-410", "message": exc.msg}
    if isinstance(exc, ValueError):
        return {"code": "HM-411", "message": str(exc)}
    return {"code": "HM-499", "message": f"{exc.__class__.__name__}: {exc}"}


def _native() -> Any | None:
    if rust_policy() == "force_python":
        return None
    try:
        return importlib.import_module(NATIVE_MODULE_NAME)
    except Exception as exc:
        if rust_policy() == "required":
            raise RustCoreRequiredError(
                "HM-203: HARNESS_MEM_RUST=required but harness_mem_core_rs is not "
                f"available ({exc.__class__.__name__}: {exc}). Install the native "
                "wheel or run: maturin develop --features python-extension"
            ) from exc
        return None


def _embedding_as_list(embedding: Sequence[float]) -> list[float]:
    try:
        return embedding.tolist()  # type: ignore[attr-defined]
    except AttributeError:
        return [float(value) for value in embedding]


def _batch_cosine_topk_python(
    query: Sequence[float],
    embeddings: dict[str, Sequence[float]],
) -> dict[str, float]:
    query_list = [float(value) for value in query]
    dot = 0.0
    norm_q = sum(value * value for value in query_list) ** 0.5
    if norm_q == 0.0:
        return {row_id: 0.0 for row_id in embeddings}

    scores: dict[str, float] = {}
    for row_id, embedding in embeddings.items():
        emb = [float(value) for value in embedding]
        norm_e = sum(value * value for value in emb) ** 0.5
        if norm_e == 0.0:
            scores[row_id] = 0.0
            continue
        dot = sum(x * y for x, y in zip(query_list, emb))
        scores[row_id] = dot / (norm_q * norm_e)
    return scores


def _search_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "raw_content",
        "content",
        "pattern",
        "trigger",
        "evidence",
        "summary",
        "activation_condition",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    steps = payload.get("steps")
    if isinstance(steps, list):
        parts.extend(str(item) for item in steps)
    return "\n".join(parts)


def _tokens(text: str) -> list[str]:
    native = _native()
    if native is not None and hasattr(native, "tokens"):
        return [str(token) for token in native.tokens(text)]

    seen: set[str] = set()
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def _trigrams(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    if not normalized:
        return []
    if len(normalized) < 3:
        return [normalized]
    return sorted({normalized[index:index + 3] for index in range(len(normalized) - 2)})


def _float_or(value: object, fallback: float) -> float:
    if isinstance(value, bool) or value is None:
        return fallback
    if not isinstance(value, (str, int, float)):
        return fallback
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(result):
        return fallback
    return result


__all__ = [
    "JsonlScanResult",
    "RUST_CORE_API_VERSION",
    "RUST_POLICY_ENV",
    "RustCoreRequiredError",
    "RustCoreStatus",
    "RustPolicy",
    "batch_cosine_topk",
    "build_bulk_index_rows",
    "error_to_hm_code",
    "fuse_hybrid_rrf",
    "rank_candidates",
    "reciprocal_rank_fusion",
    "rust_core_status",
    "rust_policy",
    "scan_jsonl",
]
