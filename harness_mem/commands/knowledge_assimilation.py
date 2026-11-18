"""Write verified candidate decisions to the current knowledge repository."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence, cast
from urllib.parse import parse_qs, urlencode, urlparse
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
    content_admission_allows_durable_write,
    resolve_repository_evidence_path,
    validate_candidate_evidence,
    validate_knowledge_sources,
)
from harness_mem.autonomous.models import UpdateMeaningJudgment
from harness_mem.core.schemas.source_report import (
    ReportOmission,
    ReportOutputProposal,
    ReportTopicJudgment,
    SourceReport,
    bind_report_split,
    report_revision_allowed,
    report_preservation_mode,
    report_preservation_digest,
    readable_knowledge_statement,
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
            reference[key].casefold() in {
                " ".join(getattr(entry, key).split()).casefold(),
                " ".join(readable_knowledge_statement(entry.statement, entry.source_report).split()).casefold()
                if key == "statement" else " ".join(entry.title.split()).casefold(),
            }
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
    expected_context_entries: Sequence[KnowledgeEntry] = (),
) -> list[str]:
    """Write clean current entries for one verified point."""

    store = backend.structured_store.knowledge_store
    candidate_before = candidate.model_copy(deep=True)
    disposition = _disposition(point)
    if candidate.status == "assimilated" and disposition in {"add", "refine", "replace"}:
        recovered = await recover_committed_assimilation(
            backend, project_name=candidate.project_name, project_root=project_root,
            points=[{**dict(point), "candidate_id": candidate.id}],
            supplied_candidates={candidate.id: candidate},
        )
        if recovered:
            return recovered
        raise ValueError("terminal candidate requires its exact committed payload")
    if disposition in {"add", "refine", "replace", "confirm"} and (
        not project_root or not source_refs
    ):
        evidence_items = await store.list_evidence(candidate.id)
        # A caller-supplied project root with no evidence is a reopen, not an
        # evidence lookup. Empty refs fail later in _require_fresh_source.
        if evidence_items or not project_root:
            resolved_root, resolved_refs, resolved_verified_at = (
                await resolve_candidate_source_context(
                    backend,
                    candidate=candidate,
                    evidence_items=evidence_items,
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
    judgment = _parse_topic_judgment(point.get("report_topic_judgment"))
    judgments = _parse_topic_judgments(point.get("report_topic_judgments"))
    written_report = candidate.source_report
    proposed_title = None
    report_split = point.get("report_split") if isinstance(point.get("report_split"), Mapping) else None
    if written_report is not None and disposition in {"add", "refine", "replace"} and report_split is None:
        preview_items = _knowledge_items(point)
        if len(preview_items) == 1:
            proposed_title = preview_items[0]["title"]
    loaded_targets: list[KnowledgeEntry | None] = []
    for target_id in matched_truth_ids:
        loaded_targets.append(await store.get_entry(target_id, project_name=candidate.project_name))
    for target in loaded_targets:
        if target is not None and disposition in {"refine", "replace", "confirm"}:
            if (written_report is None) != (target.source_report is None):
                raise ValueError("source-report and fact authority boundary cannot be crossed")
    if written_report is not None:
        written_report = _bind_report_topic_relations(written_report,
            [target.source_report for target in loaded_targets if target is not None and target.source_report is not None],
            disposition=disposition, proposed_title=proposed_title, judgment=judgment, judgments=judgments)
        if disposition == "confirm" and any(target is not None and target.statement != written_report.render_statement()
                                             for target in loaded_targets):
            raise ValueError("source-report confirmation requires the identical attributed account")
    elif judgments:
        raise ValueError("report topic judgments require verified source attribution")
    predecessor_truth_ids: list[str] = []
    predecessor_entries: list[KnowledgeEntry] = []
    new_entries: list[KnowledgeEntry] = []
    decision_id: str | None = None
    if disposition in {"add", "refine", "replace"}:
        bound_items = _candidate_knowledge_items(
            candidate, point, judgment=judgment,
            predecessor=next(
                (target.source_report for target in loaded_targets
                 if target is not None and target.source_report is not None),
                None,
            ),
        )
        for _index, item in enumerate(bound_items, 1):
            item_report = item.get("source_report") if report_split is not None else None
            if item_report is not None and not isinstance(item_report, SourceReport):
                item_report = SourceReport.model_validate(item_report)
            entry = KnowledgeEntry(
                id=_knowledge_item_id(candidate.project_name, item),
                project_name=candidate.project_name,
                title=item["title"],
                statement=item["statement"],
                source_report=(
                    item_report if item_report is not None
                    else written_report if candidate.source_report is not None else None
                ),
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
            report_topic_judgments=judgments,
        )
        if not await store.current_change_committed(decision_id) and candidate.source_report is not None:
            legacy_ids = [_legacy_knowledge_item_id(candidate.project_name, item) for item in bound_items]
            legacy_decision = assimilation_decision_id(
                candidate_id=candidate.id, disposition=disposition, knowledge_ids=legacy_ids,
                predecessor_ids=matched_truth_ids, reason=str(point.get("reason", "")),
                report_topic_judgments=judgments,
            )
            if await store.current_change_committed(legacy_decision):
                # Only a recorded exact old commit can select old identities.
                # The current-row/authority comparison below still has to pass.
                knowledge_ids = legacy_ids
                decision_id = legacy_decision
                new_entries = [entry.model_copy(update={"id": identity})
                               for entry, identity in zip(new_entries, legacy_ids)]
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
        _require_retained_meaning(
            bound_items,
            point,
            predecessors=predecessor_entries,
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

    decision = AssimilationDecision(
        id=decision_id
        or assimilation_decision_id(
            candidate_id=candidate.id,
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            predecessor_ids=matched_truth_ids,
            reason=str(point.get("reason", "")),
            report_topic_judgments=judgments,
        ),
        project_name=candidate.project_name,
        candidate_id=candidate.id,
        disposition=disposition,
        canonical_truth_ids=knowledge_ids,
        predecessor_truth_ids=predecessor_truth_ids,
        predecessor_entries=predecessor_entries,
        report_topic_judgment=judgment,
        report_topic_judgments=judgments,
        report_split=dict(report_split) if report_split is not None else None,
        reason=str(point.get("reason") or disposition),
    )
    if disposition in {"add", "refine", "replace", "confirm"}:
        await _reject_held_source_batch(backend, candidate)
        await _require_fresh_source(
            backend,
            candidate=candidate,
            project_root=project_root,
            source_refs=source_refs,
        )
    if disposition in {"add", "refine", "replace", "confirm"}:
        _require_new_write_final_judgment(
            candidate, point, items=bound_items if disposition != "confirm" else [],
            predecessors=predecessor_entries if disposition != "confirm" else loaded_targets,
            evidence_codes=_evidence_codes(await store.list_evidence(candidate.id)),
        )
    resulting_status = _separated_status(disposition)
    if new_entries:
        await store.apply_current_change(
            project_root=_optional_project_root(project_root),
            candidate_before=candidate_before,
            candidate_after=candidate.model_copy(update={"status": resulting_status}),
            decision=decision,
            added_entries=new_entries,
            predecessor_entries=predecessor_entries,
            source_refs_by_entry={
                entry.id: (
                    _refs_for_report_output(source_refs, entry.source_report)
                    if report_split is not None and entry.source_report is not None
                    else list(source_refs)
                )
                for entry in new_entries
            },
            **({"expected_context_entries": expected_context_entries}
               if expected_context_entries else {}),
        )
        candidate.status = resulting_status
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
        candidate.status = resulting_status
        await store.save_candidate(candidate)
        await store.save_decision(decision, project_root=project_root)
    return knowledge_ids


def _knowledge_item_id(project_name: str, item: Mapping[str, Any]) -> str:
    identity = "\0".join([project_name, *item["topic_path"], item["title"], item["statement"]])
    report = item.get("source_report")
    if report is not None:
        report = report if isinstance(report, SourceReport) else SourceReport.model_validate(report)
        identity += "\0" + "\0".join([
            report.session_id, report.source_id, report.speaker, report.period,
        ])
    return str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge:{identity}"))


def _legacy_knowledge_item_id(project_name: str, item: Mapping[str, Any]) -> str:
    identity = "\0".join([project_name, *item["topic_path"], item["title"], item["statement"]])
    return str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge:{identity}"))


async def is_committed_knowledge_point(
    backend: LocalMemoryBackend, *, candidate: KnowledgeCandidate, point: Mapping[str, Any],
) -> bool:
    """Prove an exact write replay without trusting caller-supplied outputs."""
    disposition = _disposition(point)
    if candidate.status != "assimilated" or disposition not in {"add", "refine", "replace"}:
        return False
    items = _candidate_knowledge_items(
        candidate, point, judgment=_parse_topic_judgment(point.get("report_topic_judgment")),
        predecessor=candidate.source_report,
    )
    for producer in (_knowledge_item_id, _legacy_knowledge_item_id):
        decision_id = assimilation_decision_id(
            candidate_id=candidate.id, disposition=disposition,
            knowledge_ids=[producer(candidate.project_name, item) for item in items],
            predecessor_ids=[str(value) for value in point.get("matched_truth_ids") or []],
            reason=str(point.get("reason", "")),
            report_topic_judgments=_parse_topic_judgments(point.get("report_topic_judgments")),
        )
        if await backend.structured_store.knowledge_store.current_change_committed(decision_id):
            return True
    return False


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
    report_topic_judgments: Sequence[Any] = (),
) -> str:
    judgments = _parse_topic_judgments(report_topic_judgments)
    topic_binding = (":report-topics:" + report_preservation_digest(
        [item.model_dump(mode="json") for item in judgments])) if judgments else ""
    return str(
        uuid5(
            NAMESPACE_URL,
            "harness-mem:assimilation-decision:"
            f"{candidate_id}:{disposition}:{','.join(knowledge_ids)}:"
            f"{','.join(predecessor_ids)}:{reason}{topic_binding}",
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
    source_refs: list[ProjectKnowledgeSourceRef] = []
    for ref in evidence.verification_refs:
        if ref.kind == "repository" and ref.locator:
            path, reason = resolve_repository_evidence_path(ref.locator, root)
            if path is None:
                raise ValueError(f"repository evidence unavailable: {reason}")
            source_refs.append(
                ProjectKnowledgeSourceRef(
                    label=ref.locator,
                    target=path.as_uri(),
                    kind="repository",
                    digest=ref.content_sha256,
                    bindings=ref.bindings,
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
                    bindings=ref.bindings,
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
                    bindings=ref.bindings,
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
    final_scope_judgment: Any = None,
    update_meaning_judgment: Any = None,
    report_topic_judgment: Any = None,
    report_topic_judgments: Any = None,
    report_split: Mapping[str, Any] | None = None,
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
    if candidate.status == "assimilated" and disposition in {"add", "refine", "replace"}:
        replay_targets = list(target_knowledge_ids)
        if target_knowledge:
            if list(target_knowledge) != candidate.assimilation_targets:
                raise ValueError("terminal candidate requires its exact committed target selection")
            replay_targets = list(candidate.assimilation_target_ids)
        replay = {"candidate_id": candidate.id, "disposition": disposition, "reason": reason,
            "knowledge_items": [dict(item) for item in knowledge_items],
            "matched_truth_ids": replay_targets, "report_topic_judgment": report_topic_judgment,
            "report_topic_judgments": report_topic_judgments,
            "report_split": report_split}
        recovered = await recover_committed_assimilation(
            backend, project_name=candidate.project_name, project_root=project_root, points=[replay])
        if recovered:
            return {"candidate_id": candidate.id, "disposition": disposition,
                    "canonical_truth_ids": recovered, "changed": False, "reused_result": True}
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
        if not content_admission_allows_durable_write(evidence_items[0]):
            raise ValueError(
                "verified source support without durable future use is not current knowledge"
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
    # Callers supply the current Agent's judgment. This function does not invent one.
    if final_scope_judgment is not None:
        from harness_mem.autonomous.models import CandidateVerificationDecision

        raw = final_scope_judgment
        if isinstance(raw, Mapping) and "points" not in raw:
            raw = raw.get(candidate.id)
        parsed = (raw if isinstance(raw, CandidateVerificationDecision)
                  else CandidateVerificationDecision.model_validate(raw))
        final_scope_judgment = parsed
        if disposition in {"refine", "replace"} and parsed.points:
            meaning = parsed.points[0].update_meaning_judgment
            if meaning is not None:
                update_meaning_judgment = meaning.model_dump(mode="json")
                point["retained_conditions"] = list(meaning.predecessor_conditions)
                point["undecided_state"] = meaning.undecided_state
        point["final_scope_judgment"] = final_scope_judgment
    if update_meaning_judgment is not None:
        point["update_meaning_judgment"] = update_meaning_judgment
    if report_topic_judgment is not None:
        point["report_topic_judgment"] = report_topic_judgment
    if report_topic_judgments is not None:
        point["report_topic_judgments"] = report_topic_judgments
    if report_split is not None:
        point["report_split"] = dict(report_split)
    candidate.assimilation_target_ids = list(target_knowledge_ids)
    candidate.assimilation_targets = [dict(item) for item in target_knowledge]
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


def _account_with_rendered_title(report: SourceReport, rendered: str) -> SourceReport:
    if rendered == report.legacy_title():
        return report.model_copy(update={"topic_title": None})
    return report.model_copy(update={"topic_title": rendered})


def _parse_topic_judgment(value: Any) -> ReportTopicJudgment | None:
    if value is None or value == {}:
        return None
    if isinstance(value, ReportTopicJudgment):
        return value
    return ReportTopicJudgment.model_validate(value)


def _parse_topic_judgments(value: Any) -> list[ReportTopicJudgment]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("report topic judgments must be an ordered list")
    return [item if isinstance(item, ReportTopicJudgment) else ReportTopicJudgment.model_validate(item)
            for item in value]


def _bind_report_topic_relations(
    report: SourceReport, predecessors: Sequence[SourceReport], *, disposition: str,
    proposed_title: str | None = None, judgment: ReportTopicJudgment | None = None,
    judgments: Sequence[ReportTopicJudgment] = (),
) -> SourceReport:
    """Require one exact title relationship per predecessor in target order.

    Generic legacy titles can repeat, so title lookup alone is insufficient.
    The ordered list gives every separately bound predecessor its own vote;
    preservation of its body is still checked by the independent inventory.
    """
    if judgments and judgment is not None:
        raise ValueError("report topic judgment formats cannot be combined")
    if judgments and len(judgments) != len(predecessors):
        raise ValueError("report topic judgments must cover every predecessor once")
    if len(predecessors) > 1 and disposition in {"refine", "replace"} and len(judgments) != len(predecessors):
        raise ValueError("report topic judgments must cover every predecessor once")
    if any(not report.same_account_source(predecessor) for predecessor in predecessors):
        raise ValueError("source-report updates cannot cross source, speaker, or period")
    if proposed_title:
        report = report.with_topic_revision(proposed_title,
            judgments[0] if judgments else judgment,
            predecessor=predecessors[0] if predecessors else None)
    for index, predecessor in enumerate(predecessors):
        selected = judgments[index] if judgments else judgment
        if judgments:
            # A negative, unclear, swapped or foreign title vote cannot hide
            # behind exact body equality or another predecessor's approval.
            if not judgments[index].authorizes(predecessor, report):
                raise ValueError("source-report topic judgment does not bind its predecessor and successor")
        elif not report_revision_allowed(report, predecessor, selected, disposition=disposition):
            raise ValueError("source-report updates cannot cross source, speaker, period, or topic")
    return report


def _bound_source_report(
    report: SourceReport,
    proposed_title: str,
    judgment: ReportTopicJudgment | None,
    predecessor: SourceReport | None,
) -> SourceReport:
    if predecessor is None and judgment is not None:
        predecessor = _account_with_rendered_title(report, judgment.predecessor_title)
    return report.with_topic_revision(proposed_title, judgment, predecessor=predecessor)


def _refs_for_report_output(
    refs: Sequence[ProjectKnowledgeSourceRef],
    report: SourceReport,
) -> list[ProjectKnowledgeSourceRef]:
    """Keep the source refs that cite this output's own exchanges."""

    selected: list[ProjectKnowledgeSourceRef] = []
    found: set[int] = set()
    for ref in refs:
        query = parse_qs(urlparse(ref.target).fragment)
        if (
            ref.kind != "source_report"
            or query.get("source_id") != [report.source_id]
            or query.get("source_revision") != [report.source_revision]
            or query.get("role") != [report.speaker]
            or len(query.get("exchange", [])) != 1
        ):
            continue
        try:
            exchange = int(query["exchange"][0])
        except ValueError as exc:
            raise ValueError("source-report exchange is invalid") from exc
        if exchange not in report.exchange_indexes:
            continue
        selected.append(ref)
        found.add(exchange)
    if found != set(report.exchange_indexes):
        raise ValueError("source-report exchanges do not match retained source scope")
    return selected


