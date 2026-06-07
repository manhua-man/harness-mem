"""Knowledge-cache boundary helpers.

This module defines the boundary between canonical truth sources
(``accepted memory`` + curated docs) and the generated knowledge cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

SYNC_MAP_FILENAME = "sync-map.json"
SOURCE_MANIFEST_FILENAME = "source-manifest.json"
GENERATED_INDEX_FILENAME = "index.json"
KEEP_FILENAME = ".keep"
GENERATED_CLAIMS_FILENAME = "claims.json"
GENERATED_TOPICS_FILENAME = "topics.json"
GENERATED_ENTITIES_FILENAME = "entities.json"
GENERATED_SOURCE_MAP_FILENAME = "source-map.json"
GENERATED_CLAIM_DIFF_FILENAME = "claim-diff.json"
COMPILED_AUTHORITY = "generated_claim"
COMPACT_RENDERER_NAME = "compact"


@dataclass(frozen=True)
class KnowledgeSourceEntry:
    """One knowledge-cache source boundary entry."""

    source_id: str
    source_kind: str
    authority: str
    label: str
    source_path: str | None
    target_path: str
    source_hash: str
    exists: bool
    mtime: str | None = None
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "authority": self.authority,
            "label": self.label,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "source_hash": self.source_hash,
            "exists": self.exists,
            "mtime": self.mtime,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class KnowledgeCachePaths:
    """Concrete paths for a project's knowledge-cache boundary."""

    cache_root: Path
    manual_root: Path
    generated_root: Path
    sync_map_path: Path
    source_manifest_path: Path
    generated_index_path: Path


@dataclass(frozen=True)
class GeneratedClaim:
    """One generated wiki-bridge claim with explicit drilldown provenance."""

    claim_id: str
    claim_kind: str
    authority: str
    text: str
    topics: tuple[str, ...]
    entities: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...]
    citation_spans: tuple[dict[str, Any], ...] = ()
    confidence: float = 0.7
    staleness: dict[str, Any] | None = None
    content_hash: str = ""
    cache_status: str = "compiled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_kind": self.claim_kind,
            "authority": self.authority,
            "text": self.text,
            "topics": list(self.topics),
            "entities": list(self.entities),
            "source_refs": [dict(item) for item in self.source_refs],
            "citation_spans": [dict(item) for item in self.citation_spans],
            "confidence": self.confidence,
            "staleness": dict(self.staleness or {}),
            "content_hash": self.content_hash,
            "cache_status": self.cache_status,
        }


@dataclass(frozen=True)
class CompactWakePayload:
    """Read-only compact wake material compiled from generated wiki artifacts."""

    project_name: str
    authority: str
    claim_count: int
    topic_count: int
    entity_count: int
    claims: tuple[dict[str, Any], ...]
    topics: tuple[dict[str, Any], ...]
    entities: tuple[dict[str, Any], ...]
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "authority": self.authority,
            "claim_count": self.claim_count,
            "topic_count": self.topic_count,
            "entity_count": self.entity_count,
            "claims": [dict(item) for item in self.claims],
            "topics": [dict(item) for item in self.topics],
            "entities": [dict(item) for item in self.entities],
            "source_ids": list(self.source_ids),
        }


def knowledge_cache_paths(data_dir: Path, project_name: str) -> KnowledgeCachePaths:
    """Return the project-scoped knowledge-cache paths without creating them."""
    safe_project = _safe_project_slug(project_name)
    cache_root = Path(data_dir) / "projects" / safe_project / "knowledge-cache"
    manual_root = cache_root / "manual"
    generated_root = cache_root / "generated"
    return KnowledgeCachePaths(
        cache_root=cache_root,
        manual_root=manual_root,
        generated_root=generated_root,
        sync_map_path=cache_root / SYNC_MAP_FILENAME,
        source_manifest_path=cache_root / SOURCE_MANIFEST_FILENAME,
        generated_index_path=generated_root / GENERATED_INDEX_FILENAME,
    )


def ensure_knowledge_cache_layout(paths: KnowledgeCachePaths) -> None:
    """Create the v2.6.0 manual/generated split and metadata placeholders."""
    paths.manual_root.mkdir(parents=True, exist_ok=True)
    paths.generated_root.mkdir(parents=True, exist_ok=True)
    _ensure_keep_file(paths.manual_root / KEEP_FILENAME)
    _ensure_keep_file(paths.generated_root / KEEP_FILENAME)
    if not paths.generated_index_path.exists():
        payload = {
            "tracked_outputs": [],
            "updated_at": _utc_now().isoformat(),
        }
        paths.generated_index_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )


