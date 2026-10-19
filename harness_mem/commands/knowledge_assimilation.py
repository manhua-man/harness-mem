"""Write verified candidate decisions to the current knowledge repository."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence, cast
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeCandidateStatus,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.commands.evidence_admission import (
    validate_candidate_evidence,
    validate_knowledge_sources,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


class KnowledgeTargetError(ValueError):
    """A readable current-memory selection cannot be resolved safely."""


def normalize_knowledge_targets(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Use the same title, statement and module fields as normal search."""
    targets: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping) or set(value) - {"title", "statement", "module", "project_name"}:
            raise KnowledgeTargetError("请用旧记忆的标题、内容和可选分类说明要改哪条。")
        target: dict[str, Any] = {}
        for key in ("title", "statement"):
            if key in value:
                if not isinstance(value[key], str) or not value[key].strip():
                    raise KnowledgeTargetError("要修改的旧记忆描述不能为空。")
                target[key] = " ".join(value[key].split())
        if not target:
            raise KnowledgeTargetError("请说明要修改的旧记忆标题或内容。")
        if "module" in value:
            module = value["module"]
            if not isinstance(module, list) or any(not isinstance(part, str) or not part.strip() for part in module):
                raise KnowledgeTargetError("旧记忆的分类应使用搜索结果中的分类文字。")
            target["module"] = [part.strip() for part in module]
        if "project_name" in value:
            if not isinstance(value["project_name"], str) or not value["project_name"].strip():
                raise KnowledgeTargetError("旧记忆的范围应使用搜索结果中的文字。")
            target["project_name"] = value["project_name"].strip()
        targets.append(target)
    return targets


async def resolve_knowledge_targets(
    store: Any, *, project_name: str,
    target_knowledge: Sequence[Mapping[str, Any]] = (),
    target_ids: Sequence[str] = (),
) -> list[str]:
    """Resolve exact readable selections inside one project, never guess IDs."""
    references = normalize_knowledge_targets(target_knowledge)
    if any(target.get("project_name", project_name) != project_name for target in references):
        raise KnowledgeTargetError("要修改的旧记忆不属于所选范围，原内容未改动。")
    ids = [str(value).strip() for value in target_ids]
    if references and ids:
        raise KnowledgeTargetError("请只用一种方式指定要修改的旧记忆。")
    entries = await store.list_entries(project_name)
    current_ids = {entry.id for entry in entries}
    if ids:
        if len(ids) != len(set(ids)) or any(not value or value not in current_ids for value in ids):
            raise KnowledgeTargetError("要修改的旧记忆已不存在或不属于当前项目，原内容未改动。")
        return ids
    resolved: list[str] = []
    for reference in references:
        matches = [entry for entry in entries if all(
            " ".join(getattr(entry, key).split()).casefold() == reference[key].casefold()
            for key in ("title", "statement") if key in reference
        ) and ("module" not in reference or entry.module_path == reference["module"])]
        if not matches:
            raise KnowledgeTargetError("没有找到这条旧记忆，原内容未改动；请核对标题或内容。")
        if len(matches) != 1 or matches[0].id in resolved:
            raise KnowledgeTargetError("有多条记忆符合这个描述，原内容未改动；请补充旧内容或分类。")
        resolved.append(matches[0].id)
    return resolved


async def resolve_knowledge_target_project(
    store: Any, target_knowledge: Sequence[Mapping[str, Any]],
) -> str:
    """Find the unique owner of an exact readable current-memory selection."""
    references = normalize_knowledge_targets(target_knowledge)
    if not references:
        raise KnowledgeTargetError("请说明要更正的旧记忆。")
    named_projects = {item["project_name"] for item in references if "project_name" in item}
    if len(named_projects) > 1:
        raise KnowledgeTargetError("一次更正的旧记忆须属于同一范围，原内容未改动。")
    projects = sorted(named_projects) if named_projects else await store.known_projects()
    owners: list[str] = []
    for name in projects:
        try:
            await resolve_knowledge_targets(store, project_name=name, target_knowledge=references)
        except KnowledgeTargetError:
            continue
        owners.append(name)
    if len(owners) != 1:
        raise KnowledgeTargetError("旧记忆已变化或描述不唯一，请重新搜索定位；原内容未改动。")
    return owners[0]