def _candidate_knowledge_items(
    candidate: KnowledgeCandidate,
    point: Mapping[str, Any],
    *,
    judgment: ReportTopicJudgment | None = None,
    predecessor: SourceReport | None = None,
) -> list[dict[str, Any]]:
    """Bind a report write to the verified account, not a provider rewrite."""
    items = _knowledge_items(point)
    report = candidate.source_report
    report_split = point.get("report_split") if isinstance(point.get("report_split"), Mapping) else None
    if report_split is not None:
        if report is None or report.text != candidate.statement:
            raise ValueError("source-report authority does not match its verified candidate")
        if not items or any(item["claim_kind"] != "source_report" for item in items):
            raise ValueError("source-report refinement requires retained attributed account items")
        outputs = [ReportOutputProposal.model_validate(item) for item in report_split.get("outputs") or []]
        omissions = [ReportOmission.model_validate(item) for item in report_split.get("omissions") or []]
        bound = bind_report_split(
            report,
            original_support=str(report_split.get("original_support") or ""),
            outputs=outputs,
            omissions=omissions,
            mode=str(report_split.get("mode", "literal_projection")),
        )
        if len(bound) != len(items):
            raise ValueError("source-report split items do not match the bound outputs")
        rewritten: list[dict[str, Any]] = []
        for item, written in zip(items, bound):
            if item["title"] != written.render_title() or item["statement"] != written.render_statement():
                raise ValueError("source-report split item does not match its typed attribution")
            copied = dict(item)
            copied["source_report"] = written
            rewritten.append(copied)
        return rewritten
    if report is None:
        if any(item["claim_kind"] == "source_report" for item in items):
            raise ValueError("source-report knowledge requires verified source attribution")
        return items
    if report.text != candidate.statement:
        raise ValueError("source-report authority does not match its verified candidate")
    if len(items) != 1:
        raise ValueError("source-report writes require exactly one verified account item")
    if judgment is None:
        judgment = _parse_topic_judgment(point.get("report_topic_judgment"))
    if judgment is None and predecessor is not None:
        judgment = next((item for item in _parse_topic_judgments(point.get("report_topic_judgments"))
                         if item.predecessor_title == predecessor.render_title()
                         and item.successor_title == items[0]["title"]), None)
    bound = _bound_source_report(report, items[0]["title"], judgment, predecessor)
    item = dict(items[0])
    item["statement"] = bound.render_statement()
    item["title"] = bound.render_title()
    item["claim_kind"] = "source_report"
    item["source_report"] = bound
    return [item]