def load_compact_wake_payload(
    data_dir: Path,
    *,
    project_name: str,
    max_claims: int = 5,
    max_topics: int = 5,
    max_entities: int = 5,
) -> CompactWakePayload | None:
    """Load compact wake material from generated wiki-bridge outputs.

    Returns ``None`` when the generated wiki bridge has not been built yet or
    when the required generated artifacts are missing or malformed.
    """
    paths = knowledge_cache_paths(data_dir, project_name)
    claims_payload = _load_json(paths.generated_root / GENERATED_CLAIMS_FILENAME)
    topics_payload = _load_json(paths.generated_root / GENERATED_TOPICS_FILENAME)
    entities_payload = _load_json(paths.generated_root / GENERATED_ENTITIES_FILENAME)
    index_payload = _load_json(paths.generated_index_path)

    claims_raw = claims_payload.get("claims")
    topics_raw = topics_payload.get("topics")
    entities_raw = entities_payload.get("entities")
    if not isinstance(claims_raw, list) or not isinstance(topics_raw, list) or not isinstance(entities_raw, list):
        return None
    valid_source_hashes = _index_sources_by_id(index_payload.get("sources", []))
    readable_claims = [
        claim
        for claim in claims_raw
        if isinstance(claim, dict) and _claim_payload_has_valid_citations(claim, valid_source_hashes)
    ]

    claims = tuple(
        item
        for item in readable_claims[:max(0, max_claims)]
    )
    topics = tuple(
        item
        for item in topics_raw[:max(0, max_topics)]
        if isinstance(item, dict)
    )
    entities = tuple(
        item
        for item in entities_raw[:max(0, max_entities)]
        if isinstance(item, dict)
    )

    source_ids = _collect_compact_source_ids(claims)
    return CompactWakePayload(
        project_name=project_name,
        authority=str(claims_payload.get("authority") or COMPILED_AUTHORITY),
        claim_count=len(readable_claims),
        topic_count=len(topics_raw),
        entity_count=len(entities_raw),
        claims=claims,
        topics=topics,
        entities=entities,
        source_ids=source_ids,
    )


async def build_knowledge_sources(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    profile: ProjectProfile | None,
    project_root: Path | None,
) -> list[KnowledgeSourceEntry]:
    """Build the current source list and source hashes for a project."""
    sources: list[KnowledgeSourceEntry] = []

    accepted_hash = await _hash_accepted_memory_snapshot(backend, project_name)
    sources.append(
        KnowledgeSourceEntry(
            source_id=f"accepted-memory://{project_name}",
            source_kind="accepted_memory",
            authority="accepted_truth",
            label="Accepted memory snapshot",
            source_path=None,
            target_path="generated/accepted-memory",
            source_hash=accepted_hash,
            exists=True,
            provenance={
                "project_name": project_name,
                "producer": "harness-mem structured_store",
            },
        )
    )

    for curated_path in (profile.curated_doc_paths if profile else []):
        resolved = _resolve_curated_path(curated_path, project_root)
        exists = resolved.exists()
        source_mtime = _path_mtime(resolved) if exists else None
        sources.append(
            KnowledgeSourceEntry(
                source_id=f"curated-doc://{_normalize_source_label(curated_path)}",
                source_kind="curated_doc",
                authority="manual",
                label=curated_path,
                source_path=str(resolved),
                target_path=f"generated/curated-docs/{_target_slug(curated_path)}",
                source_hash=_hash_path(resolved) if exists else "missing",
                exists=exists,
                mtime=source_mtime,
                provenance={
                    "project_name": project_name,
                    "profile_field": "curated_doc_paths",
                    "project_root": str(project_root) if project_root else None,
                },
            )
        )

    sources.sort(key=lambda entry: (entry.source_kind, entry.source_id))
    return sources


def write_knowledge_cache_boundary(
    paths: KnowledgeCachePaths,
    *,
    project_name: str,
    sources: list[KnowledgeSourceEntry],
) -> None:
    """Persist sync-map and source manifest for incremental compile checks."""
    ensure_knowledge_cache_layout(paths)
    sync_map_payload = {
        "project_name": project_name,
        "manual_root": str(paths.manual_root),
        "generated_root": str(paths.generated_root),
        "updated_at": _utc_now().isoformat(),
        "sources": [
            {
                "source_id": source.source_id,
                "source_kind": source.source_kind,
                "authority": source.authority,
                "label": source.label,
                "source_path": source.source_path,
                "target_path": source.target_path,
            }
            for source in sources
        ],
    }
    manifest_payload = {
        "project_name": project_name,
        "updated_at": _utc_now().isoformat(),
        "sources": [source.to_dict() for source in sources],
    }
    paths.sync_map_path.write_text(
        json.dumps(sync_map_payload, indent=2),
        encoding="utf-8",
    )
    paths.source_manifest_path.write_text(
        json.dumps(manifest_payload, indent=2),
        encoding="utf-8",
    )


