"""Run the 0.9.20 six-session archive acceptance in an isolated data root."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from harness_mem.commands.archive_distill import (
    inventory_codex_archives,
    run_archive_distill_batch,
)
from harness_mem.autonomous.models import validate_atomic_knowledge_statement
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.config.merge import load_merged_config
from harness_mem.mcp.read_projection import project_memory_entries
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.canonical_store import canonical_store_path
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


DEFAULT_COUNT = 6
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_FORBIDDEN_PROJECTION_MARKERS = (
    "distill_job_id",
    "candidate_id",
    "verification_reason_codes",
    "assimilation_disposition",
    "assimilation_reason",
    "confidence",
    "tier",
)
_FORBIDDEN_NATURAL_HEADINGS = {
    "stable operation rule",
    "stable operation rules",
    "candidate promotion",
    "候选提升",
    "稳定操作规则",
    "会话管理",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _optional_sha256(path: Path) -> str | None:
    return _sha256(path) if path.is_file() else None


def _small_tree_fingerprint(root: Path) -> str | None:
    if not root.exists():
        return None
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _assert_isolated_paths(
    *,
    output_root: Path,
    source_archive_dir: Path,
    real_data_dir: Path,
    real_notes_dir: Path,
) -> None:
    for protected in (source_archive_dir, real_data_dir, real_notes_dir):
        if _paths_overlap(output_root, protected):
            raise ValueError(
                f"output root must not overlap protected runtime path: {protected}"
            )


def _select_project_sessions(
    *,
    project_root: Path,
    source_archive_dir: Path,
    count: int,
) -> list[dict[str, Any]]:
    config = load_merged_config(project_root)
    inventory = inventory_codex_archives(
        control_root=project_root,
        config=config,
        archive_dir=source_archive_dir,
    )
    selected = [
        row
        for row in inventory["eligible_sessions"]
        if Path(str(row.get("project_root") or "")).resolve() == project_root
        and str(row.get("project_name") or "") == project_root.name
    ][:count]
    if len(selected) != count:
        raise RuntimeError(
            f"expected {count} eligible {project_root.name} archives, found {len(selected)}"
        )
    if len({str(row["session_id"]) for row in selected}) != count:
        raise RuntimeError("archive cohort contains duplicate session ids")
    return selected


def _copy_cohort(
    *,
    selected: list[dict[str, Any]],
    archive_dir: Path,
) -> list[dict[str, Any]]:
    archive_dir.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, Any]] = []
    for row in selected:
        source = Path(str(row["source_path"])).resolve()
        target = archive_dir / source.name
        shutil.copy2(source, target)
        source_sha = _sha256(source)
        copy_sha = _sha256(target)
        if source_sha != copy_sha:
            raise RuntimeError(f"archive copy digest mismatch: {source.name}")
        manifest.append(
            {
                "session_id": str(row["session_id"]),
                "project_name": str(row["project_name"]),
                "project_root": str(row["project_root"]),
                "source_path": str(source),
                "source_sha256": source_sha,
                "isolated_path": str(target),
                "isolated_sha256": copy_sha,
                "size_bytes": source.stat().st_size,
                "updated_at": str(row["updated_at"]),
            }
        )
    return manifest


def _load_manifest(path: Path, *, expected_count: int) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise RuntimeError("resume manifest does not contain the expected cohort")
    return [dict(row) for row in rows]


def _real_state_fingerprint(
    *,
    real_data_dir: Path,
    real_notes_dir: Path,
) -> dict[str, Any]:
    return {
        "canonical_sqlite_sha256": _optional_sha256(
            canonical_store_path(real_data_dir)
        ),
        "archive_distill_sha256": _small_tree_fingerprint(
            real_data_dir / "archive_distill"
        ),
        "knowledge_workspace_sha256": _small_tree_fingerprint(
            real_data_dir / "job_workspaces" / "knowledge"
        ),
        "notes_sha256": _small_tree_fingerprint(real_notes_dir),
    }


def _quality_findings(entries: list[Any], markdown: str) -> dict[str, Any]:
    projected = project_memory_entries(entries)
    projection_keys = sorted({key for row in projected for key in row})
    headings = [
        part.strip()
        for entry in entries
        for part in list(getattr(entry, "module_path", ()) or ())
    ]
    forbidden_headings = sorted(
        {
            heading
            for heading in headings
            if heading.casefold() in _FORBIDDEN_NATURAL_HEADINGS
        }
    )
    normalized_rows = [
        (
            tuple(part.casefold().strip() for part in entry.module_path),
            entry.title.casefold().strip(),
            " ".join(entry.statement.casefold().split()),
        )
        for entry in entries
    ]
    exact_duplicates = len(normalized_rows) - len(set(normalized_rows))
    title_duplicates = sorted(
        {
            entry.title
            for entry in entries
            if sum(other.title.casefold() == entry.title.casefold() for other in entries)
            > 1
        }
    )
    leaked_markers = sorted(
        marker for marker in _FORBIDDEN_PROJECTION_MARKERS if marker in markdown
    )
    uuid_leak = bool(_UUID_PATTERN.search(markdown))
    broad_items = []
    for entry in entries:
        try:
            validate_atomic_knowledge_statement(entry.statement)
        except ValueError as error:
            broad_items.append(
                {
                    "title": entry.title,
                    "statement_length": len(entry.statement),
                    "reason": str(error),
                }
            )
    return {
        "projected_rows": projected,
        "projection_keys": projection_keys,
        "forbidden_headings": forbidden_headings,
        "leaked_markers": leaked_markers,
        "uuid_leak": uuid_leak,
        "exact_duplicate_count": exact_duplicates,
        "duplicate_titles": title_duplicates,
        "broad_item_warnings": broad_items,
        "passed": bool(
            entries
            and projection_keys == ["statement", "title"]
            and not forbidden_headings
            and not leaked_markers
            and not uuid_leak
            and exact_duplicates == 0
            and not title_duplicates
            and not broad_items
        ),
    }


async def _inspect_isolated_result(
    *,
    data_dir: Path,
    notes_dir: Path,
    project_name: str,
) -> dict[str, Any]:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        store = backend.structured_store.knowledge_store
        entries = await store.list_entries(project_name)
        markdown = await store.render_markdown(project_name, include_details=False)
        known_projects = await store.known_projects()
        source_counts = {
            entry.id: len(await store.list_sources(entry.id)) for entry in entries
        }
        readback = []
        for entry in entries:
            matches = await search_current_knowledge(
                backend,
                project_name=project_name,
                query=entry.title,
                limit=max(20, len(entries)),
            )
            readback.append(
                {
                    "title": entry.title,
                    "retrieved": any(match.id == entry.id for match in matches),
                }
            )
        workspace_root = store.workspace_root
        workspace_files = (
            sorted(
                path.relative_to(workspace_root).as_posix()
                for path in workspace_root.rglob("*")
                if path.is_file()
            )
            if workspace_root.exists()
            else []
        )
        jobs = backend.transcript_store.list_distill_jobs(
            project_name=project_name,
            limit=100_000,
        )
        return {
            "entries": [entry.to_dict() for entry in entries],
            "entry_count": len(entries),
            "known_projects": known_projects,
            "source_counts": source_counts,
            "markdown": markdown,
            "readback": readback,
            "workspace_files": workspace_files,
            "job_statuses": {job.id: job.status for job in jobs},
            "job_sessions": {job.session_id: job.status for job in jobs},
            "answer_packet_sessions": sorted(
                job.session_id
                for job in jobs
                if isinstance(job.promotion_summary.get("answer_packet"), dict)
                and job.promotion_summary["answer_packet"]
            ),
            "note_sessions": sorted(
                path.stem for path in notes_dir.glob("*.md") if path.is_file()
            ),
            "canonical_sqlite": str(canonical_store_path(data_dir)),
            "quality": _quality_findings(entries, markdown),
        }
    finally:
        await backend.close()


async def _resume_retryable_cohort_jobs(
    *,
    data_dir: Path,
    notes_dir: Path,
    project_root: Path,
    session_ids: set[str],
) -> dict[str, Any]:
    """Resume only retryable jobs belonging to the frozen isolated cohort."""

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        jobs = [
            job
            for job in backend.transcript_store.list_distill_jobs(
                project_name=project_root.name,
                limit=100_000,
            )
            if job.session_id in session_ids and job.status == "retryable"
        ]
        current = datetime.now(timezone.utc)
        blocked = [
            job
            for job in jobs
            if job.retry_after is not None and job.retry_after > current
        ]
        if blocked:
            retry_at = min(job.retry_after for job in blocked if job.retry_after)
            raise RuntimeError(f"cohort retry backoff remains active until {retry_at}")
        config = load_merged_config(project_root)
        outcomes: list[dict[str, Any]] = []
        for job in jobs:
            outcome = await asyncio.to_thread(
                run_autonomous_distill_batch,
                backend,
                project_name=project_root.name,
                project_root=project_root,
                config=config,
                trigger_id=job.session_id,
                client="codex-archive",
                notes_dir=notes_dir,
                max_jobs=1,
                preferred_job_id=job.id,
                launch_source="archive_cohort_resume",
            )
            outcomes.append(outcome)
        return {
            "state": (
                "succeeded"
                if all(outcome.get("state") == "succeeded" for outcome in outcomes)
                else "failed"
            ),
            "resumed_job_ids": [job.id for job in jobs],
            "outcomes": outcomes,
        }
    finally:
        await backend.close()


async def run_acceptance(
    *,
    project_root: Path,
    source_archive_dir: Path,
    output_root: Path,
    count: int = DEFAULT_COUNT,
    resume: bool = False,
) -> dict[str, Any]:
    project_root = project_root.expanduser().resolve()
    source_archive_dir = source_archive_dir.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    real_data_dir = Path.home() / ".harness-mem" / "data"
    real_notes_dir = Path.home() / ".codex" / "hm-distill" / "sessions"
    _assert_isolated_paths(
        output_root=output_root,
        source_archive_dir=source_archive_dir,
        real_data_dir=real_data_dir,
        real_notes_dir=real_notes_dir,
    )
    if count != DEFAULT_COUNT:
        raise ValueError("0.9.20 acceptance requires exactly six sessions")
    if output_root.exists() and not resume:
        raise FileExistsError(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=resume)
    archive_dir = output_root / "archive"
    data_dir = output_root / "data"
    notes_dir = output_root / "notes"
    manifest_path = output_root / "cohort-manifest.json"
    if resume:
        manifest = _load_manifest(manifest_path, expected_count=count)
    else:
        selected = _select_project_sessions(
            project_root=project_root,
            source_archive_dir=source_archive_dir,
            count=count,
        )
        manifest = _copy_cohort(selected=selected, archive_dir=archive_dir)
        _write_json(
            manifest_path,
            {
                "schema_version": 1,
                "project_name": project_root.name,
                "project_root": str(project_root),
                "selection": "latest_first",
                "sessions": manifest,
            },
        )
    real_before = _real_state_fingerprint(
        real_data_dir=real_data_dir,
        real_notes_dir=real_notes_dir,
    )
    started_at = datetime.now(timezone.utc)
    if resume:
        processing = await _resume_retryable_cohort_jobs(
            data_dir=data_dir,
            notes_dir=notes_dir,
            project_root=project_root,
            session_ids={str(row["session_id"]) for row in manifest},
        )
    else:
        processing = await run_archive_distill_batch(
            control_root=project_root,
            apply=True,
            archive_dir=archive_dir,
            data_dir=data_dir,
            notes_dir=notes_dir,
            verify=True,
            batch_size=count,
            daily_limit=count,
        )
    inspected = await _inspect_isolated_result(
        data_dir=data_dir,
        notes_dir=notes_dir,
        project_name=project_root.name,
    )
    original_sources_unchanged = all(
        Path(str(row["source_path"])).is_file()
        and _sha256(Path(str(row["source_path"]))) == row["source_sha256"]
        for row in manifest
    )
    isolated_sources_unchanged = all(
        Path(str(row["isolated_path"])).is_file()
        and _sha256(Path(str(row["isolated_path"]))) == row["isolated_sha256"]
        for row in manifest
    )
    real_after = _real_state_fingerprint(
        real_data_dir=real_data_dir,
        real_notes_dir=real_notes_dir,
    )
    terminal_jobs = len(inspected["job_statuses"]) == count and all(
        status == "completed" for status in inspected["job_statuses"].values()
    )
    cohort_session_ids = sorted(str(row["session_id"]) for row in manifest)
    processing_passed = (
        processing.get("state") == "succeeded"
        if resume
        else (processing.get("verification") or {}).get("status") == "passed"
    )
    checks = {
        "exactly_six_selected": len(manifest) == count
        and len({row["session_id"] for row in manifest}) == count,
        "all_sources_are_harness_mem": all(
            row["project_name"] == project_root.name
            and Path(str(row["project_root"])).resolve() == project_root
            for row in manifest
        ),
        "cohort_completed_six": terminal_jobs
        and sorted(inspected["job_sessions"]) == cohort_session_ids,
        "latest_processing_passed": processing_passed,
        "only_harness_mem_knowledge": inspected["known_projects"]
        == [project_root.name],
        "meaningful_current_knowledge": inspected["entry_count"] > 0,
        "clean_projection": inspected["quality"]["passed"],
        "every_entry_retrievable": bool(inspected["readback"])
        and all(row["retrieved"] for row in inspected["readback"]),
        "all_jobs_terminal": terminal_jobs,
        "all_notes_materialized": inspected["note_sessions"] == cohort_session_ids,
        "all_answer_packets_persisted": inspected["answer_packet_sessions"]
        == cohort_session_ids,
        "terminal_workspace_clean": inspected["workspace_files"] == [],
        "original_archives_unchanged": original_sources_unchanged,
        "isolated_archives_retained": isolated_sources_unchanged,
        "real_runtime_state_unchanged": real_before == real_after,
    }
    report = {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "project_name": project_root.name,
        "project_root": str(project_root),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "isolated_paths": {
            "archive": str(archive_dir),
            "data": str(data_dir),
            "notes": str(notes_dir),
            "canonical_sqlite": inspected["canonical_sqlite"],
        },
        "cohort": manifest,
        "checks": checks,
        "processing": processing,
        "knowledge": {
            key: value for key, value in inspected.items() if key != "markdown"
        },
        "real_state_before": real_before,
        "real_state_after": real_after,
        "knowledge_markdown": str(output_root / "knowledge.md"),
    }
    (output_root / "knowledge.md").write_text(
        inspected["markdown"], encoding="utf-8"
    )
    _write_json(output_root / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--source-archive-dir",
        type=Path,
        default=Path.home() / ".codex" / "archived_sessions",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_acceptance(
            project_root=args.project_root,
            source_archive_dir=args.source_archive_dir,
            output_root=args.output_root,
            count=args.count,
            resume=args.resume,
        )
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_COUNT",
    "_assert_isolated_paths",
    "_quality_findings",
    "_select_project_sessions",
    "run_acceptance",
]