def _parse_meaning_judgment(value: Any) -> UpdateMeaningJudgment | None:
    if value is None or value == {}:
        return None
    if isinstance(value, UpdateMeaningJudgment):
        return value
    return UpdateMeaningJudgment.model_validate(value)


def _require_retained_meaning(
    items: Sequence[Mapping[str, Any]],
    point: Mapping[str, Any],
    *,
    predecessors: Sequence[KnowledgeEntry] = (),
) -> None:
    """Require the shared whole-update judgment before a new write.

    ``update_meaning_block`` is the only policy. A refine or replace with no
    judgment fails even when the caller left the condition inventory empty.
    Predecessor statements and versions come from the rows about to be
    replaced, not from a caller-selected hash.
    """

    from harness_mem.commands.separated_assimilation import target_version, update_meaning_block

    targets: list[dict[str, Any]] = []
    for entry in predecessors:
        report = entry.source_report.model_dump(mode="json") if entry.source_report is not None else None
        snapshot = {
            "id": entry.id,
            "title": entry.title,
            "statement": entry.statement,
            "topic_path": list(entry.module_path),
            "source_report": report,
        }
        snapshot["version"] = target_version(snapshot)
        targets.append(snapshot)
    if update_meaning_block({
        "disposition": point.get("disposition"),
        "candidate_id": point.get("candidate_id"),
        "knowledge_items": [dict(item) for item in items],
        "targets": targets,
        "retained_conditions": list(point.get("retained_conditions") or []),
        "undecided_state": point.get("undecided_state"),
        "update_meaning_judgment": point.get("update_meaning_judgment"),
    }):
        raise ValueError("replacement dropped a still-applicable condition or undecided state")