async def knowledge_cache_health(
    backend: LocalMemoryBackend,
    *,
    data_dir: Path,
    project_name: str,
    profile: ProjectProfile | None,
    project_root: Path | None,
) -> dict[str, Any]:
    """Return a read-only v2.6.0 health report for doctor and MCP surfaces."""
    paths = knowledge_cache_paths(data_dir, project_name)
    current_sources = await build_knowledge_sources(
        backend,
        project_name=project_name,
        profile=profile,
        project_root=project_root,
    )
    stored_manifest = _load_json(paths.source_manifest_path)
    stored_sources = {
        str(item.get("source_id")): item
        for item in stored_manifest.get("sources", [])
        if isinstance(item, dict) and item.get("source_id")
    }

    stale_sources: list[dict[str, Any]] = []
    missing_sources: list[dict[str, Any]] = []
    for source in current_sources:
        if not source.exists:
            missing_sources.append(source.to_dict())
            stale_sources.append(source.to_dict())
            continue
        previous = stored_sources.get(source.source_id)
        if previous is None or previous.get("source_hash") != source.source_hash:
            stale_sources.append(source.to_dict())

    tracked_outputs = _tracked_outputs(paths.generated_index_path)
    generated_files = _generated_files(paths.generated_root)
    orphaned_outputs = [
        str(path)
        for path in generated_files
        if _normalize_relative_generated_path(path, paths.generated_root) not in tracked_outputs
    ]
    generated_index = _load_json(paths.generated_index_path)
    generated_counts = generated_index.get("counts", {})
    if not isinstance(generated_counts, dict):
        generated_counts = {}
    compile_metrics = generated_index.get("compile_metrics", {})
    if not isinstance(compile_metrics, dict):
        compile_metrics = {}
    freshness = generated_index.get("freshness", {})
    if not isinstance(freshness, dict):
        freshness = {}
    source_map_payload = _load_json(paths.generated_root / GENERATED_SOURCE_MAP_FILENAME)
    source_map_entries = source_map_payload.get("sources", [])
    if not isinstance(source_map_entries, list):
        source_map_entries = []

    return {
        "project_name": project_name,
        "cache_root": str(paths.cache_root),
        "manual_root": str(paths.manual_root),
        "generated_root": str(paths.generated_root),
        "sync_map_path": str(paths.sync_map_path),
        "source_manifest_path": str(paths.source_manifest_path),
        "prepared": paths.sync_map_path.exists() and paths.source_manifest_path.exists(),
        "source_count": len(current_sources),
        "curated_doc_count": sum(1 for source in current_sources if source.source_kind == "curated_doc"),
        "stale_source_count": len(stale_sources),
        "missing_source_count": len(missing_sources),
        "tracked_output_count": len(tracked_outputs),
        "generated_claim_count": int(generated_counts.get("claims", 0) or 0),
        "generated_topic_count": int(generated_counts.get("topics", 0) or 0),
        "generated_entity_count": int(generated_counts.get("entities", 0) or 0),
        "compiled_claim_count": int(generated_counts.get("compiled_claims", generated_counts.get("claims", 0)) or 0),
        "invalid_claim_count": int(generated_counts.get("invalid_claims", 0) or 0),
        "source_map_count": len(source_map_entries),
        "hash_drift_count": int(freshness.get("hash_drift_count", len(stale_sources)) or 0),
        "cache_hit_ratio": float(compile_metrics.get("cache_hit_ratio", 0.0) or 0.0),
        "compile_duration_ms": int(compile_metrics.get("duration_ms", 0) or 0),
        "output_token_estimate": int(compile_metrics.get("output_token_estimate", 0) or 0),
        "orphaned_output_count": len(orphaned_outputs),
        "sources": [source.to_dict() for source in current_sources],
        "stale_sources": stale_sources,
        "missing_sources": missing_sources,
        "orphaned_outputs": orphaned_outputs,
        "compile_metrics": compile_metrics,
        "freshness": freshness,
    }


def cleanup_generated_outputs(
    data_dir: Path,
    *,
    project_name: str,
    apply: bool,
) -> dict[str, Any]:
    """Delete orphaned generated outputs without touching canonical storage."""
    paths = knowledge_cache_paths(data_dir, project_name)
    tracked_outputs = _tracked_outputs(paths.generated_index_path)
    generated_files = _generated_files(paths.generated_root)
    orphaned = [
        path
        for path in generated_files
        if _normalize_relative_generated_path(path, paths.generated_root) not in tracked_outputs
    ]
    removed: list[str] = []

    if apply:
        for file_path in orphaned:
            file_path.unlink(missing_ok=True)
            removed.append(str(file_path))
        _remove_empty_dirs(paths.generated_root)

    return {
        "project_name": project_name,
        "generated_root": str(paths.generated_root),
        "apply": apply,
        "orphaned_count": len(orphaned),
        "removed_count": len(removed),
        "orphaned_outputs": [str(path) for path in orphaned],
        "removed_outputs": removed,
    }


