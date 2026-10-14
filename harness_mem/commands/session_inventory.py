"""Project-scoped read-only session inventory and complete source pagination."""

from __future__ import annotations

from collections import Counter, OrderedDict
from contextlib import closing
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable
from collections.abc import Mapping
from urllib.parse import quote

from harness_mem.adapters.source_inspection import (
    HOSTS, InspectedSource, build_inspection_adapter, inspect_native_source,
    list_native_records, normalized_root,
    ownership_for,
    metadata_project_root,
)
from harness_mem.capture_policy import decide_capture, redact_private_text, redact_private_bytes, source_capture_policy, local_context_root
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.storage.canonical_store import CanonicalStoreRuntime, canonical_store_path
from harness_mem.storage.transcript_store import TranscriptStore
from harness_mem.transcript_chunking import sha256_text, transcript_source_id, source_uri_from_path


def session_reference(client: str, session_id: str, source_id: str, source_revision: str) -> dict[str, str]:
    identity = [client, session_id, source_id, source_revision]
    return dict(zip(("client", "session_id", "source_id", "source_revision"), identity),
                reference_id=sha256(json.dumps(identity).encode()).hexdigest())


def _project_context_labels(data_dir: Path) -> dict[str, set[str]]:
    """Read optional workspace labels, never infer name ownership from sources.

    Transcript roots describe where an earlier conversation happened. They do
    not reserve names, govern directories or constrain current memory retrieval.
    Profiles are only hints for the current caller context, not a name registry.
    """
    known: dict[str, set[str]] = {}
    for path in (data_dir / "profiles").glob("*.json"):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            root, name = normalized_root(profile.get("project_root", "")), profile.get("project_name")
            if root and isinstance(name, str) and name:
                known.setdefault(root, set()).add(name)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return known