async def record_assimilation_result(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    point: Mapping[str, Any],
    project_root: str | Path | None = None,
    source_refs: Sequence[ProjectKnowledgeSourceRef] = (),
    expected_predecessor_entries: Sequence[KnowledgeEntry] | None = None,
) -> list[str]:
    """Write clean current entries for one verified point."""

    store = backend.structured_store.knowledge_store
    candidate_before = candidate.model_copy(deep=True)
    disposition = _disposition(point)
    if disposition in {"add", "refine", "replace", "confirm"} and (
        not project_root or not source_refs
    ):
        resolved_root, resolved_refs, resolved_verified_at = (
            await resolve_candidate_source_context(
                backend,
                candidate=candidate,
                evidence_items=await store.list_evidence(candidate.id),
                project_root=project_root,
            )
        )
        project_root = resolved_root
        if not source_refs:
            source_refs = resolved_refs
        if point.get("verified_at") is None and resolved_verified_at is not None:
            point = {**point, "verified_at": resolved_verified_at}
    knowledge_ids: list[str] = []
    matched_truth_ids = [str(item) for item in point.get("matched_truth_ids") or []]
    expected_by_id = ({entry.id: entry for entry in expected_predecessor_entries}
                      if expected_predecessor_entries is not None else None)
    if expected_by_id is not None and (
        len(expected_by_id) != len(expected_predecessor_entries or ())
        or set(expected_by_id) != set(matched_truth_ids)
        or any(entry.project_name != candidate.project_name for entry in expected_by_id.values())
    ):
        raise CanonicalTransactionPreconditionError("knowledge predecessor expectation scope changed")
    for target_id in matched_truth_ids:
        target = await store.get_entry(target_id, project_name=candidate.project_name)
        if target is not None and disposition in {"refine", "replace", "confirm"}:
            if (candidate.source_report is None) != (target.source_report is None):
                raise ValueError("source-report and fact authority boundary cannot be crossed")
            if candidate.source_report is not None:
                if not candidate.source_report.same_account_source(target.source_report):
                    raise ValueError("source-report updates cannot cross source, speaker, or period")
                if disposition == "confirm" and target.statement != candidate.source_report.render_statement():
                    raise ValueError("source-report confirmation requires the identical attributed account")
    predecessor_truth_ids: list[str] = []
    predecessor_entries: list[KnowledgeEntry] = []
    new_entries: list[KnowledgeEntry] = []
    decision_id: str | None = None
    if disposition in {"add", "refine", "replace"}:
        for _index, item in enumerate(_candidate_knowledge_items(candidate, point), 1):
            if not source_refs:
                raise ValueError("knowledge write requires a real source reference")
            entry = KnowledgeEntry(
                id=_knowledge_item_id(candidate.project_name, item),
                project_name=candidate.project_name,
                title=item["title"],
                statement=item["statement"],
                source_report=candidate.source_report,
                module_path=item["topic_path"],
                verified_at=(
                    point.get("verified_at")
                    or getattr(candidate, "verified_at", None)
                ),
            )
            new_entries.append(entry)
            knowledge_ids.append(entry.id)
        decision_id = assimilation_decision_id(
            candidate_id=candidate.id,
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            predecessor_ids=matched_truth_ids,
            reason=str(point.get("reason", "")),
        )
        if await store.current_change_committed(decision_id):
            current_entries_match = await _current_entries_match(
                store,
                project_name=candidate.project_name,
                expected_entries=new_entries,
            )
            predecessor_still_current = False
            for entry_id in matched_truth_ids:
                if await store.get_entry(
                    entry_id,
                    project_name=candidate.project_name,
                ) is not None:
                    predecessor_still_current = True
                    break
            if not current_entries_match or predecessor_still_current:
                raise RuntimeError(
                    "committed knowledge change no longer matches current knowledge"
                )
            await _verify_normal_search_after_truth_write(
                backend,
                project_name=candidate.project_name,
                project_root=_optional_project_root(project_root),
                added_entries=new_entries,
                predecessor_entries=[],
            )
            candidate.status = _separated_status(disposition)
            await store.save_candidate(candidate)
            return knowledge_ids
        if disposition in {"refine", "replace"}:
            missing_target_ids: list[str] = []
            for target_id in matched_truth_ids:
                target = await store.get_entry(
                    target_id,
                    project_name=candidate.project_name,
                    project_root=project_root,
                )
                if target is None:
                    if expected_by_id is not None:
                        raise CanonicalTransactionPreconditionError("knowledge predecessor disappeared after verification")
                    missing_target_ids.append(target_id)
                    continue
                if expected_by_id is not None and target.to_dict() != expected_by_id[target_id].to_dict():
                    raise CanonicalTransactionPreconditionError("knowledge predecessor changed after verification")
                predecessor_truth_ids.append(target.id)
                predecessor_entries.append(expected_by_id[target_id] if expected_by_id is not None else target)
            if missing_target_ids:
                raise ValueError(
                    "assimilation replacement target is not current knowledge"
                )
            if len(predecessor_entries) == 1 and any(
                entry.project_name == predecessor.project_name
                and entry.module_path == predecessor.module_path
                and entry.title == predecessor.title
                and entry.statement == predecessor.statement
                for entry in new_entries
                for predecessor in predecessor_entries
            ):
                raise ValueError(
                    f"{disposition} replacement is identical to current knowledge; "
                    "use confirm"
                )
    elif disposition == "confirm":
        if expected_by_id is not None:
            for target_id, expected in expected_by_id.items():
                target = await store.get_entry(target_id, project_name=candidate.project_name)
                if target is None or target.to_dict() != expected.to_dict():
                    raise CanonicalTransactionPreconditionError("knowledge confirmation target changed after verification")
        knowledge_ids = [
            target_id
            for target_id in matched_truth_ids
            if await store.get_entry(
                target_id,
                project_name=candidate.project_name,
                project_root=project_root,
            )
            is not None
        ]
        if len(knowledge_ids) != 1:
            raise ValueError("confirm target is no longer current project knowledge")

    candidate.status = _separated_status(disposition)
    decision = AssimilationDecision(
        id=decision_id
        or assimilation_decision_id(
            candidate_id=candidate.id,
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            predecessor_ids=matched_truth_ids,
            reason=str(point.get("reason", "")),
        ),
        project_name=candidate.project_name,
        candidate_id=candidate.id,
        disposition=disposition,
        canonical_truth_ids=knowledge_ids,
        predecessor_truth_ids=predecessor_truth_ids,
        predecessor_entries=predecessor_entries,
        reason=str(point.get("reason") or disposition),
    )
    if new_entries:
        await store.apply_current_change(
            project_root=_optional_project_root(project_root),
            candidate_before=candidate_before,
            candidate_after=candidate,
            decision=decision,
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
            source_refs_by_entry={
                entry.id: list(source_refs) for entry in new_entries
            },
        )
        await _verify_normal_search_after_truth_write(
            backend,
            project_name=candidate.project_name,
            project_root=_optional_project_root(project_root),
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
        )
        # The SQLite truth transaction is the commit point.  Persisting a
        # terminal workspace status before it succeeds would make a retry skip
        # a candidate whose durable knowledge was never written.
        await store.save_candidate(candidate)
    else:
        await store.save_candidate(candidate)
        await store.save_decision(decision, project_root=project_root)
    return knowledge_ids