async def rebuild_wiki_bridge(
    backend: LocalMemoryBackend,
    *,
    data_dir: Path,
    project_name: str,
    profile: ProjectProfile | None,
    project_root: Path | None,
) -> dict[str, Any]:
    """Compile accepted truth + curated docs into generated wiki-bridge artifacts."""
    started = time.perf_counter()
    paths = knowledge_cache_paths(data_dir, project_name)
    ensure_knowledge_cache_layout(paths)
    previous_index = _load_json(paths.generated_index_path)
    previous_sources = _index_sources_by_id(previous_index.get("sources", []))
    previous_claims_payload = _load_json(paths.generated_root / GENERATED_CLAIMS_FILENAME)
    previous_claims = _index_claims_by_id(previous_claims_payload.get("claims", []))
    sources = await build_knowledge_sources(
        backend,
        project_name=project_name,
        profile=profile,
        project_root=project_root,
    )
    write_knowledge_cache_boundary(
        paths,
        project_name=project_name,
        sources=sources,
    )

    memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
    )
    confirmed_rules = await backend.structured_store.list_confirmed_rules(project_name)
    relation_facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=100000,
    )

    claims: list[GeneratedClaim] = []
    claims.extend(_claims_from_memory_entries(memory_entries, sources=sources))
    claims.extend(_claims_from_confirmed_rules(confirmed_rules, sources=sources))
    claims.extend(_claims_from_relation_facts(relation_facts, sources=sources))
    claims.extend(_claims_from_curated_docs(profile, project_root, sources=sources))
    claims = [_finalize_claim(claim) for claim in claims]
    valid_claims, invalid_claims = _validate_claims(claims, sources=sources)
    valid_claims = _mark_incremental_claims(
        valid_claims,
        previous_claims=previous_claims,
        previous_sources=previous_sources,
        current_sources=sources,
    )
    claim_diff = _build_claim_diff(previous_claims, valid_claims)

    topics = _build_topic_index(valid_claims)
    entities = _build_entity_index(valid_claims)
    source_map = _build_source_map(
        project_name=project_name,
        sources=sources,
        claims=valid_claims,
        invalid_claims=invalid_claims,
    )

    claims_payload = {
        "project_name": project_name,
        "authority": COMPILED_AUTHORITY,
        "updated_at": _utc_now().isoformat(),
        "compiler_version": "v3.2",
        "claims": [claim.to_dict() for claim in valid_claims],
        "invalid_claims": [claim.to_dict() for claim in invalid_claims],
    }
    topics_payload = {
        "project_name": project_name,
        "authority": COMPILED_AUTHORITY,
        "updated_at": _utc_now().isoformat(),
        "topics": topics,
    }
    entities_payload = {
        "project_name": project_name,
        "authority": COMPILED_AUTHORITY,
        "updated_at": _utc_now().isoformat(),
        "entities": entities,
    }

    claims_path = paths.generated_root / GENERATED_CLAIMS_FILENAME
    topics_path = paths.generated_root / GENERATED_TOPICS_FILENAME
    entities_path = paths.generated_root / GENERATED_ENTITIES_FILENAME
    source_map_path = paths.generated_root / GENERATED_SOURCE_MAP_FILENAME
    claim_diff_path = paths.generated_root / GENERATED_CLAIM_DIFF_FILENAME
    claims_path.write_text(json.dumps(claims_payload, indent=2), encoding="utf-8")
    topics_path.write_text(json.dumps(topics_payload, indent=2), encoding="utf-8")
    entities_path.write_text(json.dumps(entities_payload, indent=2), encoding="utf-8")
    source_map_path.write_text(json.dumps(source_map, indent=2), encoding="utf-8")
    claim_diff_path.write_text(json.dumps(claim_diff, indent=2), encoding="utf-8")

    tracked_outputs = [
        GENERATED_CLAIMS_FILENAME,
        GENERATED_TOPICS_FILENAME,
        GENERATED_ENTITIES_FILENAME,
        GENERATED_SOURCE_MAP_FILENAME,
        GENERATED_CLAIM_DIFF_FILENAME,
    ]
    cache_hit_count = sum(1 for claim in valid_claims if claim.cache_status == "reused")
    compile_metrics = {
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "source_count": len(sources),
        "claim_count": len(valid_claims),
        "invalid_claim_count": len(invalid_claims),
        "cache_hit_count": cache_hit_count,
        "cache_miss_count": max(0, len(valid_claims) - cache_hit_count),
        "cache_hit_ratio": (cache_hit_count / len(valid_claims)) if valid_claims else 0.0,
        "output_token_estimate": _estimate_compact_output_tokens(valid_claims, topics, entities),
    }
    freshness = {
        "stale_source_count": 0,
        "missing_source_count": sum(1 for source in sources if not source.exists),
        "hash_drift_count": _hash_drift_count(previous_sources, sources),
        "orphaned_output_count": len([
            path
            for path in _generated_files(paths.generated_root)
            if _normalize_relative_generated_path(path, paths.generated_root) not in set(tracked_outputs)
        ]),
    }
    generated_index_payload = {
        "project_name": project_name,
        "authority": COMPILED_AUTHORITY,
        "updated_at": _utc_now().isoformat(),
        "compiler_version": "v3.2",
        "tracked_outputs": tracked_outputs,
        "counts": {
            "claims": len(valid_claims),
            "compiled_claims": len(valid_claims),
            "invalid_claims": len(invalid_claims),
            "topics": len(topics),
            "entities": len(entities),
            "sources": len(sources),
        },
        "compile_metrics": compile_metrics,
        "freshness": freshness,
        "claim_diff": claim_diff["summary"],
        "sources": [
            {
                "source_id": source.source_id,
                "source_hash": source.source_hash,
                "source_kind": source.source_kind,
                "authority": source.authority,
                "exists": source.exists,
                "mtime": source.mtime,
            }
            for source in sources
        ],
    }
    paths.generated_index_path.write_text(
        json.dumps(generated_index_payload, indent=2),
        encoding="utf-8",
    )
    return {
        "project_name": project_name,
        "claims_path": str(claims_path),
        "topics_path": str(topics_path),
        "entities_path": str(entities_path),
        "source_map_path": str(source_map_path),
        "claim_diff_path": str(claim_diff_path),
        "index_path": str(paths.generated_index_path),
        "claim_count": len(valid_claims),
        "invalid_claim_count": len(invalid_claims),
        "topic_count": len(topics),
        "entity_count": len(entities),
        "source_count": len(sources),
        "cache_hit_ratio": compile_metrics["cache_hit_ratio"],
        "compile_duration_ms": compile_metrics["duration_ms"],
        "output_token_estimate": compile_metrics["output_token_estimate"],
        "claim_diff": claim_diff["summary"],
        "tracked_outputs": tracked_outputs,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _tracked_outputs(index_path: Path) -> set[str]:
    payload = _load_json(index_path)
    tracked = payload.get("tracked_outputs", [])
    if not isinstance(tracked, list):
        return set()
    return {
        str(item).replace("\\", "/")
        for item in tracked
        if isinstance(item, str) and item.strip()
    }


def _generated_files(generated_root: Path) -> list[Path]:
    if not generated_root.exists():
        return []
    files = [
        path
        for path in generated_root.rglob("*")
        if path.is_file() and path.name not in {GENERATED_INDEX_FILENAME, KEEP_FILENAME}
    ]
    return sorted(files)


def _normalize_relative_generated_path(path: Path, generated_root: Path) -> str:
    return str(path.relative_to(generated_root)).replace("\\", "/")


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted(
        [path for path in root.rglob("*") if path.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        with os.scandir(directory) as entries:
            if any(True for _ in entries):
                continue
        directory.rmdir()


async def _hash_accepted_memory_snapshot(
    backend: LocalMemoryBackend,
    project_name: str,
) -> str:
    entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
    )
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    relation_facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=100000,
    )
    payload = {
        "memory_entries": [
            {
                "id": entry.id,
                "category": entry.category,
                "content": entry.content,
                "valid_to": entry.valid_to.isoformat() if entry.valid_to else None,
                "supersedes": list(entry.supersedes or []),
                "superseded_by": list(entry.superseded_by or []),
            }
            for entry in entries
        ],
        "confirmed_rules": [
            {
                "id": rule.id,
                "pattern": rule.pattern,
                "trigger": rule.trigger,
                "valid_to": rule.valid_to.isoformat() if rule.valid_to else None,
                "supersedes": list(rule.supersedes or []),
                "superseded_by": list(rule.superseded_by or []),
            }
            for rule in rules
        ],
        "relation_facts": [
            {
                "id": fact.id,
                "source_entity": fact.source_entity,
                "relation_type": fact.relation_type,
                "target_entity": fact.target_entity,
                "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
            }
            for fact in relation_facts
        ],
    }
    return _hash_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))