def automatic_project_names(
    data_dir: Path, roots: list[str], *, bindings: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """Reuse context labels without reserving or automatically changing names."""
    known = bindings if bindings is not None else _project_context_labels(data_dir)
    roots = sorted(set(filter(None, (normalized_root(root) for root in roots))))
    result = {}
    for root in roots:
        existing = sorted(known.get(root, ()))
        base = Path(root).name
        result[root] = base if base in existing or not existing else existing[0]
    return result


def _metadata_source_uri(client: str, record: Mapping[str, Any]) -> str:
    path, identity = Path(record["path"]), str(record["session_id"])
    uri = source_uri_from_path(path)
    if client == "cursor" and path.suffix.lower() != ".jsonl":
        return "cursor-sqlite:" + path.absolute().as_uri() + "#" + quote(identity, safe="")
    if client in {"hermes", "opencode"} and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return uri + "#session=" + quote(identity, safe="")
    if client == "antigravity" and path.name == "history.jsonl":
        return uri + "#conversation=" + quote(identity, safe="")
    return uri


def _metadata_roots(record: Mapping[str, Any]) -> list[str]:
    return list(record.get("project_roots") or ([record["cwd"]] if record.get("cwd") else []))


def _metadata_row(client: str, record: Mapping[str, Any], project_name: str, project_root: Path | None) -> dict:
    roots = _metadata_roots(record)
    owner = ownership_for(roots, project_root) if project_root is not None else "source"
    token = sha256(json.dumps({
        "uri": _metadata_source_uri(client, record), "session": record["session_id"],
        "roots": roots, "mtime_ns": record.get("mtime_ns"), "bytes": record.get("size_bytes"),
    }, sort_keys=True).encode()).hexdigest()
    # Discovery identity is tied to the root, not a guessed/friendly name.
    # Preparation replaces it with the validated canonical source identity.
    source_id = transcript_source_id(client=client, project_name="metadata-root:" + normalized_root(project_root) if project_root is not None else "metadata-source",
                                    session_id=record["session_id"], source_uri=_metadata_source_uri(client, record))
    return {
        **session_reference(client, record["session_id"], source_id, "metadata:" + token),
        "project_root": normalized_root(project_root) if project_root is not None else metadata_project_root(roots), "project_name": project_name,
        "ownership": owner, "readability": "not_checked", "processing": "pending" if owner in {"project", "source"} else "not_selected",
        "imported": False, "origin": "native", "revision_verified": False,
        **({"scope": "all"} if project_root is None else {}),
    }


def discover_session_projects(
    data_dir: Path, *, clients: list[str] | None = None,
    adapter_factory: Callable[..., Any] | None = None,
) -> dict:
    """Discover all native project bindings without importing or rendering sessions."""
    selected = list(dict.fromkeys(HOSTS if clients is None else clients))
    if not selected or set(selected) - set(HOSTS):
        raise ValueError("clients must select supported hosts")
    factory = adapter_factory or build_inspection_adapter
    records: list[tuple[str, Mapping[str, Any]]] = []
    issues: list[dict] = []
    for client in selected:
        host_issues: list[dict[str, str]] = []
        try:
            adapter = factory(client)
            records.extend((client, record) for record in list_native_records(adapter, client, host_issues))
        except (OSError, ValueError, sqlite3.Error):
            issues.append({"client": client, "reason": "source_scan_failed"})
        issues.extend({"client": client, "reason": item.get("code", "source_scan_failed")} for item in host_issues)
    grouped: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    unknown: list[dict] = []
    for client, record in records:
        roots = _metadata_roots(record)
        root = metadata_project_root(roots)
        if not root:
            unknown.append({"client": client, "session_id": record["session_id"], "reason": "project_not_determined"})
            continue
        grouped.setdefault(root, []).append((client, record))
    names = automatic_project_names(data_dir, list(grouped))
    projects = []
    for root, items in sorted(grouped.items()):
        rows = [_metadata_row(client, record, names[root], Path(root)) for client, record in items]
        available = Path(root).is_dir()
        if available:
            try:
                config = load_merged_config(root)
            except (OSError, ValueError):
                available = False
                issues.append({"project_root": root, "reason": "project_configuration_unreadable"})
                for row in rows:
                    row.update(readability="unreadable", processing="blocked")
            else:
                for row, (client, record) in zip(rows, items):
                    if not decide_capture(config, client=client, session_id=record["session_id"],
                                          source_uri=_metadata_source_uri(client, record)).admitted:
                        row.update(readability="excluded", processing="skipped")
        projects.append({"project_root": root, "project_name": names[root],
                         "available": available, "counts": {"sessions": len(rows)}, "sessions": rows})
    return {"success": True, "discovery": "metadata_only", "projects": projects,
            "unclassified": unknown, "issues": issues, "processing_unchanged": True}


def resolve_session_scope(
    data_dir: Path, *, project_root: str | None = None, project_name: str | None = None,
    sessions: list[dict] | None = None, batch_id: str | None = None,
) -> tuple[str, Path | None] | None:
    """Resolve native or frozen scope; a Router's cwd/active-project is not a caller workspace."""
    if batch_id:
        from harness_mem.storage.manual_batch_store import ManualBatchStore
        name, root = ManualBatchStore(data_dir).read_scope(batch_id)
        if ((project_root and (root is None or normalized_root(project_root) != normalized_root(root)))
                or (project_name and project_name != name)):
            raise ValueError("batch belongs to another project")
        return name, root
    selected = sessions or []
    roots = set(filter(None, (normalized_root(item.get("project_root", "")) for item in selected)))
    if len(roots) > 1:
        raise ValueError("process each automatically discovered project independently")
    hinted_root = project_root or (next(iter(roots)) if roots else None)
    if not hinted_root and project_name:
        matches = [root for root, names in _project_context_labels(data_dir).items() if project_name in names]
        if len(matches) == 1:
            hinted_root = matches[0]
    if hinted_root:
        root = Path(hinted_root).expanduser()
        if not root.is_absolute():
            raise ValueError("the source workspace must be an absolute path")
        names = {str(item["project_name"]) for item in selected if item.get("project_name")}
        if len(names) > 1:
            raise ValueError("selected sessions have conflicting project bindings")
        bindings = _project_context_labels(data_dir)
        automatic = automatic_project_names(data_dir, [str(root)], bindings=bindings)[normalized_root(root)]
        # A current workspace profile can refresh a stale discovery label.
        # Historical transcript roots never reserve or force a different name.
        binding_exists = normalized_root(root) in bindings
        name = project_name or (automatic if binding_exists else next(iter(names)) if names else automatic)
        return name, root
    if selected:
        if (data_dir / "transcript_ledger.sqlite").is_file():
            with closing(TranscriptStore(data_dir, read_only=True)) as ledger:
                sources = [ledger.get_source(str(item.get("source_id"))) for item in selected]
            if all(source is not None for source in sources):
                ledger_scopes = {(source.project_name, normalized_root(source.project_root)) for source in sources if source}
                if len(ledger_scopes) == 1:
                    name, root_text = next(iter(ledger_scopes))
                    return name, Path(root_text)
        found = []
        for project in discover_session_projects(data_dir, clients=sorted({item["client"] for item in selected}))["projects"]:
            if any(all(row.get(field) == item.get(field) for field in ("client", "session_id", "source_id"))
                   for row in project["sessions"] for item in selected):
                found.append(project)
        if len(found) == 1:
            return found[0]["project_name"], Path(found[0]["project_root"])
        raise ValueError("selected sessions do not have one verified project binding")
    return None


def current_entries(data_dir: Path, project_name: str | None) -> dict[str, dict]:
    if not canonical_store_path(data_dir).is_file():
        return {}
    with closing(CanonicalStoreRuntime(data_dir, read_only=True)) as store:
        return {item["id"]: item for item in store.list_payloads("knowledge_entries", project_name=project_name)}


def completion_proven(job: SessionDistillJob, entries: dict[str, dict], *, superseded: set[str] | None = None) -> bool:
    """Conservative current proof, not a packet-exists or status-only shortcut."""
    if job.status != "completed" or job.completion_disposition is None:
        return False
    audit = job.structural_audit
    if (audit.get("coverage") != "complete" or audit.get("expected_chunks") != job.expected_chunk_count
            or audit.get("completed_chunks") != job.expected_chunk_count
            or job.completed_chunk_count != job.expected_chunk_count):
        return False
    summary = job.promotion_summary
    if summary.get("pending", 0) or summary.get("missing", 0):
        return False
    points = summary.get("points") or []
    if {p.get("candidate_id") for p in points} != set(job.output_candidate_ids):
        return False
    writes = [p for p in points if p.get("disposition") in {"add", "refine", "replace"}]
    if len(writes) != int(summary.get("promoted") or 0):
        return False
    for point in writes:
        ids = point.get("canonical_truth_ids") or []
        if not ids or any(value not in entries and value not in (superseded or set()) for value in ids):
            return False
        if any(value in entries for value in point.get("replaced_truth_ids") or []):
            return False
    # Legacy completion without readback remains needs_verification.
    receipt = summary.get("readback")
    if not isinstance(receipt, dict) or receipt.get("source_revision") != job.source_revision or receipt.get("verified") is not True:
        return False
    if points:
        return True
    if not job.semantic_review.get("zero_candidate_challenge"):
        if receipt.get("handoff_ids") and job.semantic_review.get("unfinished_work"):
            return bool(job.semantic_review.get("promotion_decision") == "partial"
                        and str(job.semantic_review.get("session_summary") or "").strip())
        return bool(
            job.completion_disposition == "no_candidate"
            and job.semantic_review.get("promotion_decision") == "no_promotion"
            and str(job.semantic_review.get("session_summary") or "").strip()
            and not receipt.get("handoff_ids")
            and not job.semantic_review.get("unfinished_work")
        )
    challenge = job.semantic_review.get("zero_candidate_challenge") or {}
    terminal_challenge = (challenge.get("conclusion") == "no_durable_candidate"
                          and challenge.get("future_utility") in {"none", "session_only"})
    preserved_handoff = (challenge.get("conclusion") == "candidate_required"
                         and bool(receipt.get("handoff_ids"))
                         and bool(job.semantic_review.get("unfinished_work")))
    return bool(job.zero_candidate_challenge_version == "v1"
                and challenge.get("source_revision") == job.source_revision
                and challenge.get("evidence_fidelity") == "complete"
                and (terminal_challenge or preserved_handoff))


def completed_job_ids(jobs: list[SessionDistillJob], entries: dict[str, dict]) -> tuple[set[str], set[str]]:
    """Resolve only proven replacement chains ending in current knowledge.

    This is a projection of existing temporary job receipts, not stored history.
    A missing final entry or a cycle cannot certify any predecessor.
    """
    completed: set[str] = set()
    superseded: set[str] = set()
    while True:
        newly_proven = [job for job in jobs if job.id not in completed
                        and completion_proven(job, entries, superseded=superseded)]
        if not newly_proven:
            return completed, superseded
        for job in newly_proven:
            completed.add(job.id)
            for point in job.promotion_summary.get("points") or []:
                if point.get("disposition") in {"refine", "replace"}:
                    superseded.update(point.get("replaced_truth_ids") or [])


@dataclass
class SessionInventory:
    project_name: str
    project_root: str
    rows: list[dict] = field(default_factory=list)
    native: dict[str, InspectedSource] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "success": True,
            "project_name": self.project_name,
            "project_root": self.project_root,
            **({"scope": "all"} if not self.project_root else {}),
            "counts": {
                "sessions": len(self.rows),
                "ownership": dict(Counter(row["ownership"] for row in self.rows)),
                "readability": dict(Counter(row["readability"] for row in self.rows)),
                "processing": dict(Counter(row["processing"] for row in self.rows if row["ownership"] in {"project", "source"})),
            },
            "sessions": self.rows,
            **({"issues": self.issues} if self.issues else {}),
        }


