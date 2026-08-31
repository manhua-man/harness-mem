"""Persist and read Hook re-entry blocks during autonomous provider runs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTONOMOUS_PROVIDER_ENV = "HARNESS_MEM_AUTONOMOUS_PROVIDER"
_BLOCKED_ACTIONS = frozenset({"wake-start", "post-turn-maintenance", "dream-end"})


def autonomous_provider_context_active() -> bool:
    """True when the current process was spawned by an autonomous provider."""

    return os.environ.get(AUTONOMOUS_PROVIDER_ENV) == "1"


def autonomous_provider_hook_reentry_blocked(action: str) -> bool:
    """True when this host-entry action must not recurse from autonomous work."""

    return autonomous_provider_context_active() and str(action or "") in _BLOCKED_ACTIONS


def _project_key(project_name: str, project_root: Path) -> str:
    material = f"{project_name}\0{project_root.expanduser().resolve()}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def hook_reentry_ledger_path(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
) -> Path:
    key = _project_key(project_name, project_root)
    return Path(data_dir) / "autonomous" / "hook_reentry" / f"{key}.jsonl"


def record_hook_reentry_block(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    action: str,
    trigger_id: str | None = None,
) -> None:
    """Append one blocked Hook attempt while autonomous provider context is active."""

    path = hook_reentry_ledger_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "action": str(action or ""),
        "trigger_id": str(trigger_id or ""),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def count_hook_reentry_blocks(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None = None,
) -> int:
    """Count ledger entries, optionally scoped to one Hook trigger id."""

    path = hook_reentry_ledger_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    selected = str(trigger_id or "")
    count = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if selected and str(payload.get("trigger_id") or "") != selected:
            continue
        count += 1
    return count


def summarize_hook_reentry_blocks(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None = None,
) -> dict[str, Any]:
    """Return a compact audit view for receipts and health cards."""

    return {
        "count": count_hook_reentry_blocks(
            data_dir,
            project_name=project_name,
            project_root=project_root,
            trigger_id=trigger_id,
        ),
        "trigger_id": trigger_id,
    }