def _resolve_curated_path(curated_path: str, project_root: Path | None) -> Path:
    raw = Path(curated_path)
    if raw.is_absolute():
        return raw
    if project_root is not None:
        return (project_root / raw).resolve()
    return raw.resolve()


def _hash_path(path: Path) -> str:
    if path.is_file():
        return _hash_bytes(path.read_bytes())
    if path.is_dir():
        digest = hashlib.sha256()
        for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(str(file_path.relative_to(path)).replace("\\", "/").encode("utf-8"))
            digest.update(file_path.read_bytes())
        return digest.hexdigest()
    return "missing"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_source_label(value: str) -> str:
    return value.replace("\\", "/").strip()


def _target_slug(value: str) -> str:
    normalized = _normalize_source_label(value).lower()
    parts = [
        character if character.isalnum() else "-"
        for character in normalized
    ]
    collapsed = "".join(parts).strip("-")
    while "--" in collapsed:
        collapsed = collapsed.replace("--", "-")
    return collapsed or "curated-doc"


def _path_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _source_by_id(
    sources: list[KnowledgeSourceEntry],
    source_id: str,
) -> KnowledgeSourceEntry | None:
    for source in sources:
        if source.source_id == source_id:
            return source
    return None


def _accepted_memory_source_ref(sources: list[KnowledgeSourceEntry]) -> dict[str, str]:
    for source in sources:
        if source.source_kind == "accepted_memory":
            return {
                "source_id": source.source_id,
                "source_hash": source.source_hash,
            }
    return {"source_id": "accepted-memory://unknown", "source_hash": "missing"}


def _record_citation_span(source_ref: dict[str, Any], *, record_id: str) -> dict[str, Any]:
    return {
        "source_id": str(source_ref.get("source_id") or ""),
        "source_hash": str(source_ref.get("source_hash") or ""),
        "record_id": record_id,
        "quote_hash": _hash_bytes(record_id.encode("utf-8")),
    }


def _truth_staleness(valid_to: datetime | None) -> dict[str, Any]:
    return {
        "status": "historical" if valid_to else "current",
        "valid_to": valid_to.isoformat() if valid_to else None,
    }


