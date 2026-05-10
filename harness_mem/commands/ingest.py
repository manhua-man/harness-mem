"""Ingest command implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.protocol import SessionRecord
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_cli_event,
    log_command_invoked,
    resolve_project_name,
    set_active_project,
)
from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.event_log import EventType
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def cmd_ingest(
    client: str,
    project_name: str | None = None,
    limit: int = 10,
    full_rescan: bool = False,
) -> int:
    """Ingest sessions for a supported client."""
    project_name = resolve_project_name(project_name, action_label=f"{client} ingest")
    if not project_name:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)

        if client == "claude-code":
            return await _ingest_claude_code(
                backend,
                profile_store,
                project_name=project_name,
                limit=limit,
                full_rescan=full_rescan,
            )

        print(f"Ingesting {client} sessions for project: {project_name}")
        adapter = AdapterRegistry.build(client, backend)
        result = await adapter.ingest(project_name=project_name, limit=limit, min_size_kb=0)
        return _report_non_claude_ingest_result(
            client=client,
            project_name=project_name,
            result=result,
            full_rescan=full_rescan,
        )
    finally:
        await backend.close()


async def _ingest_claude_code(
    backend: LocalMemoryBackend,
    profile_store: LocalProjectProfileStore,
    *,
    project_name: str,
    limit: int,
    full_rescan: bool,
) -> int:
    adapter = AdapterRegistry.build("claude-code", backend)
    profile = await profile_store.get(project_name)
    all_sessions = adapter.list_sessions(project_name, min_size_kb=0)
    last_session_id = profile.last_ingest_session_id if profile and not full_rescan else None
    last_ingest_at = profile.last_ingest_at if profile and not full_rescan else None

    print(f"Ingesting claude-code sessions for project: {project_name}")
    candidate_sessions = _select_claude_candidate_sessions(
        all_sessions,
        limit=limit,
        full_rescan=full_rescan,
        last_session_id=last_session_id,
        last_ingest_at=last_ingest_at,
    )

    existing_observations = await backend.verbatim_store.list(limit=100000)
    existing_session_ids = {
        observation.session_id
        for observation in existing_observations
        if observation.metadata.get("project_name") == project_name
    }

    ingested = 0
    errors = 0
    skipped_existing = 0

    for session in candidate_sessions:
        try:
            if session["session_id"] in existing_session_ids:
                skipped_existing += 1
                continue
            observation = adapter.session_to_observation(session["path"], session["session_id"], project_name)
            await backend.verbatim_store.save(observation)
            ingested += 1
            existing_session_ids.add(session["session_id"])
        except Exception:
            errors += 1

    newest_seen_session_id = last_session_id
    if all_sessions:
        newest_seen_session_id = all_sessions[0]["session_id"]

    print(f"Sessions found: {len(all_sessions)}")
    print(f"Ingested: {ingested} sessions")
    if skipped_existing > 0:
        print(f"Skipped existing: {skipped_existing} sessions")
    if errors > 0:
        print(f"Errors: {errors}")

    if profile is None:
        profile = ProjectProfile(project_name=project_name)
    if newest_seen_session_id is not None:
        profile.last_ingest_session_id = newest_seen_session_id
    if candidate_sessions or full_rescan:
        profile.last_ingest_at = datetime.now(timezone.utc)
    await profile_store.save(profile)

    if not profile.stacks:
        sessions_dir = Path.home() / ".claude" / "projects"
        project_path = sessions_dir / project_name
        if project_path.exists():
            detected = build_project_profile(project_path, project_name)
            profile.stacks = detected.stacks
            profile.key_files = detected.key_files
            await profile_store.save(profile)
            print(f"Auto-detected profile: {', '.join(profile.stacks)}")

    set_active_project(project_name)
    extra = {
        "client": "claude-code",
        "ingested": ingested,
        "sessions_found": len(all_sessions),
        "full_rescan": full_rescan,
    }
    log_command_invoked("ingest", project_name=project_name, extra=extra)
    log_cli_event(
        EventType.SESSION_INGESTED,
        project_name=project_name,
        command="ingest",
        extra=extra,
    )
    return 0


def _select_claude_candidate_sessions(
    all_sessions: list[SessionRecord],
    *,
    limit: int,
    full_rescan: bool,
    last_session_id: str | None,
    last_ingest_at: datetime | None,
) -> list[SessionRecord]:
    if full_rescan:
        print("[Full Rescan] Processing all sessions without cursor shortcuts.")
        return all_sessions[:limit]

    if not last_session_id:
        return all_sessions[:limit]

    candidate_sessions: list[SessionRecord] = []
    cursor_found = False
    for session in all_sessions:
        if session["session_id"] == last_session_id:
            cursor_found = True
            break
        candidate_sessions.append(session)

    if cursor_found:
        print(f"[Incremental] Processing sessions newer than cursor: {last_session_id}")
        return candidate_sessions[:limit]

    print(
        f"Warning: ingest cursor {last_session_id} not found; "
        "falling back to sessions newer than last ingest timestamp."
    )
    if last_ingest_at is not None:
        candidate_sessions = [
            session for session in all_sessions if session.get("mtime") and session["mtime"] > last_ingest_at
        ]
        return candidate_sessions[:limit]

    return all_sessions[:limit]


def _report_non_claude_ingest_result(
    *,
    client: str,
    project_name: str,
    result: dict,
    full_rescan: bool,
) -> int:
    for warning in result.get("warnings", []):
        print(f"Warning: {warning['message']}")

    exit_code = 1 if result["errors"] > 0 and result["ingested"] == 0 else 0
    extra = {"client": client, **result, "full_rescan": full_rescan, "exit_code": exit_code}

    if result["sessions_found"] == 0:
        log_command_invoked("ingest", project_name=project_name, extra=extra)
        log_cli_event(
            EventType.SESSION_INGESTED,
            project_name=project_name,
            command="ingest",
            extra=extra,
        )
        print(f"No {client} sessions found.")
        return 1

    print(f"Sessions found: {result['sessions_found']}")
    print(f"Ingested: {result['ingested']} sessions")
    for error in result.get("error_details", []):
        print(f"Error: {error['message']}")
    if result["errors"] > 0:
        print(f"Errors: {result['errors']}")
    if exit_code == 0:
        set_active_project(project_name)

    log_command_invoked("ingest", project_name=project_name, extra=extra)
    log_cli_event(
        EventType.SESSION_INGESTED,
        project_name=project_name,
        command="ingest",
        extra=extra,
    )
    return exit_code