async def _reject_held_source_batch(
    backend: LocalMemoryBackend, candidate: KnowledgeCandidate,
) -> None:
    """Re-read the manual batch owner before a current-knowledge write.

    The batch manifest and the canonical database are not one transaction.
    A paused or integrity-stopped job that owns this candidate's evidence
    cannot commit. An unrelated job and an explicit standalone deletion stay
    on their own authorization. Continue clears a user pause; this check then
    allows the write. A replay of an already committed change returns earlier
    and does not call this function.
    """

    from harness_mem.commands.manual_distill import manual_job_guard, paused_batch_error

    evidence_items = await backend.structured_store.knowledge_store.list_evidence(candidate.id)
    seen: set[str] = set()
    for evidence in evidence_items:
        job_id = evidence.distill_job_id
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        job = backend.transcript_store.get_distill_job(job_id)
        if job is None:
            continue
        held = paused_batch_error(backend, job)
        if held is None and manual_job_guard(backend, job) == "manual_batch_stopped":
            held = "manual_batch_stopped"
        if held:
            raise ValueError(
                "paused or integrity-stopped source batch cannot write current knowledge: "
                + held
            )


def _evidence_codes(evidence_items: Sequence[Any]) -> set[str]:
    if len(evidence_items) != 1:
        return set()
    return set(evidence_items[0].verification_reason_codes or [])