def _claims_from_memory_entries(
    entries: list[MemoryEntry],
    *,
    sources: list[KnowledgeSourceEntry],
) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for entry in entries:
        text = entry.content.strip()
        if not text:
            continue
        snapshot_ref = _accepted_memory_source_ref(sources)
        source_ref = {
            "source_kind": "memory_entry",
            "source_id": snapshot_ref["source_id"],
            "record_id": entry.id,
            "label": entry.category,
            "source_hash": snapshot_ref["source_hash"],
            "drilldown": {"memory_entry_id": entry.id},
        }
        citation = _record_citation_span(source_ref, record_id=entry.id)
        claims.append(
            GeneratedClaim(
                claim_id=f"memory-entry:{entry.id}",
                claim_kind="memory_entry",
                authority=COMPILED_AUTHORITY,
                text=text,
                topics=tuple(_topics_for_memory_entry(entry)),
                entities=tuple(_extract_entities(text)),
                source_refs=(source_ref,),
                citation_spans=(citation,),
                confidence=entry.confidence,
                staleness=_truth_staleness(entry.valid_to),
            )
        )
    return claims


def _claims_from_confirmed_rules(
    rules: list[ConfirmedRule],
    *,
    sources: list[KnowledgeSourceEntry],
) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for rule in rules:
        pattern = rule.pattern.strip()
        trigger = rule.trigger.strip()
        if not pattern and not trigger:
            continue
        text = f"When {trigger}, {pattern}".strip(", ")
        snapshot_ref = _accepted_memory_source_ref(sources)
        source_ref = {
            "source_kind": "confirmed_rule",
            "source_id": snapshot_ref["source_id"],
            "record_id": rule.id,
            "label": trigger or "confirmed rule",
            "source_hash": snapshot_ref["source_hash"],
            "drilldown": {"confirmed_rule_id": rule.id},
        }
        citation = _record_citation_span(source_ref, record_id=rule.id)
        claims.append(
            GeneratedClaim(
                claim_id=f"confirmed-rule:{rule.id}",
                claim_kind="confirmed_rule",
                authority=COMPILED_AUTHORITY,
                text=text,
                topics=tuple(_topics_for_rule(rule)),
                entities=tuple(_extract_entities(text)),
                source_refs=(source_ref,),
                citation_spans=(citation,),
                confidence=0.9,
                staleness=_truth_staleness(rule.valid_to),
            )
        )
    return claims


def _claims_from_relation_facts(
    facts: list[RelationFact],
    *,
    sources: list[KnowledgeSourceEntry],
) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for fact in facts:
        text = f"{fact.source_entity} {fact.relation_type} {fact.target_entity}. {fact.evidence}".strip()
        snapshot_ref = _accepted_memory_source_ref(sources)
        source_ref = {
            "source_kind": "relation_fact",
            "source_id": snapshot_ref["source_id"],
            "record_id": fact.id,
            "label": fact.relation_type,
            "source_hash": snapshot_ref["source_hash"],
            "drilldown": {"relation_fact_id": fact.id},
        }
        citation = _record_citation_span(source_ref, record_id=fact.id)
        claims.append(
            GeneratedClaim(
                claim_id=f"relation-fact:{fact.id}",
                claim_kind="relation_fact",
                authority=COMPILED_AUTHORITY,
                text=text,
                topics=(fact.relation_type.lower(), "relation"),
                entities=(fact.source_entity, fact.target_entity),
                source_refs=(source_ref,),
                citation_spans=(citation,),
                confidence=fact.confidence,
                staleness=_truth_staleness(fact.valid_to),
            )
        )
    return claims


def _claims_from_curated_docs(
    profile: ProjectProfile | None,
    project_root: Path | None,
    *,
    sources: list[KnowledgeSourceEntry],
) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for curated_path in (profile.curated_doc_paths if profile else []):
        resolved = _resolve_curated_path(curated_path, project_root)
        if not resolved.exists() or not resolved.is_file():
            continue
        text = resolved.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = " ".join(lines[:3]).strip()
        if not summary:
            continue
        source = _source_by_id(
            sources,
            f"curated-doc://{_normalize_source_label(curated_path)}",
        )
        source_ref = {
            "source_kind": "curated_doc",
            "source_id": f"curated-doc://{_normalize_source_label(curated_path)}",
            "label": curated_path,
            "source_hash": source.source_hash if source else _hash_path(resolved),
            "drilldown": {"curated_doc_path": str(resolved)},
        }
        citation = {
            "source_id": source_ref["source_id"],
            "source_hash": source_ref["source_hash"],
            "line_start": 1,
            "line_end": min(3, len(lines)),
            "quote_hash": _hash_bytes(summary.encode("utf-8")),
        }
        claims.append(
            GeneratedClaim(
                claim_id=f"curated-doc:{_target_slug(curated_path)}",
                claim_kind="curated_doc",
                authority=COMPILED_AUTHORITY,
                text=summary,
                topics=tuple(_topics_for_curated_doc(curated_path, summary)),
                entities=tuple(_extract_entities(summary)),
                source_refs=(source_ref,),
                citation_spans=(citation,),
                confidence=0.65,
                staleness={"status": "current"},
            )
        )
    return claims