def _knowledge_item_id(project_name: str, item: Mapping[str, Any]) -> str:
    identity = "\0".join([project_name, *item["topic_path"], item["title"], item["statement"]])
    return str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge:{identity}"))


async def is_committed_knowledge_point(
    backend: LocalMemoryBackend, *, candidate: KnowledgeCandidate, point: Mapping[str, Any],
) -> bool:
    """Prove an exact write replay without trusting caller-supplied outputs."""
    disposition = _disposition(point)
    if candidate.status != "assimilated" or disposition not in {"add", "refine", "replace"}:
        return False
    decision_id = assimilation_decision_id(
        candidate_id=candidate.id, disposition=disposition,
        knowledge_ids=[_knowledge_item_id(candidate.project_name, item) for item in _candidate_knowledge_items(candidate, point)],
        predecessor_ids=[str(value) for value in point.get("matched_truth_ids") or []],
        reason=str(point.get("reason", "")),
    )
    return await backend.structured_store.knowledge_store.current_change_committed(decision_id)


async def _verify_normal_search_after_truth_write(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path | None,
    added_entries: Sequence[KnowledgeEntry],
    predecessor_entries: Sequence[KnowledgeEntry],
) -> None:
    """Require the ordinary search path to observe the committed mutation."""

    from harness_mem.read_knowledge import search_current_knowledge

    for entry in added_entries:
        results = await search_current_knowledge(
            backend,
            project_name=project_name,
            query=entry.statement,
            limit=100000,
            project_root=project_root,
        )
        if not any(item.id == entry.id for item in results):
            raise RuntimeError(
                "current knowledge write is not readable through normal search"
            )
    for predecessor in predecessor_entries:
        results = await search_current_knowledge(
            backend,
            project_name=project_name,
            query=predecessor.statement,
            limit=100000,
            project_root=project_root,
        )
        if any(item.id == predecessor.id for item in results):
            raise RuntimeError(
                "replaced knowledge remains readable through normal search"
            )


