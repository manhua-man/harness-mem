from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENTRY_MIX = [
    "observation",
    "memory_entry",
    "confirmed_rule",
    "relation_fact",
    "rule_candidate",
    "skill",
]
CORPUS_PROFILES = {
    "10k": 10_000,
    "100k": 100_000,
    "1m": 1_000_000,
}


def resolve_entry_count(entry_count: int, profile: str | None) -> int:
    if profile is None:
        return entry_count
    try:
        return CORPUS_PROFILES[profile]
    except KeyError as exc:
        choices = ", ".join(sorted(CORPUS_PROFILES))
        raise ValueError(f"unknown corpus profile {profile!r}; expected one of: {choices}") from exc
def generate_v3_corpus(
    data_dir: Path,
    *,
    entry_count: int,
    project_count: int,
    seed: int,
    payload_size_bytes: int,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    rng = random.Random(seed)
    counts = {kind: 0 for kind in ENTRY_MIX}
    payload_hash = hashlib.sha256()

    for index in range(entry_count):
        kind = ENTRY_MIX[index % len(ENTRY_MIX)]
        counts[kind] += 1
        project = f"project-{index % max(project_count, 1):03d}"
        entity_id = f"{kind}-{index:08d}"
        payload = _payload(
            kind,
            entity_id=entity_id,
            project_name=project,
            index=index,
            seed=seed,
            rng=rng,
            payload_size_bytes=payload_size_bytes,
        )
        path = _payload_path(data_dir, kind, entity_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(payload, indent=2, sort_keys=True)
        path.write_text(rendered + "\n", encoding="utf-8")
        payload_hash.update(_stable_json(payload).encode("utf-8"))
        payload_hash.update(b"\n")

    dataset_hash = payload_hash.hexdigest()
    return {
        "dataset_id": f"storage-v2-synthetic-{entry_count}-{project_count}-{seed}-{payload_size_bytes}",
        "dataset_hash": dataset_hash,
        "entry_count": entry_count,
        "project_count": project_count,
        "seed": seed,
        "payload_size_bytes": payload_size_bytes,
        "entry_mix": counts,
        "generator": "benchmark-suite/tools/storage_v2_fixture.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def corpus_json_file_count(data_dir: Path) -> int:
    data_dir = Path(data_dir)
    return len(list((data_dir / "verbatim").glob("*.json"))) + len(
        list((data_dir / "structured").glob("*/*.json"))
    )


def corpus_disk_bytes(data_dir: Path) -> int:
    total = 0
    for path in Path(data_dir).glob("**/*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def write_dataset_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    (Path(run_dir) / "dataset.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _payload(
    kind: str,
    *,
    entity_id: str,
    project_name: str,
    index: int,
    seed: int,
    rng: random.Random,
    payload_size_bytes: int,
) -> dict[str, Any]:
    text = _text_payload(kind, index=index, seed=seed, rng=rng, target=payload_size_bytes)
    timestamp = f"2026-06-{(index % 28) + 1:02d}T12:00:00+00:00"
    if kind == "observation":
        return {
            "id": entity_id,
            "session_id": f"session-{index // 8:06d}",
            "client": "synthetic",
            "content_type": "text",
            "raw_content": text,
            "timestamp": timestamp,
            "tags": ["storage-v2", "synthetic"],
            "metadata": {"project_name": project_name, "corpus": "storage-v2"},
            "compacted": False,
        }
    if kind == "memory_entry":
        return {
            "id": entity_id,
            "project_name": project_name,
            "category": "decision",
            "content": text,
            "confidence": 0.82,
            "status": "accepted",
            "source": "synthetic",
            "created_at": timestamp,
            "updated_at": timestamp,
            "tags": ["storage-v2"],
            "compacted": False,
            "usage_count": index % 7,
            "last_accessed_at": None,
            "memory_type": "semantic",
        }
    if kind == "confirmed_rule":
        return {
            "id": entity_id,
            "project_name": project_name,
            "pattern": f"rule pattern {index}",
            "trigger": text[:120],
            "examples": [f"example {index}"],
            "confirmed_at": timestamp,
            "source_candidate_id": f"candidate-{index:08d}",
            "source_session_id": f"session-{index // 8:06d}",
            "tags": ["storage-v2"],
            "usage_count": index % 5,
            "last_surfaced_at": None,
        }
    if kind == "relation_fact":
        return {
            "id": entity_id,
            "project_name": project_name,
            "source_entity": f"entity-{index % 17}",
            "target_entity": f"entity-{(index + 3) % 17}",
            "relation_type": "depends_on",
            "confidence": 0.74,
            "status": "accepted",
            "evidence": text,
            "source": "synthetic",
            "created_at": timestamp,
            "updated_at": timestamp,
            "tags": ["storage-v2"],
        }
    if kind == "skill":
        return {
            "id": entity_id,
            "project_name": project_name,
            "name": f"storage skill {index}",
            "activation_condition": text[:160],
            "steps": [text[:80], text[80:160]],
            "termination_condition": "checksum and report complete",
            "success_examples": [f"success {index}"],
            "source_candidate_id": f"candidate-{index:08d}",
            "source_session_id": f"session-{index // 8:06d}",
            "source_ids": [],
            "status": "accepted",
            "created_at": timestamp,
            "updated_at": timestamp,
            "usage_count": index % 3,
            "success_count": index % 2,
            "failure_count": 0,
        }
    return {
        "id": entity_id,
        "project_name": project_name,
        "pattern": f"candidate pattern {index}",
        "rationale": text,
        "confidence": 0.66,
        "status": "pending",
        "session_id": f"session-{index // 8:06d}",
        "created_at": timestamp,
        "evidence": [f"obs-{index:08d}"],
    }


def _payload_path(data_dir: Path, kind: str, entity_id: str) -> Path:
    if kind == "observation":
        return data_dir / "verbatim" / f"{entity_id}.json"
    collection = {
        "memory_entry": "memory_entries",
        "confirmed_rule": "confirmed_rules",
        "relation_fact": "relation_facts",
        "rule_candidate": "rule_candidates",
        "skill": "skills",
    }[kind]
    return data_dir / "structured" / collection / f"{entity_id}.json"


def _text_payload(
    kind: str,
    *,
    index: int,
    seed: int,
    rng: random.Random,
    target: int,
) -> str:
    base = (
        f"storage-v2 synthetic {kind} row {index} seed {seed} "
        f"token {rng.randint(100000, 999999)} "
    )
    repeat = max(target // max(len(base), 1) + 1, 1)
    return (base * repeat)[:target]


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