def _require_new_write_final_judgment(
    candidate: KnowledgeCandidate,
    point: Mapping[str, Any],
    *,
    items: Sequence[Mapping[str, Any]],
    predecessors: Sequence[KnowledgeEntry],
    evidence_codes: set[str],
) -> None:
    """A new add, refine, or replace needs a real final semantic judgment.

    A stored proof is reusable only for these exact normalized bytes and
    predecessor versions. Missing admission markers are not a second way in.
    """

    from harness_mem.autonomous.models import CandidateVerificationDecision
    from harness_mem.commands.separated_assimilation import (
        prove_supplied_final_scope,
        final_scope_proof,
        _meaning_fields,
        target_version,
    )
    from harness_mem.core.schemas.source_report import source_report_snapshot

    targets: list[dict[str, Any]] = []
    for entry in predecessors:
        snapshot = {
            "id": entry.id,
            "title": entry.title,
            "statement": entry.statement,
            "topic_path": list(entry.module_path),
            "source_report": source_report_snapshot(entry.source_report),
        }
        snapshot["version"] = target_version(snapshot)
        targets.append(snapshot)
    knowledge_items: list[dict[str, Any]] = []
    for item in items:
        copied = {
            "title": item["title"],
            "statement": item["statement"],
            "topic_path": list(item["topic_path"]),
            "claim_kind": item["claim_kind"],
        }
        report = item.get("source_report")
        if isinstance(report, SourceReport):
            copied["source_report"] = source_report_snapshot(report)
        elif isinstance(report, Mapping):
            copied["source_report"] = dict(report)
        knowledge_items.append(copied)
    payload: dict[str, Any] = {
        "disposition": point.get("disposition"),
        "candidate_id": candidate.id,
        "knowledge_items": knowledge_items,
        "targets": targets,
    }
    payload.update(_meaning_fields(
        judgment=_parse_topic_judgment(point.get("report_topic_judgment")),
        judgments=_parse_topic_judgments(point.get("report_topic_judgments")),
        retained_conditions=list(point.get("retained_conditions") or []),
        undecided_state=point.get("undecided_state"),
        update_meaning=point.get("update_meaning_judgment"),
    ))
    if point.get("report_preservation_inventory") is not None:
        payload["report_preservation_inventory"] = point["report_preservation_inventory"]
    from harness_mem.core.schemas.source_report import (
        report_body_update_required, report_preservation_block, validate_report_preservation_inventory,
    )
    if str(point.get("disposition") or "") in {"refine", "replace"} and report_body_update_required(targets, knowledge_items):
        inventory = payload.get("report_preservation_inventory")
        if not isinstance(inventory, Mapping):
            raise ValueError("final_report_original_inventory_missing")
        validate_report_preservation_inventory(inventory, owner=candidate.id, targets=targets, items=knowledge_items,
            expected_mode=report_preservation_mode(point.get("report_split")))
        meaning = payload.get("update_meaning_judgment") or {}
        blocked = report_preservation_block(inventory, meaning.get("report_preservation"), knowledge_items)
        if blocked:
            raise ValueError(blocked)
    if ("autonomous_final_scope_required" in evidence_codes
            and final_scope_proof(payload) in evidence_codes):
        return
    supplied = point.get("final_scope_judgment")
    if supplied is None:
        raise ValueError("new knowledge write requires a final semantic judgment")
    judgment = (
        supplied if isinstance(supplied, CandidateVerificationDecision)
        else CandidateVerificationDecision.model_validate(supplied)
    )
    prove_supplied_final_scope(payload=payload, judgment=judgment)