def assimilation_decision_id(
    *,
    candidate_id: str,
    disposition: str,
    knowledge_ids: Sequence[str],
    predecessor_ids: Sequence[str] = (),
    reason: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "harness-mem:assimilation-decision:"
            f"{candidate_id}:{disposition}:{','.join(knowledge_ids)}:"
            f"{','.join(predecessor_ids)}:{reason}",
        )
    )


async def _current_entries_match(
    store: Any,
    *,
    project_name: str,
    expected_entries: Sequence[KnowledgeEntry],
) -> bool:
    if not expected_entries:
        return False
    for expected in expected_entries:
        current = await store.get_entry(expected.id, project_name=project_name)
        if current is None or (
            current.project_name != expected.project_name
            or current.module_path != expected.module_path
            or current.title != expected.title
            or current.statement != expected.statement
            or current.source_report != expected.source_report
        ):
            return False
    return True


def _optional_project_root(value: str | Path | None) -> Path | None:
    """Preserve missing context without resolving it to the process directory."""
    if value is None or not str(value).strip():
        return None
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("knowledge source context requires an absolute project root")
    return root.resolve()


async def resolve_candidate_source_context(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    evidence_items: Sequence[KnowledgeEvidence],
    project_root: str | Path | None,
) -> tuple[Path | None, list[ProjectKnowledgeSourceRef], Any]:
    if len(evidence_items) != 1:
        raise ValueError("knowledge candidate requires one evidence envelope")
    evidence = evidence_items[0]
    job = (
        backend.transcript_store.get_distill_job(evidence.distill_job_id)
        if evidence.distill_job_id
        else None
    )
    revision = (
        backend.transcript_store.get_revision(job.source_id, job.source_revision)
        if job is not None
        else None
    )
    root_value = project_root or (job.project_root if job is not None else None)
    has_repository_refs = any(
        ref.kind == "repository" for ref in evidence.verification_refs
    )
    if (
        not root_value
        and has_repository_refs
        and job is None
        and (backend.data_dir / "profiles").is_dir()
    ):
        # Preserve attribution from existing repository profiles. Missing
        # profiles must not be created just to resolve optional context.
        profile = await LocalProjectProfileStore(backend.data_dir).get(
            candidate.project_name
        )
        root_value = profile.project_root if profile is not None else None
    root = _optional_project_root(root_value)
    if has_repository_refs and (root is None or not root.is_dir()):
        raise ValueError("repository knowledge requires a real project root")
    source_refs: list[ProjectKnowledgeSourceRef] = []
    for ref in evidence.verification_refs:
        if ref.kind == "repository" and ref.locator:
            assert root is not None
            path = (root / ref.locator).resolve()
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=ref.locator,
                    target=path.as_uri(),
                    kind="repository",
                    digest=ref.content_sha256,
                )
            )
            continue
        if ref.kind == "user_statement" and ref.exchange_index is not None:
            if job is None or revision is None:
                raise ValueError(
                    "user-statement knowledge requires its retained transcript revision"
                )
            source_target = Path(backend.transcript_store.db_path).resolve().as_uri()
            source_fragment = urlencode(
                {
                    "source_id": job.source_id,
                    "source_revision": job.source_revision,
                    "exchange": ref.exchange_index,
                }
            )
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=f"原始会话 Exchange {ref.exchange_index}",
                    target=f"{source_target}#{source_fragment}",
                    kind="user_statement",
                    digest=ref.content_sha256,
                )
            )
            continue
        if ref.kind in {"transcript", "source_report"} and (
            ref.chunk_index is not None or ref.exchange_index is not None
        ):
            if job is None or revision is None:
                raise ValueError(
                    "transcript knowledge requires its retained transcript revision"
                )
            source_target = Path(backend.transcript_store.db_path).resolve().as_uri()
            location_name = "chunk" if ref.chunk_index is not None else "exchange"
            location_value = (
                ref.chunk_index if ref.chunk_index is not None else ref.exchange_index
            )
            source_fragment = urlencode(
                {
                    "source_id": job.source_id,
                    "source_revision": job.source_revision,
                    location_name: location_value,
                }
            )
            if ref.kind == "source_report":
                source_fragment += "&" + urlencode({"role": ref.role})
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=f"原始会话 {location_name.title()} {location_value}",
                    target=f"{source_target}#{source_fragment}",
                    kind=ref.kind,
                    digest=ref.content_sha256,
                )
            )
    if not source_refs:
        raise ValueError("verified knowledge has no readable source reference")
    return root, source_refs, evidence.verified_at


