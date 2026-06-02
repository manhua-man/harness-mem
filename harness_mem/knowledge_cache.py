"""Knowledge-cache boundary helpers for v2.6.0.

This module defines the boundary between canonical truth sources
(``accepted memory`` + curated docs) and the future generated knowledge cache.
v2.6.0 intentionally stops at layout, visibility, source hashing, and cleanup;
it does not compile wiki claims yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
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
COMPILED_AUTHORITY = "generated_claim"


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_kind": self.claim_kind,
            "authority": self.authority,
            "text": self.text,
            "topics": list(self.topics),
            "entities": list(self.entities),
            "source_refs": [dict(item) for item in self.source_refs],
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
        )
    )

    for curated_path in (profile.curated_doc_paths if profile else []):
        resolved = _resolve_curated_path(curated_path, project_root)
        exists = resolved.exists()
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
        "orphaned_output_count": len(orphaned_outputs),
        "sources": [source.to_dict() for source in current_sources],
        "stale_sources": stale_sources,
        "missing_sources": missing_sources,
        "orphaned_outputs": orphaned_outputs,
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
    paths = knowledge_cache_paths(data_dir, project_name)
    ensure_knowledge_cache_layout(paths)
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
    claims.extend(_claims_from_memory_entries(memory_entries))
    claims.extend(_claims_from_confirmed_rules(confirmed_rules))
    claims.extend(_claims_from_relation_facts(relation_facts))
    claims.extend(_claims_from_curated_docs(profile, project_root))

    topics = _build_topic_index(claims)
    entities = _build_entity_index(claims)

    claims_payload = {
        "project_name": project_name,
        "authority": COMPILED_AUTHORITY,
        "updated_at": _utc_now().isoformat(),
        "claims": [claim.to_dict() for claim in claims],
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
    claims_path.write_text(json.dumps(claims_payload, indent=2), encoding="utf-8")
    topics_path.write_text(json.dumps(topics_payload, indent=2), encoding="utf-8")
    entities_path.write_text(json.dumps(entities_payload, indent=2), encoding="utf-8")

    tracked_outputs = [
        GENERATED_CLAIMS_FILENAME,
        GENERATED_TOPICS_FILENAME,
        GENERATED_ENTITIES_FILENAME,
    ]
    generated_index_payload = {
        "project_name": project_name,
        "authority": COMPILED_AUTHORITY,
        "updated_at": _utc_now().isoformat(),
        "tracked_outputs": tracked_outputs,
        "counts": {
            "claims": len(claims),
            "topics": len(topics),
            "entities": len(entities),
        },
        "sources": [
            {
                "source_id": source.source_id,
                "source_hash": source.source_hash,
                "authority": source.authority,
                "exists": source.exists,
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
        "index_path": str(paths.generated_index_path),
        "claim_count": len(claims),
        "topic_count": len(topics),
        "entity_count": len(entities),
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


def _claims_from_memory_entries(entries: list[MemoryEntry]) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for entry in entries:
        text = entry.content.strip()
        if not text:
            continue
        source_ref = {
            "source_kind": "memory_entry",
            "source_id": entry.id,
            "label": entry.category,
            "drilldown": {"memory_entry_id": entry.id},
        }
        claims.append(
            GeneratedClaim(
                claim_id=f"memory-entry:{entry.id}",
                claim_kind="memory_entry",
                authority=COMPILED_AUTHORITY,
                text=text,
                topics=tuple(_topics_for_memory_entry(entry)),
                entities=tuple(_extract_entities(text)),
                source_refs=(source_ref,),
            )
        )
    return claims


def _claims_from_confirmed_rules(rules: list[ConfirmedRule]) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for rule in rules:
        pattern = rule.pattern.strip()
        trigger = rule.trigger.strip()
        if not pattern and not trigger:
            continue
        text = f"When {trigger}, {pattern}".strip(", ")
        source_ref = {
            "source_kind": "confirmed_rule",
            "source_id": rule.id,
            "label": trigger or "confirmed rule",
            "drilldown": {"confirmed_rule_id": rule.id},
        }
        claims.append(
            GeneratedClaim(
                claim_id=f"confirmed-rule:{rule.id}",
                claim_kind="confirmed_rule",
                authority=COMPILED_AUTHORITY,
                text=text,
                topics=tuple(_topics_for_rule(rule)),
                entities=tuple(_extract_entities(text)),
                source_refs=(source_ref,),
            )
        )
    return claims


def _claims_from_relation_facts(facts: list[RelationFact]) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    for fact in facts:
        text = f"{fact.source_entity} {fact.relation_type} {fact.target_entity}. {fact.evidence}".strip()
        source_ref = {
            "source_kind": "relation_fact",
            "source_id": fact.id,
            "label": fact.relation_type,
            "drilldown": {"relation_fact_id": fact.id},
        }
        claims.append(
            GeneratedClaim(
                claim_id=f"relation-fact:{fact.id}",
                claim_kind="relation_fact",
                authority=COMPILED_AUTHORITY,
                text=text,
                topics=(fact.relation_type.lower(), "relation"),
                entities=(fact.source_entity, fact.target_entity),
                source_refs=(source_ref,),
            )
        )
    return claims


def _claims_from_curated_docs(
    profile: ProjectProfile | None,
    project_root: Path | None,
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
        source_ref = {
            "source_kind": "curated_doc",
            "source_id": f"curated-doc://{_normalize_source_label(curated_path)}",
            "label": curated_path,
            "drilldown": {"curated_doc_path": str(resolved)},
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
            )
        )
    return claims


def _topics_for_memory_entry(entry: MemoryEntry) -> list[str]:
    topics = [entry.category.lower()]
    topics.extend(_extract_keywords(entry.content, limit=4))
    return _unique_preserve_order(topics)


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