def render_compact_wake_payload(payload: CompactWakePayload) -> str:
    """Render opt-in compact wake text from generated wiki artifacts only."""
    lines = [
        "# Compact Wake  (generated summary, not confirmed truth)",
        (
            f"# authority: {payload.authority}  "
            f"claims={payload.claim_count} topics={payload.topic_count} entities={payload.entity_count}"
        ),
    ]

    if payload.claims:
        lines.append("# Claims")
        for claim in payload.claims:
            text = str(claim.get("text") or "").strip()
            claim_id = str(claim.get("claim_id") or "")
            topics = claim.get("topics") or []
            topic_text = ", ".join(str(item) for item in topics if str(item).strip())
            suffix = f"  [{claim_id}]" if claim_id else ""
            if topic_text:
                suffix += f"  (topics: {topic_text})"
            lines.append(f"- {text}{suffix}".rstrip())
    else:
        lines.append("# Claims")
        lines.append("_(none)_")

    if payload.topics:
        lines.append("# Topics")
        for topic in payload.topics:
            topic_name = str(topic.get("topic") or "").strip()
            claim_ids = topic.get("claim_ids") or []
            lines.append(f"- {topic_name}  [{len(claim_ids)} claims]")

    if payload.entities:
        lines.append("# Entities")
        for entity in payload.entities:
            entity_name = str(entity.get("entity") or "").strip()
            claim_ids = entity.get("claim_ids") or []
            lines.append(f"- {entity_name}  [{len(claim_ids)} claims]")

    if payload.source_ids:
        lines.append("# Source IDs")
        lines.append("- " + ", ".join(payload.source_ids))

    lines.append(
        "Note: compact wake is generated from wiki bridge artifacts and does not replace confirmed truth."
    )
    return "\n".join(lines)


def _topics_for_memory_entry(entry: MemoryEntry) -> list[str]:
    topics = [entry.category.lower()]
    topics.extend(_extract_keywords(entry.content, limit=4))
    return _unique_preserve_order(topics)