def collect_session_inventory(
    data_dir: Path, *, project_root: Path | None = None, project_name: str = "global",
    clients: list[str] | None = None,
    adapter_factory: Callable[..., Any] | None = None,
    lightweight: bool = False,
    selected_sessions: list[dict] | None = None,
) -> SessionInventory:
    if project_root is not None and not project_root.is_absolute():
        raise ValueError("project_root must be absolute")
    selected = list(dict.fromkeys(HOSTS if clients is None else
                                  ("codex" if client == "codex-archive" else client for client in clients)))
    if not selected or set(selected) - set(HOSTS):
        raise ValueError("clients must select supported hosts")
    config = load_merged_config(str(project_root) if project_root is not None and project_root.is_dir() else None)
    adapter_factory = adapter_factory or build_inspection_adapter
    result = SessionInventory(project_name, normalized_root(project_root) if project_root is not None else "")
    sources = []
    jobs: list[SessionDistillJob] = []
    if (data_dir / "transcript_ledger.sqlite").is_file():
        with closing(TranscriptStore(data_dir, read_only=True)) as ledger:
            sources = [source for source in ledger.list_sources(project_name=project_name if project_root is not None else None, limit=None)
                       if (source.client in selected or source.client == "codex-archive" and "codex" in selected)
                       and (project_root is None or normalized_root(source.project_root) == normalized_root(project_root))]
            jobs = [job for job in ledger.list_distill_jobs(project_name=project_name if project_root is not None else None)
                    if project_root is None or normalized_root(job.project_root) == normalized_root(project_root)]
    entries = current_entries(data_dir, project_name if project_root is not None else None)
    proven, _ = completed_job_ids(jobs, entries)
    seen_sources: set[str] = set()
    by_identity: dict[tuple[str, str, str], dict] = {}
    for client in selected:
        issues: list[dict[str, str]] = []
        try:
            adapter = adapter_factory(client)
            records = list_native_records(adapter, client, issues)
        except (OSError, ValueError, sqlite3.Error):
            result.issues.append({"client": client, "reason": "source_scan_failed"})
            continue
        for issue in issues:
            result.issues.append({"client": client, "reason": issue.get("code", "source_scan_failed")})
        for record in records:
            preliminary = _metadata_row(client, record, project_name, project_root)
            record_sources = [source for source in sources if source.client == client
                              and source.session_id == record["session_id"]
                              and source.source_uri == _metadata_source_uri(client, record)]
            record_config = config
            if project_root is None:
                try:
                    record_config = source_capture_policy(_metadata_roots(record), config_loader=load_merged_config)
                except (OSError, ValueError):
                    result.rows.append({**preliminary, "readability": "unreadable", "processing": "blocked"})
                    result.issues.append({"client": client, "session_id": record["session_id"], "reason": "source_policy_unreadable"})
                    continue
            if selected_sessions is not None and not any(
                item.get("client") == client and item.get("session_id") == record.get("session_id")
                and item.get("source_id") == (
                    preliminary["source_id"] if str(item.get("source_revision", "")).startswith("metadata:")
                    else str(item.get("source_id")) if project_root is None and any(source.id == item.get("source_id") for source in record_sources)
                    else transcript_source_id(client=client, project_name=project_name, session_id=record["session_id"],
                                              source_uri=_metadata_source_uri(client, record))
                ) for item in selected_sessions
            ):
                continue
            if lightweight or (project_root is not None and "project_roots" in record and preliminary["ownership"] != "project"):
                matching = [source for source in sources if source.client == client
                            and source.session_id == record["session_id"]
                            and source.source_uri == _metadata_source_uri(client, record)]
                seen_sources.update(source.id for source in matching)
                preliminary["imported"] = bool(matching)
                if matching and preliminary["ownership"] in {"project", "source"}:
                    preliminary["processing"] = "needs_verification"
                if not decide_capture(record_config, client=client, session_id=record["session_id"],
                                      source_uri=_metadata_source_uri(client, record)).admitted:
                    preliminary.update(readability="excluded", processing="skipped")
                result.rows.append(preliminary)
                continue
            try:
                preview_stamps = _record_dependency_stamps(record)
                native = inspect_native_source(adapter, client, record, project_root=project_root, config=record_config)
                if project_root is None:
                    full_stamps = _record_dependency_stamps({**record, "project_roots": native.project_roots or []})
                    record_config = source_capture_policy(native.project_roots or [], config_loader=load_merged_config)
                    native.capture_config = record_config
                    if not decide_capture(record_config, client=client, session_id=native.session_id, source_uri=native.source_uri).admitted:
                        native.readability, native.captured_bytes, native.text = "excluded", None, ""
                        native.native_input_bytes, native.authored_user_texts = None, None
                        native.native_input_digest = None
                    elif record_config.capture_private_tags:
                        native.text, _ = redact_private_text(native.text)
                        if native.captured_bytes is not None:
                            native.captured_bytes, _ = redact_private_bytes(native.captured_bytes)
                            native.native_digest = sha256(native.captured_bytes).hexdigest()
                    if not _unchanged(full_stamps):
                        raise ValueError("source policy changed during complete read")
                    preview_stamps = list(dict.fromkeys([*preview_stamps, *full_stamps]))
                if not _unchanged(preview_stamps):
                    raise ValueError("source or workspace metadata changed during complete read")
                native.preview_stamps = preview_stamps
            except (OSError, ValueError, TypeError, sqlite3.Error, UnicodeError) as exc:
                reason = "source_dependencies_changed" if isinstance(exc, ValueError) and str(exc) in {
                    "source policy changed during complete read",
                    "source or workspace metadata changed during complete read",
                } else "source_unreadable"
                result.issues.append({"client": client, "session_id": record.get("session_id"), "reason": reason,
                                      "error_type": type(exc).__name__})
                result.rows.append({"client": client, "session_id": record.get("session_id"), "ownership": "unknown", "readability": "unreadable", "processing": "not_selected"})
                continue
            source_id = transcript_source_id(client=client, project_name=project_name, session_id=native.session_id, source_uri=native.source_uri)
            reference = session_reference(client, native.session_id, source_id, f"sha256:{native.native_digest}")
            matching = [source for source in sources if source.client == client and source.session_id == native.session_id
                        and (source.source_uri == native.source_uri or source.raw_sha256 == native.native_digest)]
            matching_jobs = [job for job in jobs for source in matching if job.source_id == source.id
                             and job.source_revision == source.source_revision
                             and source.raw_sha256 == native.native_digest]
            seen_sources.update(source.id for source in matching)
            job = max(matching_jobs, key=lambda value: value.updated_at) if matching_jobs else None
            if project_root is None and job is not None:
                reference = session_reference(job.client, job.session_id, job.source_id, job.source_revision)
            processing = "pending"
            if native.ownership not in {"project", "source"}:
                processing = "not_selected"
            elif native.readability in {"empty_source", "empty_draft", "excluded"}:
                processing = "skipped"
            elif native.readability != "readable":
                processing = "blocked"
            elif job is not None:
                processing = "completed" if job.id in proven else "needs_verification" if job.status == "completed" else job.status
            row = {**reference, "ownership": native.ownership, "readability": native.readability, "processing": processing,
                   "imported": bool(matching_jobs), "origin": "native", "revision_verified": True,
                   "project_root": normalized_root(project_root) if project_root is not None else job.project_root if job is not None else metadata_project_root(native.project_roots or _metadata_roots(record)),
                   "project_name": job.project_name if project_root is None and job is not None else project_name,
                   **({"scope": "all"} if project_root is None else {})}
            row["metadata_reference_id"] = preliminary["reference_id"]
            if job is not None:
                row["job_id"] = job.id
            # Only identical host identity AND bytes deduplicate native copies.
            key = (client, native.session_id, native.native_digest)
            if native.native_digest and key in by_identity:
                previous = by_identity[key]
                if previous["ownership"] != row["ownership"]:
                    previous.update(ownership="unknown", processing="not_selected")
                    result.native.pop(previous["reference_id"], None)
                continue
            by_identity[key] = row
            result.rows.append(row)
            if native.ownership in {"project", "source"} and native.readability != "excluded":
                result.native[reference["reference_id"]] = native
        # Unknown/other ownership is counted, never eligible for a manual batch.
    for source in sources:
        if selected_sessions is not None and not any(
            item.get("source_id") == source.id for item in selected_sessions
        ):
            continue
        if source.id in seen_sources:
            continue
        ledger_config = config
        if project_root is None:
            ledger_config = source_capture_policy(source.metadata.get("source_context_roots")
                                                 or ([source.project_root] if source.project_root else []), config_loader=load_merged_config)
        allowed = decide_capture(ledger_config, client=source.client, session_id=source.session_id, source_uri=source.source_uri).admitted
        matching_jobs = [job for job in jobs if job.source_id == source.id and job.source_revision == source.source_revision]
        job = max(matching_jobs, key=lambda value: value.updated_at) if matching_jobs else None
        reference = session_reference(source.client, source.session_id, source.id, source.source_revision)
        result.rows.append({**reference, "ownership": "project" if project_root is not None else "source", "readability": "excluded" if not allowed else "readable" if source.coverage == "complete" else "partial",
                            "processing": "skipped" if not allowed else "completed" if job and job.id in proven else "needs_verification" if job and job.status == "completed" else job.status if job else "pending",
                            "imported": True, "origin": "ledger", "project_name": source.project_name, "project_root": source.project_root,
                            **({"scope": "all"} if project_root is None else {}), **({"job_id": job.id} if job else {})})
    result.rows.sort(key=lambda row: (row["client"], row.get("session_id", ""), row.get("source_id", ""), row.get("source_revision", "")))
    return result