async def _require_fresh_source(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    project_root: str | Path | None,
    source_refs: Sequence[ProjectKnowledgeSourceRef] = (),
) -> None:
    """Reopen the cited source before a new commit.

    Zero evidence is not a skip. Dream and other adapters that supply source
    refs must reopen those refs and, for a report, bind the raw account.
    More than one evidence row cannot authorize a new write. Committed replay
    returns before this function.
    """

    evidence_items = await backend.structured_store.knowledge_store.list_evidence(candidate.id)
    if len(evidence_items) > 1:
        raise ValueError("malformed evidence cannot authorize a new knowledge write")
    if len(evidence_items) == 0:
        await _reopen_supplied_source_refs(
            backend, candidate=candidate, source_refs=source_refs, project_root=project_root,
        )
        return
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
        backend, subject, project_root=project_root,
    )
    if validation.verification_outcome != "verified":
        reasons = ", ".join(validation.reason_codes) or "source unavailable"
        raise ValueError("source unavailable; current knowledge was not written: " + reasons)
    if not content_admission_allows_durable_write(evidence):
        raise ValueError("verified source support without durable future use is not current knowledge")


async def _reopen_supplied_source_refs(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    source_refs: Sequence[ProjectKnowledgeSourceRef],
    project_root: str | Path | None,
) -> None:
    """Reopen caller-supplied refs when the candidate has no evidence row."""

    from datetime import datetime, timezone

    from harness_mem.commands.evidence_admission import reopen_knowledge_sources
    from harness_mem.core.schemas.knowledge import KnowledgeSource

    if not source_refs:
        raise ValueError("knowledge write requires one evidence envelope or a reopenable source")
    report = candidate.source_report
    if report is not None:
        cited: set[int] = set()
        for ref in source_refs:
            query = parse_qs(urlparse(ref.target).fragment)
            if (
                ref.kind != "source_report"
                or query.get("source_id") != [report.source_id]
                or query.get("source_revision") != [report.source_revision]
                or query.get("role") != [report.speaker]
                or len(query.get("exchange", [])) != 1
            ):
                raise ValueError("supplied source ref does not bind the raw report account")
            try:
                cited.add(int(query["exchange"][0]))
            except ValueError as exc:
                raise ValueError("supplied source ref does not bind the raw report account") from exc
        if cited != set(report.exchange_indexes):
            raise ValueError("supplied source ref does not bind the raw report account")
    sources: list[KnowledgeSource] = []
    for ref in source_refs:
        if not ref.kind or not ref.target or not ref.digest:
            raise ValueError("source unavailable; current knowledge was not written: repository_ref_incomplete")
        sources.append(KnowledgeSource(
            knowledge_id=candidate.id,
            project_name=candidate.project_name,
            source_kind=ref.kind,
            locator=ref.target,
            content_sha256=str(ref.digest).lower(),
            verified_at=datetime.now(timezone.utc),
        ))
    validation, _reopened = await reopen_knowledge_sources(
        backend,
        project_name=candidate.project_name,
        sources=sources,
        project_root=project_root,
    )
    if validation.verification_outcome != "verified":
        reasons = ", ".join(validation.reason_codes) or "source unavailable"
        raise ValueError("source unavailable; current knowledge was not written: " + reasons)


