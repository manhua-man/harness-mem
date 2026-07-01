"""Manifest-last Local Memory Index Fabric MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.rust_core import build_bulk_index_rows


INDEX_FABRIC_SCHEMA_VERSION = 1
CURRENT_MANIFEST_NAME = "current-manifest.json"


@dataclass(frozen=True)
class IndexSidecar:
    name: str
    kind: str
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexSidecar":
        return cls(
            name=str(data["name"]),
            kind=str(data["kind"]),
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
        )


@dataclass(frozen=True)
class BuildMetrics:
    source_file_count: int
    entity_count: int
    sidecar_count: int
    build_ms: int
    first_lazy_load: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file_count": self.source_file_count,
            "entity_count": self.entity_count,
            "sidecar_count": self.sidecar_count,
            "build_ms": self.build_ms,
            "first_lazy_load": self.first_lazy_load,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildMetrics":
        return cls(
            source_file_count=int(data["source_file_count"]),
            entity_count=int(data["entity_count"]),
            sidecar_count=int(data["sidecar_count"]),
            build_ms=int(data["build_ms"]),
            first_lazy_load=bool(data.get("first_lazy_load", False)),
        )


@dataclass(frozen=True)
class IndexManifest:
    schema_version: int
    generation_id: str
    source_fingerprint: str
    committed_at: str
    backend: str
    sidecars: list[IndexSidecar]
    build_metrics: BuildMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation_id": self.generation_id,
            "source_fingerprint": self.source_fingerprint,
            "committed_at": self.committed_at,
            "backend": self.backend,
            "sidecars": [sidecar.to_dict() for sidecar in self.sidecars],
            "build_metrics": self.build_metrics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexManifest":
        return cls(
            schema_version=int(data["schema_version"]),
            generation_id=str(data["generation_id"]),
            source_fingerprint=str(data["source_fingerprint"]),
            committed_at=str(data["committed_at"]),
            backend=str(data.get("backend") or "local-index-fabric"),
            sidecars=[
                IndexSidecar.from_dict(item)
                for item in list(data.get("sidecars") or [])
            ],
            build_metrics=BuildMetrics.from_dict(dict(data["build_metrics"])),
        )


def source_fingerprint(source_dir: Path) -> str:
    """Return stable fingerprint for JSON source files under ``source_dir``."""

    source_dir = Path(source_dir)
    digest = hashlib.sha256()
    for path in sorted(source_dir.rglob("*.json")):
        if not path.is_file():
            continue
        rel = path.relative_to(source_dir).as_posix()
        data = path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_current_manifest(index_dir: Path) -> IndexManifest | None:
    """Load the visible manifest; interrupted generations are ignored."""

    manifest_path = Path(index_dir) / CURRENT_MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return IndexManifest.from_dict(data)


def ensure_index_current(source_dir: Path, index_dir: Path) -> tuple[IndexManifest, bool]:
    """Return current manifest, lazily rebuilding when the source drifts."""

    current = load_current_manifest(index_dir)
    fingerprint = source_fingerprint(source_dir)
    if current is not None and current.source_fingerprint == fingerprint:
        return current, False
    return build_index_generation(
        source_dir,
        index_dir,
        source_fingerprint_value=fingerprint,
        first_lazy_load=current is None,
    ), True


def build_index_generation(
    source_dir: Path,
    index_dir: Path,
    *,
    generation_id: str | None = None,
    source_fingerprint_value: str | None = None,
    first_lazy_load: bool = False,
) -> IndexManifest:
    """Build sidecars and atomically publish manifest last."""

    started = datetime.now(timezone.utc)
    source_dir = Path(source_dir)
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    generation_id = generation_id or f"gen-{uuid4().hex}"
    generation_dir = index_dir / "generations" / generation_id
    generation_dir.mkdir(parents=True, exist_ok=True)

    payloads = _load_payloads(source_dir)
    bulk_rows = _bulk_rows(payloads)
    sidecar_specs = {
        "exact.bin": ("exact", _exact_postings_from_rows(bulk_rows)),
        "word.bin": ("word", _word_postings_from_rows(bulk_rows)),
        "trigram.bin": ("trigram", _trigram_postings_from_rows(bulk_rows)),
        "graph.bin": ("graph", _graph_edges(payloads)),
    }
    sidecars: list[IndexSidecar] = []
    for filename, (kind, payload) in sidecar_specs.items():
        path = generation_dir / filename
        path.write_bytes(_sidecar_bytes(payload))
        sidecars.append(
            IndexSidecar(
                name=filename,
                kind=kind,
                path=path.relative_to(index_dir).as_posix(),
                sha256=_sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    manifest = IndexManifest(
        schema_version=INDEX_FABRIC_SCHEMA_VERSION,
        generation_id=generation_id,
        source_fingerprint=source_fingerprint_value or source_fingerprint(source_dir),
        committed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        backend="local-index-fabric",
        sidecars=sidecars,
        build_metrics=BuildMetrics(
            source_file_count=len(payloads),
            entity_count=len(payloads),
            sidecar_count=len(sidecars),
            build_ms=elapsed_ms,
            first_lazy_load=first_lazy_load,
        ),
    )
    manifest_tmp = index_dir / f".{CURRENT_MANIFEST_NAME}.tmp"
    manifest_tmp.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_tmp.replace(index_dir / CURRENT_MANIFEST_NAME)
    return manifest


def _load_payloads(source_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(Path(source_dir).rglob("*.json")):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data["_source_relpath"] = path.relative_to(source_dir).as_posix()
            payloads.append(data)
    return payloads


def _normalized_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for payload in payloads:
        item = dict(payload)
        if not item.get("id"):
            item["id"] = str(item.get("_source_relpath") or "")
        normalized.append(item)
    return normalized


def _bulk_rows(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return build_bulk_index_rows(_normalized_payloads(payloads))


def _exact_postings_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    postings: dict[str, list[str]] = {}
    for row in rows:
        entity_id = str(row.get("id") or "")
        for token in row.get("tokens") or []:
            postings.setdefault(str(token), []).append(entity_id)
    return _sorted_postings(postings)


def _word_postings_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return _exact_postings_from_rows(rows)


def _trigram_postings_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    postings: dict[str, list[str]] = {}
    for row in rows:
        entity_id = str(row.get("id") or "")
        for trigram in row.get("trigrams") or []:
            postings.setdefault(str(trigram), []).append(entity_id)
    return _sorted_postings(postings)


def _graph_edges(payloads: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for payload in payloads:
        if not all(key in payload for key in ("source_entity", "target_entity", "relation_type")):
            continue
        edges.append(
            {
                "id": str(payload.get("id") or ""),
                "source": str(payload["source_entity"]),
                "target": str(payload["target_entity"]),
                "relation": str(payload["relation_type"]),
            }
        )
    return sorted(edges, key=lambda row: (row["source"], row["relation"], row["target"], row["id"]))


def _sorted_postings(postings: dict[str, list[str]]) -> dict[str, list[str]]:
    return {
        key: sorted(set(values))
        for key, values in sorted(postings.items(), key=lambda item: item[0])
    }


def _sidecar_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