async def resolve_separated_review(
    backend: LocalMemoryBackend,
    *,
    candidate_id: str,
    disposition: AssimilationDisposition,
    reason: str,
    knowledge_items: Sequence[Mapping[str, Any]] = (),
    target_knowledge_ids: Sequence[str] = (),
    target_knowledge: Sequence[Mapping[str, Any]] = (),
    project_root: str | Path | None = None,
    expected_project_name: str | None = None,
) -> dict[str, Any]:
    """Apply an explicit Review decision through the same separated ledger.

    Review may reject or defer any candidate.  It may write current knowledge
    only after the candidate already has verified evidence; this keeps a Dream
    discovery from bypassing the verification module.
    """

    store = backend.structured_store.knowledge_store
    candidate = await store.get_candidate(candidate_id)
    if candidate is None:
        raise ValueError("knowledge review candidate is missing")
    if expected_project_name and candidate.project_name != expected_project_name:
        raise ValueError("knowledge review candidate belongs to another project")
    if candidate.status in {"assimilated", "rejected"}:
        raise ValueError("knowledge review candidate already has a terminal decision")
    if candidate.status not in {"pending", "deferred", "conflict"}:
        raise ValueError("knowledge review candidate has an unsupported status")
    evidence_items = await store.list_evidence(candidate.id)

    items = [dict(item) for item in knowledge_items]
    writes_truth = disposition in {"add", "refine", "replace"}
    needs_verified_evidence = writes_truth or disposition == "confirm"
    resolved_root: Path | None = None
    source_refs: list[ProjectKnowledgeSourceRef] = []
    verified_at: Any = None
    if needs_verified_evidence:
        if len(evidence_items) != 1 or evidence_items[0].verification_outcome != "verified":
            raise ValueError(
                "knowledge review requires verified evidence before confirmation or truth write"
            )
        resolved_root, source_refs, _previous_verified_at = (
            await resolve_candidate_source_context(
                backend,
                candidate=candidate,
                evidence_items=evidence_items,
                project_root=project_root,
            )
        )
        evidence = evidence_items[0]
        subject = SimpleNamespace(
            id=candidate.id,
            project_name=candidate.project_name,
            distill_job_id=evidence.distill_job_id,
            evidence_basis=evidence.evidence_basis,
            verification_outcome=evidence.verification_outcome,
            verification_refs=list(evidence.verification_refs),
            verification_reason_codes=list(evidence.verification_reason_codes),
            verified_at=evidence.verified_at,
            statement=candidate.statement,
            source_report=candidate.source_report,
        )
        validation = await validate_candidate_evidence(
            backend,
            subject,
            project_root=resolved_root,
        )
        if validation.verification_outcome != "verified":
            reasons = ", ".join(validation.reason_codes) or "source unavailable"
            raise ValueError(
                "knowledge review requires current verified evidence: " + reasons
            )
        verified_at = validation.verified_at
    if writes_truth and not items:
        raise ValueError(
            "knowledge review truth write requires canonical knowledge items"
        )
    target_knowledge_ids = await resolve_knowledge_targets(
        store, project_name=candidate.project_name,
        target_ids=target_knowledge_ids, target_knowledge=target_knowledge,
    )
    if disposition in {"refine", "replace"} and not target_knowledge_ids:
        raise ValueError(f"{disposition} requires at least one current knowledge target")
    if disposition == "confirm" and len(target_knowledge_ids) != 1:
        raise ValueError("confirm requires exactly one current knowledge target")

    # Resolve every existing-truth dependency before creating a replacement.
    # Otherwise an invalid target would leave an orphan current entry behind
    # even though no assimilation decision can validly own it.
    targets: list[KnowledgeEntry] = []
    if disposition in {"refine", "replace", "confirm"}:
        for target_id in target_knowledge_ids:
            target = await store.get_entry(
                str(target_id),
                project_name=candidate.project_name,
                project_root=resolved_root,
            )
            if target is None or target.project_name != candidate.project_name:
                raise ValueError("review target is not current project knowledge")
            targets.append(target)
        if disposition == "confirm":
            target_validation = await validate_knowledge_sources(
                backend,
                project_name=candidate.project_name,
                sources=await store.list_sources(targets[0].id),
                project_root=resolved_root,
            )
            if target_validation.verification_outcome != "verified":
                reasons = ", ".join(target_validation.reason_codes)
                raise ValueError(
                    "review target source is no longer current: " + reasons
                )

    if disposition in {"refine", "replace", "confirm"} and not targets:
        raise AssertionError("review target was not preflighted")
    point = {
        "disposition": disposition,
        "matched_truth_ids": list(target_knowledge_ids),
        "knowledge_items": items,
        "reason": reason,
        "verified_at": verified_at,
    }
    truth_ids = await record_assimilation_result(
        backend,
        candidate=candidate,
        point=point,
        project_root=resolved_root,
        source_refs=source_refs,
    )
    return {
        "candidate_id": candidate.id,
        "disposition": disposition,
        "canonical_truth_ids": truth_ids,
        "changed": bool(writes_truth),
    }