async def recover_committed_assimilation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path | None,
    points: Sequence[Mapping[str, Any]],
    supplied_candidates: Mapping[str, KnowledgeCandidate] | None = None,
) -> list[str]:
    """Reuse a knowledge commit that landed before Note or receipt completion.

    This does not apply the change again. An uncommitted point is left untouched.
    The transcript ledger and the canonical knowledge database do not share a
    transaction; this only reads the knowledge result that already committed.
    """

    recovered: list[str] = []
    store = backend.structured_store.knowledge_store
    root = _optional_project_root(project_root)
    for point in points:
        disposition = str(point.get("disposition") or "")
        if disposition not in {"add", "refine", "replace"}:
            continue
        candidate_id = str(point.get("candidate_id") or "")
        candidate = ((supplied_candidates or {}).get(candidate_id)
                     or await store.get_candidate(candidate_id))
        try:
            items = (_candidate_knowledge_items(candidate, point, predecessor=candidate.source_report)
                     if candidate is not None else _knowledge_items(point))
        except ValueError:
            continue
        if not items:
            continue
        knowledge_ids = [_knowledge_item_id(project_name, item) for item in items]
        decision_id = assimilation_decision_id(
            candidate_id=str(point.get("candidate_id") or ""),
            disposition=disposition,
            knowledge_ids=knowledge_ids,
            predecessor_ids=[str(value) for value in point.get("matched_truth_ids") or []],
            reason=str(point.get("reason", "")),
            report_topic_judgments=_parse_topic_judgments(point.get("report_topic_judgments")),
        )
        if not await store.current_change_committed(decision_id):
            legacy_ids = [_legacy_knowledge_item_id(project_name, item) for item in items]
            legacy_decision = assimilation_decision_id(
                candidate_id=str(point.get("candidate_id") or ""), disposition=disposition,
                knowledge_ids=legacy_ids,
                predecessor_ids=[str(value) for value in point.get("matched_truth_ids") or []],
                reason=str(point.get("reason", "")),
                report_topic_judgments=_parse_topic_judgments(point.get("report_topic_judgments")),
            )
            if not await store.current_change_committed(legacy_decision):
                continue
            knowledge_ids = legacy_ids
            decision_id = legacy_decision
        entries: list[KnowledgeEntry] = []
        for entry_id in knowledge_ids:
            entry = await store.get_entry(entry_id, project_name=project_name)
            if entry is None:
                raise RuntimeError(
                    "committed knowledge result disappeared before note or receipt completion"
                )
            entries.append(entry)
        for item, entry in zip(items, entries):
            report = item.get("source_report")
            if isinstance(report, Mapping):
                report = SourceReport.model_validate(report)
            if (entry.title != item["title"] or entry.statement != item["statement"]
                    or entry.module_path != item["topic_path"] or entry.source_report != report):
                raise RuntimeError("committed knowledge result no longer matches its exact payload")
        for predecessor_id in point.get("matched_truth_ids") or []:
            if await store.get_entry(str(predecessor_id), project_name=project_name) is not None:
                raise RuntimeError("committed replacement left its predecessor current")
        await _verify_normal_search_after_truth_write(
            backend,
            project_name=project_name,
            project_root=root,
            added_entries=entries,
            predecessor_entries=[],
        )
        recovered.extend(knowledge_ids)
    return recovered


