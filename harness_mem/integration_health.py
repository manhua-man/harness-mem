"""Compact, factual project integration diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness_mem.adapters import AdapterRegistry
from harness_mem.commands.distill_lifecycle import pending_distill_jobs
from harness_mem.commands.support import normalize_client_name
from harness_mem.hook_runtime import collect_hook_file_statuses
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def build_integration_health(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path | None,
) -> dict[str, Any]:
    """Report project, host, hooks, transcript, and distill queue health."""

    root = project_root.expanduser().resolve() if project_root is not None else None
    configured_host = os.environ.get("HARNESS_MEM_CLIENT")
    host = normalize_client_name(configured_host) if configured_host else "unknown"

    hook_files = (
        collect_hook_file_statuses(root, client=host)
        if root is not None and host != "unknown"
        else ()
    )
    installed_hooks = [hook for hook in hook_files if hook.exists]
    if host == "unknown" or root is None:
        hooks_status = "unknown"
    elif not hook_files:
        hooks_status = "unsupported"
    elif len(installed_hooks) == len(hook_files):
        hooks_status = "ok"
    else:
        hooks_status = "missing"

    observations = await backend.verbatim_store.list(
        project_name=project_name,
        limit=100000,
    )
    transcript_clients = sorted(
        {str(observation.client) for observation in observations if observation.client}
    )
    host_observations = sum(1 for item in observations if item.client == host)
    adapter_available = host in AdapterRegistry.list()
    if observations:
        transcript_status = "observed"
    elif host == "unknown":
        transcript_status = "unknown"
    elif adapter_available:
        transcript_status = "ready"
    else:
        transcript_status = "unsupported"

    queued = pending_distill_jobs(backend, project_name=project_name)
    processing = backend.reflection_job_store.list(
        project_name=project_name,
        status="processing",
        kind="reflection",
        limit=100,
    )
    distill_status = "processing" if processing else "queued" if queued else "idle"
    project_status = "ok" if root is not None else "unknown"
    summary = (
        f"project={project_status} | host={host} | "
        f"hooks={hooks_status} ({len(installed_hooks)}/{len(hook_files)}) | "
        f"transcript={transcript_status} ({len(observations)}) | "
        f"distill={distill_status} ({len(queued)} queued, {len(processing)} processing)"
    )
    return {
        "summary": summary,
        "project": {
            "status": project_status,
            "name": project_name,
            "root": str(root) if root is not None else None,
        },
        "host": {"status": "ok" if host != "unknown" else "unknown", "client": host},
        "hooks": {
            "status": hooks_status,
            "installed": len(installed_hooks),
            "expected": len(hook_files),
            "files": [str(hook.path) for hook in hook_files if hook.exists],
        },
        "transcript": {
            "status": transcript_status,
            "observation_count": len(observations),
            "host_observation_count": host_observations,
            "clients": transcript_clients,
            "adapter_available": adapter_available,
        },
        "pending_distill": {
            "status": distill_status,
            "queued": len(queued),
            "processing": len(processing),
        },
    }


__all__ = ["build_integration_health"]
