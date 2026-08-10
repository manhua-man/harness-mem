"""Durable proof that a generated IDE hook completed successfully."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness_mem.hook_runtime import collect_hook_file_statuses

__all__ = [
    "HOOK_RECEIPT_FRESHNESS_SECONDS",
    "hook_configuration_fingerprint",
    "inspect_hook_execution_receipt",
    "read_hook_execution_receipt",
    "record_hook_execution",
]

_SCHEMA_VERSION = 1
HOOK_RECEIPT_FRESHNESS_SECONDS = 24 * 60 * 60


def hook_configuration_fingerprint(
    project_root: Path,
    *,
    client: str,
    home_dir: Path | None = None,
) -> str | None:
    """Hash the generated hook artifacts currently bound to one host."""

    statuses = collect_hook_file_statuses(
        project_root,
        client=client,
        home_dir=home_dir,
    )
    if not statuses or any(
        not status.exists or not status.configured for status in statuses
    ):
        return None

    digest = hashlib.sha256()
    for status in sorted(statuses, key=lambda item: str(item.path)):
        try:
            content = status.path.read_bytes()
        except OSError:
            return None
        digest.update(str(status.path.resolve()).encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def record_hook_execution(
    data_dir: Path,
    *,
    project_root: Path,
    project_name: str,
    client: str,
    action: str,
    source: str,
    trigger_id: str | None,
) -> Path | None:
    """Record a successful hook action against its current config fingerprint."""

    root = project_root.expanduser().resolve()
    fingerprint = hook_configuration_fingerprint(root, client=client)
    if fingerprint is None:
        return None

    target = _receipt_path(data_dir, project_root=root, client=client, action=action)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "project_name": project_name,
        "project_root": str(root),
        "client": client,
        "action": action,
        "source": source,
        "trigger_id": trigger_id,
        "config_fingerprint": fingerprint,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def read_hook_execution_receipt(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    action: str,
) -> dict[str, Any] | None:
    """Return a receipt only when it matches the current hook configuration."""

    root = project_root.expanduser().resolve()
    fingerprint = hook_configuration_fingerprint(root, client=client)
    if fingerprint is None:
        return None
    path = _receipt_path(data_dir, project_root=root, client=client, action=action)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expected = {
        "schema_version": _SCHEMA_VERSION,
        "project_root": str(root),
        "client": client,
        "action": action,
        "config_fingerprint": fingerprint,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        return None
    return payload


def inspect_hook_execution_receipt(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    action: str,
    now: datetime | None = None,
    max_age: timedelta = timedelta(seconds=HOOK_RECEIPT_FRESHNESS_SECONDS),
) -> dict[str, Any]:
    """Describe whether one current hook action has recent execution proof.

    ``read_hook_execution_receipt`` intentionally preserves its compatibility
    contract and returns any receipt bound to the current configuration.  This
    diagnostic adds the time dimension needed by health checks and keeps a
    configuration mismatch distinct from a hook that has never run.
    """

    root = project_root.expanduser().resolve()
    fingerprint = hook_configuration_fingerprint(root, client=client)
    path = _receipt_path(data_dir, project_root=root, client=client, action=action)
    if not path.exists():
        return _receipt_health_payload(receipt_status="missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _receipt_health_payload(receipt_status="invalid")
    if not isinstance(payload, dict):
        return _receipt_health_payload(receipt_status="invalid")

    completed_at = _parse_completed_at(payload.get("completed_at"))
    last_success_at = completed_at.isoformat() if completed_at is not None else None
    reference_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (
        max(0, int((reference_time - completed_at).total_seconds()))
        if completed_at is not None
        else None
    )
    identity_matches = all(
        payload.get(key) == value
        for key, value in {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(root),
            "client": client,
            "action": action,
        }.items()
    )
    config_match = bool(
        identity_matches
        and fingerprint is not None
        and payload.get("config_fingerprint") == fingerprint
    )
    if not identity_matches or completed_at is None:
        return _receipt_health_payload(
            receipt_status="invalid",
            last_success_at=last_success_at,
            age_seconds=age_seconds,
        )
    if not config_match:
        return _receipt_health_payload(
            receipt_status="config_mismatch",
            last_success_at=last_success_at,
            age_seconds=age_seconds,
        )
    freshness = "fresh" if age_seconds is not None and age_seconds <= int(max_age.total_seconds()) else "stale"
    return _receipt_health_payload(
        freshness=freshness,
        receipt_status="current",
        last_success_at=last_success_at,
        age_seconds=age_seconds,
        config_match=True,
    )


def _receipt_health_payload(
    *,
    freshness: str = "never",
    receipt_status: str,
    last_success_at: str | None = None,
    age_seconds: int | None = None,
    config_match: bool = False,
) -> dict[str, Any]:
    return {
        "freshness": freshness,
        "receipt_status": receipt_status,
        "last_success_at": last_success_at,
        "age_seconds": age_seconds,
        "config_match": config_match,
    }


def _parse_completed_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _receipt_path(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    action: str,
) -> Path:
    root_key = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:24]
    safe_action = action.replace("/", "-").replace("\\", "-")
    return Path(data_dir) / "hook_runtime" / f"{client}-{root_key}-{safe_action}.json"