# Read-only previews are ephemeral and bounded, not source or memory authority.
# Selected-source preparation always performs independent complete validation.
_PAGE_CACHE: OrderedDict[tuple[str, ...], tuple[dict, str, list[tuple[Path, int, int]]]] = OrderedDict()
_PAGE_CACHE_CHARS = 16000000


def _dependency_stamps(native: InspectedSource) -> list[tuple[Path, int, int]]:
    return native.preview_stamps if native.preview_stamps is not None else _record_dependency_stamps(native.record)


def _record_dependency_stamps(record: Mapping[str, Any]) -> list[tuple[Path, int, int]]:
    paths = [Path(record["path"]), *(Path(path) for path in record.get("metadata_paths", []))]
    for root in _metadata_roots(record):
        local_root = local_context_root(root)
        if local_root is not None:
            paths.append(local_root / ".harness-mem.toml")
    result = []
    for path in dict.fromkeys(paths):
        try:
            stat = path.stat()
            result.append((path, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            result.append((path, -1, -1))
    return result


def _unchanged(stamps: list[tuple[Path, int, int]]) -> bool:
    try:
        for path, mtime, size in stamps:
            try:
                stat = path.stat()
                actual = (stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                actual = (-1, -1)
            if actual != (mtime, size):
                return False
        return True
    except OSError:
        return False


def read_session_page(
    data_dir: Path, *, project_root: Path | None = None, project_name: str = "global", session: dict,
    offset: int = 0, page_chars: int = 16000,
    adapter_factory: Callable[..., Any] | None = None,
) -> dict:
    if offset < 0 or page_chars < 1 or page_chars > 200000:
        raise ValueError("invalid source page range")
    expected = session_reference(*(str(session.get(key) or "") for key in ("client", "session_id", "source_id", "source_revision")))
    if session.get("reference_id") != expected["reference_id"]:
        raise ValueError("invalid session reference")
    config = load_merged_config(str(project_root) if project_root is not None and project_root.is_dir() else None)
    text: str | None = None
    verified = expected
    context_root = normalized_root(project_root) if project_root is not None else ""
    context_name = project_name
    if (data_dir / "transcript_ledger.sqlite").is_file():
        with closing(TranscriptStore(data_dir, read_only=True)) as ledger:
            revision = ledger.get_revision(session["source_id"], session["source_revision"])
            if revision is not None:
                if ((project_root is not None and (revision.project_name != project_name or normalized_root(revision.project_root) != normalized_root(project_root)))
                        or revision.client != session["client"] or revision.session_id != session["session_id"]):
                    raise ValueError("source belongs to another project or session")
                if project_root is None:
                    context_root, context_name = revision.project_root, revision.project_name
                    config = source_capture_policy(revision.metadata.get("source_context_roots")
                                                   or ([context_root] if context_root else []), config_loader=load_merged_config)
                if not decide_capture(config, client=revision.client, session_id=revision.session_id, source_uri=revision.source_uri).admitted:
                    raise ValueError("source excluded by capture policy")
                if revision.coverage != "complete":
                    raise ValueError("source coverage is incomplete")
                text = ledger.reconstruct(revision.source_id, source_revision=revision.source_revision)
    if text is None:
        namespace = (str(data_dir.resolve()), normalized_root(project_root) if project_root is not None else "", project_name,
                     expected["client"], expected["source_id"], sha256(repr((
                         config.capture_enabled, config.capture_private_tags, config.capture_ignore_clients,
                         config.capture_ignore_session_ids, config.capture_ignore_source_globs,
                     )).encode()).hexdigest())
        key = (*namespace, expected["reference_id"])
        cached = _PAGE_CACHE.get(key)
        if cached is not None and _unchanged(cached[2]):
            verified, text, _ = cached
            _PAGE_CACHE.move_to_end(key)
        else:
            _PAGE_CACHE.pop(key, None)
            inventory = collect_session_inventory(data_dir, project_root=project_root, project_name=project_name,
                                                  clients=[session["client"]], adapter_factory=adapter_factory,
                                                  selected_sessions=[expected])
            row = next((row for row in inventory.rows if row.get("reference_id") == expected["reference_id"]
                        or (expected["source_revision"].startswith("metadata:")
                            and row.get("metadata_reference_id") == expected["reference_id"])), None)
            native = inventory.native.get(row["reference_id"]) if row is not None else None
            if native is None or row is None or native.ownership not in {"project", "source"}:
                raise ValueError("source revision changed, unavailable, or outside project")
            verified = session_reference(*(str(row[field]) for field in ("client", "session_id", "source_id", "source_revision")))
            context_root, context_name = row.get("project_root", ""), row.get("project_name", project_name)
            text = native.text
            if len(text) <= _PAGE_CACHE_CHARS:
                stamps = _dependency_stamps(native)
                _PAGE_CACHE[key] = ({**verified, "project_root": context_root, "project_name": context_name}, text, stamps)
                while sum(len(item[1]) for item in _PAGE_CACHE.values()) > _PAGE_CACHE_CHARS:
                    _PAGE_CACHE.popitem(last=False)
    if config.capture_private_tags:
        text, _ = redact_private_text(text)
    if offset > len(text):
        raise ValueError("source offset exceeds complete text")
    end = min(len(text), offset + page_chars)
    verified = {**verified, "project_root": verified.get("project_root", context_root), "project_name": verified.get("project_name", context_name),
                **({"scope": "all"} if project_root is None else {})}
    return {"success": True, "session": expected, "verified_session": verified,
            "revision_verified": True, "offset": offset, "end": end,
            "total_chars": len(text), "content": text[offset:end], "content_sha256": sha256_text(text),
            "next_offset": end if end < len(text) else None,
            "complete": offset == 0 and end == len(text)}