def _collect_compact_source_ids(claims: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    source_ids: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        refs = claim.get("source_refs") or []
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            source_id = str(ref.get("source_id") or "").strip()
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            source_ids.append(source_id)
    return tuple(source_ids)


def _topics_for_rule(rule: ConfirmedRule) -> list[str]:
    topics = ["rule"]
    topics.extend(_extract_keywords(rule.trigger, limit=3))
    topics.extend(_extract_keywords(rule.pattern, limit=3))
    return _unique_preserve_order(topics)


def _topics_for_curated_doc(curated_path: str, text: str) -> list[str]:
    base = Path(curated_path).stem.replace("_", " ").replace("-", " ")
    topics = _extract_keywords(base, limit=3)
    topics.extend(_extract_keywords(text, limit=4))
    return _unique_preserve_order(topics)


def _build_topic_index(claims: list[GeneratedClaim]) -> list[dict[str, Any]]:
    topic_map: dict[str, set[str]] = {}
    for claim in claims:
        for topic in claim.topics:
            topic_map.setdefault(topic, set()).add(claim.claim_id)
    return [
        {"topic": topic, "claim_ids": sorted(claim_ids)}
        for topic, claim_ids in sorted(topic_map.items())
    ]


def _build_entity_index(claims: list[GeneratedClaim]) -> list[dict[str, Any]]:
    entity_map: dict[str, set[str]] = {}
    for claim in claims:
        for entity in claim.entities:
            entity_map.setdefault(entity, set()).add(claim.claim_id)
    return [
        {"entity": entity, "claim_ids": sorted(claim_ids)}
        for entity, claim_ids in sorted(entity_map.items())
    ]


def _finalize_claim(claim: GeneratedClaim) -> GeneratedClaim:
    payload = {
        "claim_id": claim.claim_id,
        "claim_kind": claim.claim_kind,
        "text": claim.text,
        "source_refs": claim.source_refs,
        "citation_spans": claim.citation_spans,
    }
    return replace(
        claim,
        content_hash=_hash_bytes(json.dumps(payload, sort_keys=True).encode("utf-8")),
    )


def _validate_claims(
    claims: list[GeneratedClaim],
    *,
    sources: list[KnowledgeSourceEntry],
) -> tuple[list[GeneratedClaim], list[GeneratedClaim]]:
    source_hashes = {source.source_id: source.source_hash for source in sources if source.exists}
    valid: list[GeneratedClaim] = []
    invalid: list[GeneratedClaim] = []
    for claim in claims:
        if _claim_has_valid_citations(claim, source_hashes):
            valid.append(replace(claim, staleness=_merge_staleness(claim.staleness, "current")))
        else:
            invalid.append(replace(claim, staleness=_merge_staleness(claim.staleness, "invalid_citation")))
    return valid, invalid


def _claim_has_valid_citations(
    claim: GeneratedClaim,
    source_hashes: dict[str, str],
) -> bool:
    if not claim.source_refs or not claim.citation_spans:
        return False
    ref_ids = {str(ref.get("source_id") or "") for ref in claim.source_refs}
    for source_id in ref_ids:
        if not source_id or source_id not in source_hashes:
            return False
    for citation in claim.citation_spans:
        source_id = str(citation.get("source_id") or "")
        source_hash = str(citation.get("source_hash") or "")
        if not source_id or source_id not in ref_ids:
            return False
        if source_hashes.get(source_id) != source_hash:
            return False
    return True


def _claim_payload_has_valid_citations(
    claim: dict[str, Any],
    source_hashes: dict[str, dict[str, Any]],
) -> bool:
    refs = claim.get("source_refs")
    citations = claim.get("citation_spans")
    if not isinstance(refs, list) or not refs:
        return False
    if not isinstance(citations, list) or not citations:
        return False
    ref_ids = {
        str(ref.get("source_id") or "")
        for ref in refs
        if isinstance(ref, dict)
    }
    if not ref_ids:
        return False
    for citation in citations:
        if not isinstance(citation, dict):
            return False
        source_id = str(citation.get("source_id") or "")
        source_hash = str(citation.get("source_hash") or "")
        indexed = source_hashes.get(source_id)
        if not indexed or indexed.get("source_hash") != source_hash:
            return False
    return True


def _merge_staleness(
    staleness: dict[str, Any] | None,
    citation_status: str,
) -> dict[str, Any]:
    merged = dict(staleness or {})
    merged["citation_status"] = citation_status
    return merged


def _index_sources_by_id(raw_sources: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_sources, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "")
        if not source_id:
            continue
        indexed[source_id] = item
    return indexed


def _index_claims_by_id(raw_claims: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_claims, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or "")
        if not claim_id:
            continue
        indexed[claim_id] = item
    return indexed


def _mark_incremental_claims(
    claims: list[GeneratedClaim],
    *,
    previous_claims: dict[str, dict[str, Any]],
    previous_sources: dict[str, dict[str, Any]],
    current_sources: list[KnowledgeSourceEntry],
) -> list[GeneratedClaim]:
    current_source_hashes = {source.source_id: source.source_hash for source in current_sources}
    marked: list[GeneratedClaim] = []
    for claim in claims:
        previous = previous_claims.get(claim.claim_id)
        reusable = previous is not None and previous.get("content_hash") == claim.content_hash
        if reusable:
            for ref in claim.source_refs:
                source_id = str(ref.get("source_id") or "")
                if not source_id:
                    reusable = False
                    break
                if previous_sources.get(source_id, {}).get("source_hash") != current_source_hashes.get(source_id):
                    reusable = False
                    break
        marked.append(replace(claim, cache_status="reused" if reusable else "compiled"))
    return marked


def _build_claim_diff(
    previous_claims: dict[str, dict[str, Any]],
    current_claims: list[GeneratedClaim],
) -> dict[str, Any]:
    current_by_id = {claim.claim_id: claim for claim in current_claims}
    previous_ids = set(previous_claims)
    current_ids = set(current_by_id)
    added = sorted(current_ids - previous_ids)
    removed = sorted(previous_ids - current_ids)
    changed = sorted(
        claim_id
        for claim_id in previous_ids & current_ids
        if previous_claims[claim_id].get("content_hash") != current_by_id[claim_id].content_hash
    )
    unchanged = sorted((previous_ids & current_ids) - set(changed))
    return {
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": len(unchanged),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }


def _build_source_map(
    *,
    project_name: str,
    sources: list[KnowledgeSourceEntry],
    claims: list[GeneratedClaim],
    invalid_claims: list[GeneratedClaim],
) -> dict[str, Any]:
    claims_by_source: dict[str, list[str]] = {}
    invalid_by_source: dict[str, list[str]] = {}
    for claim in claims:
        for ref in claim.source_refs:
            source_id = str(ref.get("source_id") or "")
            if source_id:
                claims_by_source.setdefault(source_id, []).append(claim.claim_id)
    for claim in invalid_claims:
        for ref in claim.source_refs:
            source_id = str(ref.get("source_id") or "")
            if source_id:
                invalid_by_source.setdefault(source_id, []).append(claim.claim_id)
    return {
        "project_name": project_name,
        "authority": "generated_source_map",
        "updated_at": _utc_now().isoformat(),
        "manual_root_note": "manual sources and accepted truth remain canonical; generated outputs are derived.",
        "sources": [
            {
                **source.to_dict(),
                "claim_ids": sorted(set(claims_by_source.get(source.source_id, []))),
                "invalid_claim_ids": sorted(set(invalid_by_source.get(source.source_id, []))),
            }
            for source in sources
        ],
    }


def _hash_drift_count(
    previous_sources: dict[str, dict[str, Any]],
    current_sources: list[KnowledgeSourceEntry],
) -> int:
    drift = 0
    for source in current_sources:
        previous = previous_sources.get(source.source_id)
        if previous is not None and previous.get("source_hash") != source.source_hash:
            drift += 1
    return drift


def _estimate_compact_output_tokens(
    claims: list[GeneratedClaim],
    topics: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> int:
    text = "\n".join(
        [claim.text for claim in claims]
        + [str(topic.get("topic") or "") for topic in topics]
        + [str(entity.get("entity") or "") for entity in entities]
    )
    return max(0, round(len(text) / 4))


def _extract_entities(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][A-Za-z0-9_./-]*\b", text)
    return _unique_preserve_order(matches[:8])


def _extract_keywords(text: str, *, limit: int) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    filtered = [
        token for token in tokens
        if token not in {"the", "and", "for", "with", "that", "this", "from", "when", "into", "docs"}
    ]
    return _unique_preserve_order(filtered)[:limit]


def _unique_preserve_order(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_project_slug(project_name: str) -> str:
    return (
        project_name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "_")
    )


def _ensure_keep_file(path: Path) -> None:
    if not path.exists():
        path.write_text("", encoding="utf-8")
