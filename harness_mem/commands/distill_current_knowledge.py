"""Read current same-source knowledge before ordinary candidate extraction.

These rows are comparisons, never source evidence or a blanket processed range.
The complete conversation remains available to discover changed or omitted claims.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from harness_mem.commands.dream_assimilation import _entry_version_snapshot
from harness_mem.commands.evidence_admission import (
    _reopen_complete_user_context,
    _source_report_author_indexes,
    _source_report_context,
    reopen_knowledge_sources,
)
from harness_mem.mcp.distill_projection import _parse_exchanges, render_distill_exchange_windows


async def manual_knowledge_context(
    backend: Any, packet: dict[str, Any], *, include_current: bool, scope: str,
) -> dict[str, Any]:
    """Supply live classification context for each manual review, including resume."""
    from harness_mem.mcp.read_projection import project_memory_entries, reading_tokens
    from harness_mem.read_knowledge import search_current_knowledge

    try:
        if backend.runtime_state == "degraded_fallback" or backend.runtime_error:
            raise ValueError("current memory is unavailable")
        job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
        if job is None:
            raise ValueError("prepared source job is unavailable")
        _, rendering, _ = _source_report_context(
            backend, project_name=job.project_name, source_id=job.source_id,
            source_revision=job.source_revision,
        )
        _, exchanges, _ = _parse_exchanges(rendering)
        query = "\n".join(
            body for exchange in exchanges for role in ("user", "assistant")
            for body in exchange[role]
        ) or rendering

        # The selected job's frozen owner supplies the taxonomy used for writes.
        project = job.project_name
        entries = await backend.structured_store.knowledge_store.list_entries(project)
        paths = sorted({tuple(entry.module_path) for entry in entries if entry.module_path})
        modules = []
        remaining = 900
        for path in paths:
            cost = reading_tokens(path)
            if cost <= remaining:
                modules.append(list(path))
                remaining -= cost

        if include_current:
            current = await search_current_knowledge(
                backend, project_name=project if scope == "project" else None,
                query=query, source_context=True,
            )
            rows = project_memory_entries(current, include_project=True, include_modules=True)
            limited = False
        else:
            current = await search_current_knowledge(
                backend, project_name=project, query=query, source_context=True, limit=9,
            )
            candidates = project_memory_entries(current, include_project=True, include_modules=True)
            rows = []
            limited = len(current) > 8
            remaining = 1200
            for row in candidates[:8]:
                cost = reading_tokens(row)
                if cost <= remaining:
                    rows.append(row)
                    remaining -= cost
                else:
                    limited = True
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return {"current_knowledge_status": "unavailable"}

    return {
        "current_knowledge": rows,
        "current_knowledge_status": "answered" if rows else "limited" if limited else "empty",
        "current_knowledge_limited": limited,
        "current_module_catalog": {
            "project_name": project, "paths": modules, "truncated": len(modules) < len(paths),
        },
    }


async def current_source_knowledge(
    backend: Any, *, job: Any, project_root: Path,
) -> list[dict[str, Any]]:
    """Bind complete current entries to unchanged, role-proved source anchors.

    An appended revision does not make an old claim new. Conversely a matching
    exchange is not proof that every clause in that exchange has been retained.
    Expose the actual retained meaning so extraction can decide that difference.
    Invalid or missing comparison evidence never suppresses source extraction.
    """
    try:
        revision, rendering, raw = _source_report_context(
            backend, project_name=job.project_name, source_id=job.source_id,
            source_revision=job.source_revision,
        )
    except (ValueError, KeyError, TypeError, OSError):
        return []
    if (revision.session_id != job.session_id or revision.client != job.client
            or Path(revision.project_root).resolve() != project_root.resolve()):
        return []
    count = len(_parse_exchanges(rendering)[1])
    anchors = {row['exchange_index']: row['content_sha256'] for row in
               render_distill_exchange_windows(rendering, list(range(1, count + 1)))}
    authored = {role: _source_report_author_indexes(revision, rendering, raw, role)
                for role in ('user', 'assistant')}
    store = backend.structured_store.knowledge_store
    result: list[dict[str, Any]] = []
    opened: dict[tuple[str, str, str], bool] = {}
    revisions: dict[str, Any] = {revision.source_revision: revision}
    for entry in await store.list_entries(job.project_name, project_root=project_root):
        if entry.project_name != job.project_name:
            continue
        try:
            sources = await store.list_sources(entry.id)
            if not sources:
                continue
            mapped = []
            for source in sources:
                query = parse_qs(urlparse(source.locator).fragment, keep_blank_values=True)
                if (source.project_name != job.project_name or source.knowledge_id != entry.id
                        or source.source_kind not in {'user_statement', 'source_report'}
                        or query.get('source_id') != [job.source_id]
                        or any(len(query.get(k, [])) != 1 for k in ['source_revision', 'exchange'])):
                    break
                old_revision = query['source_revision'][0]
                index = int(query['exchange'][0])
                if source.source_kind == 'source_report':
                    report = entry.source_report
                    if (report is None or report.source_id != job.source_id
                            or report.source_revision != old_revision or report.session_id != job.session_id
                            or index not in report.exchange_indexes or query.get('role') != [report.speaker]):
                        break
                elif entry.source_report is not None or ('role' in query and query['role'] != ['user']):
                    break
                role = (query.get('role') or ['user'])[0]
                if index not in (authored.get(role) or set()):
                    break
                anchor_values = query.get('anchor_sha256', [source.content_sha256])
                if len(anchor_values) != 1 or anchors.get(index) != anchor_values[0]:
                    break
                if old_revision not in revisions:
                    revisions[old_revision] = _source_report_context(
                        backend, project_name=job.project_name, source_id=job.source_id,
                        source_revision=old_revision,
                    )[0]
                old = revisions[old_revision]
                if (old.client != revision.client or old.session_id != revision.session_id
                        or Path(old.project_root).resolve() != project_root.resolve()):
                    break
                key = (source.source_kind, source.locator, source.content_sha256)
                if key not in opened:
                    if source.source_kind == 'user_statement':
                        status, _reason, content, truncated, _effective = _reopen_complete_user_context(backend, source)
                        body = json.loads(content) if status == 'verified' and content and not truncated else {}
                        opened[key] = (body.get('context_scope') == 'complete-authored-user-v1'
                            and body.get('source_id') == job.source_id
                            and body.get('source_revision') == old_revision
                            and body.get('session_id') == job.session_id and body.get('role') == 'user')
                    else:
                        validation, reopened = await reopen_knowledge_sources(
                            backend, project_name=job.project_name, sources=[source], project_root=project_root,
                        )
                        opened[key] = validation.verification_outcome == 'verified' and bool(reopened)
                if not opened[key]:
                    break
                mapped.append({'exchange_index': index, 'content_sha256': anchors[index],
                    'source_revision': old_revision, 'source_kind': source.source_kind,
                    'role': role})
            else:
                snapshot = _entry_version_snapshot(entry)
                current = await store.get_entry(entry.id, project_name=job.project_name, project_root=project_root)
                if (current is not None and _entry_version_snapshot(current) == snapshot
                        and await store.list_sources(entry.id) == sources):
                    result.append({**snapshot, 'comparison_only': True,
                        'kind': 'current_knowledge_comparison_not_source_evidence',
                        'source_exchanges': mapped})
        except (KeyError, ValueError, TypeError, OSError):
            continue
    return sorted(result, key=lambda row: row['id'])