async def delete_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    target_knowledge_ids: Sequence[str] = (),
    target_knowledge: Sequence[Mapping[str, Any]] = (),
    expected_entry: KnowledgeEntry | None = None,
    retained_entries: Sequence[KnowledgeEntry] = (),
) -> dict[str, Any]:
    """Delete exactly one current project-knowledge entry."""

    normalized_project = str(project_name).strip()
    if not normalized_project:
        raise ValueError("knowledge delete requires project_name")
    store = backend.structured_store.knowledge_store
    try:
        targets = await resolve_knowledge_targets(
            store, project_name=normalized_project,
            target_ids=target_knowledge_ids, target_knowledge=target_knowledge,
        )
    except KnowledgeTargetError as exc:
        if expected_entry is not None:
            raise CanonicalTransactionPreconditionError("verified delete target is no longer current") from exc
        raise
    if len(targets) != 1 or not targets[0]:
        raise ValueError("knowledge delete requires exactly one target knowledge id")

    entry_id = targets[0]
    current = await store.get_entry(
        entry_id,
        project_name=normalized_project,
    )
    if current is None:
        if expected_entry is not None:
            raise CanonicalTransactionPreconditionError("verified delete target disappeared")
        raise ValueError("knowledge delete target is not current project knowledge")
    await store.delete_current_entry(
        project_name=normalized_project,
        entry_id=entry_id,
        expected_entry=expected_entry,
        retained_entries=retained_entries,
    )
    await _verify_normal_search_after_truth_write(
        backend,
        project_name=normalized_project,
        project_root=None,
        added_entries=[],
        predecessor_entries=[current],
    )
    if await store.list_sources(entry_id):
        raise RuntimeError("deleted knowledge sources remain in current storage")
    return {
        "deleted_knowledge_ids": [entry_id],
    }


