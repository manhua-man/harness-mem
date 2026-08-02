"""Exercise an installed wheel across upgrade, recovery, and cleanup retry.

The two phases are intentionally separate so the release workflow can run
``prepare-upgrade`` with the previous wheel installed and ``verify-upgrade``
after installing the release candidate into the same environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn, Sequence


_PROJECT_NAME = "install-lifecycle-qualification"
_CANONICAL_ID = "upgrade-canonical-observation"
_LEGACY_ID = "upgrade-legacy-observation"
_CANONICAL_BODY = "synthetic canonical state written by the baseline wheel"
_LEGACY_BODY = "synthetic legacy state restored by the release wheel"
_CLEANUP_BODY = "synthetic transcript removed by cleanup retry"
_CLEANUP_SESSION_ID = "019f0000-0000-7000-8000-000000000997"


def _installed_version() -> str:
    from harness_mem import __version__

    return __version__


def _require_installed_wheel() -> None:
    import harness_mem

    checkout_package = Path(__file__).resolve().parents[1] / "harness_mem"
    module_path = Path(harness_mem.__file__).resolve()
    if module_path.is_relative_to(checkout_package):
        raise RuntimeError(
            f"qualification imported checkout source instead of installed wheel: {module_path}"
        )


def _require_version(expected_version: str) -> str:
    expected = expected_version.removeprefix("v")
    installed = _installed_version()
    if installed != expected:
        raise RuntimeError(
            f"installed version mismatch: {installed} != {expected}"
        )
    return installed


def _observation_payload(
    *, observation_id: str, session_id: str, raw_content: str
) -> dict[str, Any]:
    return {
        "id": observation_id,
        "session_id": session_id,
        "client": "codex",
        "raw_content": raw_content,
        "content_type": "transcript",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"project_name": _PROJECT_NAME},
        "tags": [],
        "compacted": False,
    }


async def _seed_canonical_state(data_dir: Path) -> None:
    from harness_mem.core.schemas.observation import Observation
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        await backend.verbatim_store.save(
            Observation.from_dict(
                _observation_payload(
                    observation_id=_CANONICAL_ID,
                    session_id="baseline-canonical-session",
                    raw_content=_CANONICAL_BODY,
                )
            )
        )
    finally:
        await backend.close()


def prepare_upgrade_state(state_dir: Path) -> dict[str, Any]:
    """Write current and legacy state using the baseline installation."""

    state_dir = Path(state_dir)
    data_dir = state_dir / "data"
    asyncio.run(_seed_canonical_state(data_dir))
    legacy_dir = data_dir / "verbatim"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / f"{_LEGACY_ID}.json").write_text(
        json.dumps(
            _observation_payload(
                observation_id=_LEGACY_ID,
                session_id="baseline-legacy-session",
                raw_content=_LEGACY_BODY,
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "schema_version": 1,
        "phase": "prepared",
        "platform": platform.system().lower(),
        "canonical_seeded": True,
        "legacy_seeded": True,
    }


def _canonical_payload(data_dir: Path, entity_id: str) -> dict[str, Any] | None:
    from harness_mem.storage.canonical_store import canonical_store_path

    connection = sqlite3.connect(canonical_store_path(data_dir))
    try:
        row = connection.execute(
            "SELECT payload_json FROM observations WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
    finally:
        connection.close()
    return json.loads(row[0]) if row is not None else None


def _exercise_migration_recovery(data_dir: Path) -> dict[str, Any]:
    from harness_mem.storage import canonical_store

    original_writer = canonical_store.write_runtime_state

    def fail_runtime_activation(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise RuntimeError("injected release qualification failure")

    canonical_store.write_runtime_state = fail_runtime_activation
    failure_observed = False
    try:
        canonical_store.migrate_canonical_store_atomically(
            data_dir,
            project_name=_PROJECT_NAME,
        )
    except RuntimeError as exc:
        failure_observed = str(exc) == "injected release qualification failure"
    finally:
        canonical_store.write_runtime_state = original_writer
    if not failure_observed:
        raise RuntimeError("migration fault injection did not reach runtime activation")

    rolled_back = _canonical_payload(data_dir, _CANONICAL_ID)
    if rolled_back is None or rolled_back.get("raw_content") != _CANONICAL_BODY:
        raise RuntimeError("migration rollback did not preserve baseline canonical state")
    if _canonical_payload(data_dir, _LEGACY_ID) is not None:
        raise RuntimeError("failed activation leaked staged legacy state")

    result = canonical_store.migrate_canonical_store_atomically(
        data_dir,
        project_name=_PROJECT_NAME,
    )
    backup_path = Path(str(result.get("backup_db_path") or ""))
    if not result.get("activated_atomically") or not backup_path.is_file():
        raise RuntimeError("migration retry did not activate with a verified snapshot")
    return {
        "fault_injection_observed": True,
        "rollback_preserved_live_store": True,
        "retry_activated": True,
        "backup_verified": True,
        "checksum_relation": result["checksum_relation"]["relation"],
    }


async def _verify_migrated_rows(data_dir: Path) -> None:
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        canonical = await backend.verbatim_store.get(_CANONICAL_ID)
        legacy = await backend.verbatim_store.get(_LEGACY_ID)
        if canonical is None or canonical.raw_content != _CANONICAL_BODY:
            raise RuntimeError("baseline canonical row was not preserved")
        if legacy is None or legacy.raw_content != _LEGACY_BODY:
            raise RuntimeError("legacy row was not restored")
    finally:
        await backend.close()


async def _exercise_cleanup_retry(state_dir: Path, data_dir: Path) -> dict[str, Any]:
    from harness_mem.adapters.snapshot import persist_session_snapshot
    from harness_mem.core.schemas.observation import Observation
    from harness_mem.processed_source_cleanup import retry_retained_source_cleanups
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    project = state_dir / "workspace with space" / "项目"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir(exist_ok=True)
    native_root = state_dir / "native" / ".codex" / "sessions"
    native_path = (
        native_root
        / "2026"
        / "08"
        / "02"
        / f"rollout-2026-08-02-{_CLEANUP_SESSION_ID}.jsonl"
    )
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(_CLEANUP_BODY, encoding="utf-8")
    old = time.time() - 600
    os.utime(native_path, (old, old))

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        snapshot = await persist_session_snapshot(
            backend,
            Observation.from_dict(
                _observation_payload(
                    observation_id="cleanup-retry-observation",
                    session_id=_CLEANUP_SESSION_ID,
                    raw_content=_CLEANUP_BODY,
                )
            ),
            project_name=_PROJECT_NAME,
            project_root=str(project),
            client="codex",
            session_id=_CLEANUP_SESSION_ID,
            source_kind="jsonl",
            source_uri=native_path.absolute().as_uri(),
            source_text=_CLEANUP_BODY,
            raw_bytes=_CLEANUP_BODY.encode("utf-8"),
            mtime_ns=native_path.stat().st_mtime_ns,
        )
        if snapshot.source is None or snapshot.distill_job_id is None:
            raise RuntimeError("cleanup qualification snapshot was not admitted")
        claims = backend.transcript_store.claim_distill_chunks(
            snapshot.distill_job_id,
            lease_owner="install-lifecycle-smoke",
            limit=100,
        )
        for chunk, _checkpoint in claims:
            backend.transcript_store.checkpoint_distill_chunk(
                snapshot.distill_job_id,
                chunk.id,
                lease_owner="install-lifecycle-smoke",
                result={"outline": "synthetic qualification outline"},
            )
        backend.transcript_store.finalize_distill_job(
            snapshot.distill_job_id,
            semantic_review={
                "final_user_request": "synthetic qualification request",
                "final_outcome": "synthetic qualification completed",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "no_promotion",
            },
        )
        backend.transcript_store.record_distill_completion_outcome(
            snapshot.distill_job_id,
            disposition="no_candidate",
            reason_codes=["no_durable_candidate", "transient_cleanup_failure"],
            promotion_summary={"suggested": 0, "promoted": 0, "rejected": 0},
            source_cleanup_status="partial_failure",
        )
        retry = await retry_retained_source_cleanups(
            backend,
            project_name=_PROJECT_NAME,
            authorized=True,
            minimum_age_seconds=0,
        )
        completed = backend.transcript_store.get_distill_job(
            snapshot.distill_job_id
        )
        raw = backend.transcript_store.reconstruct_raw(
            snapshot.source.id,
            source_revision=snapshot.source.source_revision,
        )
        receipts = backend.transcript_store.list_deletion_audit(
            project_name=_PROJECT_NAME
        )
        receipt_text = json.dumps(receipts, sort_keys=True)
        sensitive_values = (
            _CLEANUP_BODY,
            _CLEANUP_SESSION_ID,
            str(native_path),
            native_path.absolute().as_uri(),
        )
        if retry.get("deleted") != 1 or native_path.exists() or raw != b"":
            raise RuntimeError("partial cleanup retry did not remove all raw evidence")
        if completed is None or completed.source_cleanup_status != "deleted":
            raise RuntimeError("cleanup retry did not persist the completed outcome")
        if not receipts or any(value in receipt_text for value in sensitive_values):
            raise RuntimeError("cleanup receipt retained source content or locator")
        return {
            "partial_failure_retried": True,
            "native_source_deleted": True,
            "stored_raw_deleted": True,
            "content_free_receipt_verified": True,
            "attempted": int(retry["attempted"]),
            "deleted": int(retry["deleted"]),
        }
    finally:
        await backend.close()


def verify_upgrade_state(state_dir: Path) -> dict[str, Any]:
    """Verify rollback, restart recovery, legacy import, and cleanup retry."""

    state_dir = Path(state_dir)
    data_dir = state_dir / "data"
    if not data_dir.is_dir():
        raise RuntimeError("prepared upgrade state is missing")
    migration = _exercise_migration_recovery(data_dir)
    asyncio.run(_verify_migrated_rows(data_dir))
    cleanup = asyncio.run(_exercise_cleanup_retry(state_dir, data_dir))
    return {
        "schema_version": 1,
        "phase": "verified",
        "platform": platform.system().lower(),
        "legacy_restore": {
            "canonical_preserved": True,
            "legacy_restored": True,
            **migration,
        },
        "cleanup_retry": cleanup,
        "path_contract": {"contains_space": True, "contains_non_ascii": True},
        "success": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="phase", required=True)
    for phase in ("prepare-upgrade", "verify-upgrade"):
        command = subparsers.add_parser(phase)
        command.add_argument("--expected-version", required=True)
        command.add_argument("--state-dir", required=True, type=Path)
        command.add_argument("--require-installed-wheel", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.require_installed_wheel:
        _require_installed_wheel()
    installed = _require_version(args.expected_version)
    if args.phase == "prepare-upgrade":
        report = prepare_upgrade_state(args.state_dir)
    else:
        report = verify_upgrade_state(args.state_dir)
    report["installed_version"] = installed
    serialized = json.dumps(report, indent=2, sort_keys=True)
    for private_value in (_CANONICAL_BODY, _LEGACY_BODY, _CLEANUP_BODY):
        if private_value in serialized:
            raise RuntimeError("smoke report contains synthetic session content")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
