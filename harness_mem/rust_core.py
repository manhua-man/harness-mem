"""Stable Python facade for the optional v4.0 Rust core.

The native extension is optional in v4.0.x.  This module exposes the same
deterministic data-work API whether ``harness_mem_core_rs`` is installed or the
pure-Python fallback is used, so runtime read paths and doctor can report the
mode without hard-failing on platforms that do not have a wheel yet.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import math
import re
from typing import Any, Iterable


RUST_CORE_API_VERSION = "v4.0.2"
NATIVE_MODULE_NAME = "harness_mem_core_rs"


@dataclass(frozen=True)
class RustCoreStatus:
    api_version: str
    mode: str
    native_module: str
    available: bool
    fallback_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "mode": self.mode,
            "native_module": self.native_module,
            "available": self.available,
            "fallback_reason": self.fallback_reason,
        }


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
    """Return native/fallback mode without importing the extension globally."""

    try:
        module = importlib.import_module(NATIVE_MODULE_NAME)
    except Exception as exc:  # noqa: BLE001 - import failures are status, not crash.
        return RustCoreStatus(
            api_version=RUST_CORE_API_VERSION,
            mode="python_fallback",
            native_module=NATIVE_MODULE_NAME,
            available=False,
            fallback_reason=f"{exc.__class__.__name__}: {exc}",
        )
    version = getattr(module, "api_version", lambda: RUST_CORE_API_VERSION)
    return RustCoreStatus(
        api_version=str(version()),
        mode="rust",
        native_module=NATIVE_MODULE_NAME,
        available=True,
        fallback_reason=None,
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

    rows: list[dict[str, Any]] = []
    for payload in payloads:
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
                    "truth_status": payload.get("status") or "accepted",
                    "confidence": payload.get("confidence"),
                },
            }
        )
    return rows


def reciprocal_rank_fusion(
    ranked_lists: Iterable[Iterable[str]],
    *,
    k: int = 60,
) -> dict[str, float]:
    """Return deterministic RRF scores for ranked source-id lists."""

    scores: dict[str, float] = {}
    for ranked in ranked_lists:
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

    query_tokens = set(_tokens(query))
    ranked: list[dict[str, Any]] = []
    source_seen: dict[str, int] = {}
    for row in rows:
        row_id = str(row.get("id") or "")
        tokens = set(str(token) for token in row.get("tokens") or [])
        exact_overlap = len(query_tokens & tokens)
        confidence = _float_or(row.get("confidence"), 0.0)
        source_id = str(row.get("source_id") or row.get("project_id") or "")
        diversity_seen = source_seen.get(source_id, 0)
        source_seen[source_id] = diversity_seen + 1
        metadata_penalty = 0.0 if row.get("truth_status") in {None, "accepted", "confirmed_current"} else 0.2
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
    try:
        return importlib.import_module(NATIVE_MODULE_NAME)
    except Exception:
        return None


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
    "RustCoreStatus",
    "build_bulk_index_rows",
    "error_to_hm_code",
    "rank_candidates",
    "reciprocal_rank_fusion",
    "rust_core_status",
    "scan_jsonl",
]