def _candidate_knowledge_items(
    candidate: KnowledgeCandidate, point: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Bind a report write to the verified account, not a provider rewrite."""
    items = _knowledge_items(point)
    report = candidate.source_report
    if report is None:
        if any(item["claim_kind"] == "source_report" for item in items):
            raise ValueError("source-report knowledge requires verified source attribution")
        return items
    if report.text != candidate.statement:
        raise ValueError("source-report authority does not match its verified candidate")
    if len(items) != 1:
        raise ValueError("source-report writes require exactly one verified account item")
    item = dict(items[0])
    item["statement"] = report.render_statement()
    item["title"] = report.render_title()
    item["claim_kind"] = "source_report"
    return [item]


def _knowledge_items(point: Mapping[str, Any]) -> list[dict[str, Any]]:
    supplied = list(point.get("knowledge_items") or [])
    if supplied:
        normalized: list[dict[str, Any]] = []
        for item in supplied:
            title = str(item.get("title") or "").strip()
            statement = str(item.get("statement") or "").strip()
            topic_path = [str(part).strip() for part in item.get("topic_path") or []]
            claim_kind = str(item.get("claim_kind") or "")
            if not title or not statement or not topic_path:
                raise ValueError(
                    "review knowledge item must have title, statement, and topic path"
                )
            if claim_kind not in {
                "design_requirement",
                "implementation_fact",
                "durable_preference",
                "procedure",
                "source_report",
            }:
                raise ValueError("review knowledge item has an invalid claim kind")
            normalized.append(
                {
                    "title": title,
                    "statement": statement,
                    "topic_path": topic_path,
                    "claim_kind": claim_kind,
                }
            )
        return normalized

    title = str(point.get("canonical_title") or "").strip()
    statement = str(point.get("canonical_statement") or "").strip()
    topic_path = [str(part).strip() for part in point.get("topic_path") or []]
    if not title or not statement or not topic_path:
        raise ValueError("a knowledge-writing disposition requires an atomic item")
    return [
        {
            "title": title,
            "statement": statement,
            "topic_path": topic_path,
            "claim_kind": str(point.get("claim_kind") or "procedure"),
        }
    ]


def _separated_status(disposition: AssimilationDisposition) -> KnowledgeCandidateStatus:
    if disposition == "defer":
        return "deferred"
    if disposition == "conflict":
        return "conflict"
    if disposition == "reject":
        return "rejected"
    return "assimilated"


def _disposition(point: Mapping[str, Any]) -> AssimilationDisposition:
    value = str(point.get("disposition") or "reject")
    allowed = {
        "add",
        "refine",
        "confirm",
        "replace",
        "no_write",
        "handoff",
        "defer",
        "conflict",
        "reject",
    }
    if value not in allowed:
        raise ValueError(f"unknown assimilation disposition: {value}")
    return cast(AssimilationDisposition, value)


__all__ = [
    "delete_current_knowledge",
    "record_assimilation_result",
    "resolve_candidate_source_context",
    "resolve_separated_review",
]