async def commit_shared_knowledge_change(
    backend: LocalMemoryBackend,
    *,
    candidate: KnowledgeCandidate,
    point: Mapping[str, Any],
    project_root: str | Path | None = None,
    source_refs: Sequence[ProjectKnowledgeSourceRef] = (),
    expected_predecessor_entries: Sequence[KnowledgeEntry] | None = None,
    confirmation_refresh: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Commit one add, refinement, replacement, confirmation, or retirement.

    Dream scheduling and manual review both call this instead of a private
    current-row writer. Confirmation may refresh verification metadata in the
    same store. Retirement uses the existing delete contract. There is no
    knowledge-history or undo record.
    """

    disposition = _disposition(point)
    if disposition == "reject":
        retained = list(expected_predecessor_entries or ())
        deleted = await delete_current_knowledge(
            backend,
            project_name=candidate.project_name,
            target_knowledge_ids=[str(item) for item in point.get("matched_truth_ids") or []],
            expected_entry=retained[0] if retained else None,
            retained_entries=retained[1:],
        )
        return {"truth_ids": list(deleted["deleted_knowledge_ids"]), "truth_change": "deleted"}
    if disposition == "confirm" and confirmation_refresh is not None:
        expected = confirmation_refresh.get("expected_entry")
        if not isinstance(expected, KnowledgeEntry):
            raise ValueError("confirmation requires its exact current target snapshot")
        await _reject_held_source_batch(backend, candidate)
        await _require_fresh_source(backend, candidate=candidate, project_root=project_root,
                                    source_refs=source_refs)
        _require_new_write_final_judgment(candidate, point, items=[], predecessors=[expected],
                                         evidence_codes=set())
        await backend.structured_store.knowledge_store.refresh_entry_verification(
            **dict(confirmation_refresh),
        )
        return {
            "truth_ids": [str(confirmation_refresh["entry_id"])],
            "truth_change": "verification_refreshed",
        }
    truth_ids = await record_assimilation_result(
        backend,
        candidate=candidate,
        point=point,
        project_root=project_root,
        source_refs=source_refs,
        expected_predecessor_entries=expected_predecessor_entries,
    )
    return {
        "truth_ids": truth_ids,
        "truth_change": "confirmed" if disposition == "confirm" else disposition,
    }


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
    "commit_shared_knowledge_change",
    "delete_current_knowledge",
    "record_assimilation_result",
    "recover_committed_assimilation",
    "resolve_candidate_source_context",
    "resolve_separated_review",
]
