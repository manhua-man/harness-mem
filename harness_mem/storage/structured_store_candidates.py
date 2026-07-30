"""Governance candidate persistence for LocalStructuredStore."""

# The concrete LocalStructuredStore supplies persistence primitives and sibling
# capability methods through composition. Contract tests exercise the complete host.
# mypy: disable-error-code="attr-defined"

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone

from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.core.schemas.merge_suggestion_candidate import MergeSuggestionCandidate
from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.procedural_candidate import ProceduralCandidate
from harness_mem.core.schemas.skill import Skill
from harness_mem.governance_status import (
    user_confirm_status,
)


class StructuredCandidateMixin:
    async def save_rule_candidate(self, candidate: RuleCandidate) -> str:
        blob_path = self._blob_path("rule_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.upsert,
            "rule_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "session_id": candidate.session_id,
                "pattern": candidate.pattern,
                "trigger": candidate.trigger,
                "examples": candidate.examples,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "created_at": candidate.created_at,
            },
        )
        return candidate.id

    async def get_rule_candidate(self, id: str) -> RuleCandidate | None:
        blob_path = self._blob_path("rule_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return RuleCandidate.from_dict(data)

    async def list_rule_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[RuleCandidate]:
        where_parts = ["project_name = ?"]
        params = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        where = " AND ".join(where_parts)
        rows = await asyncio.to_thread(
            self._index.list,
            "rule_candidates",
            where,
            tuple(params),
            order_by="created_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("rule_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(RuleCandidate.from_dict(data))
        return results

    async def update_rule_candidate_status(self, id: str, status: str) -> bool:
        return await self.candidate_store.update_status("rule_candidates", id, status)

    # ---- SupersedeCandidate ----

    async def save_supersede_candidate(self, candidate: SupersedeCandidate) -> str:
        blob_path = self._blob_path("supersede_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "supersede_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "target_type": candidate.target_type,
                "target_id": candidate.target_id,
                "replacement_type": candidate.replacement_type,
                "replacement_id": candidate.replacement_id,
                "reason": candidate.reason,
                "evidence": candidate.evidence,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "source": candidate.source,
                "created_at": candidate.created_at,
                "reviewed_at": candidate.reviewed_at,
                "reviewer_id": candidate.reviewer_id,
            },
        )
        return candidate.id

    async def get_supersede_candidate(self, id: str) -> SupersedeCandidate | None:
        blob_path = self._blob_path("supersede_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return SupersedeCandidate.from_dict(data)

    async def list_supersede_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[SupersedeCandidate]:
        where_parts = ["project_name = ?"]
        params = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "supersede_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("supersede_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(SupersedeCandidate.from_dict(data))
        return results

    async def update_supersede_candidate_status(
        self,
        id: str,
        status: str,
        *,
        reviewed_at: datetime | None = None,
        reviewer_id: str | None = None,
    ) -> bool:
        reviewed_at = reviewed_at or datetime.now(timezone.utc)
        return await self.candidate_store.update_status(
            "supersede_candidates",
            id,
            status,
            index_updates={
                "reviewed_at": reviewed_at,
                "reviewer_id": reviewer_id,
            },
            payload_updates={
                "reviewed_at": reviewed_at.isoformat(),
                "reviewer_id": reviewer_id,
            },
        )

    async def confirm_supersede_candidate(
        self,
        id: str,
        *,
        reviewed_at: datetime | None = None,
        reviewer_id: str | None = None,
    ) -> SupersedeCandidate | None:
        candidate = await self.get_supersede_candidate(id)
        if candidate is None or candidate.status != "pending":
            return None
        if (
            candidate.target_type == candidate.replacement_type
            and candidate.target_id == candidate.replacement_id
        ):
            return None

        reviewed_at = reviewed_at or datetime.now(timezone.utc)
        try:
            target_loaded = self._load_truth_data(
                candidate.target_type, candidate.target_id
            )
            replacement_loaded = self._load_truth_data(
                candidate.replacement_type, candidate.replacement_id
            )
        except ValueError:
            return None
        if target_loaded is None or replacement_loaded is None:
            return None

        target_collection, _, target_original = target_loaded
        replacement_collection, _, replacement_original = replacement_loaded

        target_updated = self._apply_truth_supersede_updates(
            target_original,
            valid_to=reviewed_at,
            add_superseded_by=candidate.replacement_id,
        )
        replacement_updated = self._apply_truth_supersede_updates(
            replacement_original,
            add_supersedes=candidate.target_id,
        )
        if not await self._persist_truth_snapshot(
            target_collection, candidate.target_id, target_updated
        ):
            return None
        if not await self._persist_truth_snapshot(
            replacement_collection, candidate.replacement_id, replacement_updated
        ):
            await self._persist_truth_snapshot(
                target_collection, candidate.target_id, target_original
            )
            return None
        if not await self.update_supersede_candidate_status(
            id,
            user_confirm_status(),
            reviewed_at=reviewed_at,
            reviewer_id=reviewer_id,
        ):
            await self._persist_truth_snapshot(
                replacement_collection, candidate.replacement_id, replacement_original
            )
            await self._persist_truth_snapshot(
                target_collection, candidate.target_id, target_original
            )
            return None
        return await self.get_supersede_candidate(id)

    # ---- MergeSuggestionCandidate ----

    async def save_merge_suggestion_candidate(
        self, candidate: MergeSuggestionCandidate
    ) -> str:
        blob_path = self._blob_path("merge_suggestion_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "merge_suggestion_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "target_a_id": candidate.target_a_id,
                "target_a_kind": candidate.target_a_kind,
                "target_b_id": candidate.target_b_id,
                "target_b_kind": candidate.target_b_kind,
                "similarity_score": candidate.similarity_score,
                "status": candidate.status,
                "metabolism_run_id": candidate.metabolism_run_id,
                "created_at": candidate.created_at,
            },
        )
        return candidate.id

    async def get_merge_suggestion_candidate(
        self, id: str
    ) -> MergeSuggestionCandidate | None:
        blob_path = self._blob_path("merge_suggestion_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return MergeSuggestionCandidate.from_dict(data)

    async def list_merge_suggestion_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[MergeSuggestionCandidate]:
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "merge_suggestion_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results: list[MergeSuggestionCandidate] = []
        for row in rows:
            blob_path = self._blob_path("merge_suggestion_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(MergeSuggestionCandidate.from_dict(data))
        return results

    async def update_merge_suggestion_candidate_status(
        self, id: str, status: str
    ) -> bool:
        return await self.candidate_store.update_status(
            "merge_suggestion_candidates",
            id,
            status,
        )

    # ---- StaleTruthSuggestionCandidate ----

    async def save_stale_truth_suggestion_candidate(
        self, candidate: StaleTruthSuggestionCandidate
    ) -> str:
        blob_path = self._blob_path("stale_truth_suggestion_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "stale_truth_suggestion_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "target_id": candidate.target_id,
                "target_kind": candidate.target_kind,
                "last_surfaced_at": candidate.last_surfaced_at,
                "days_since_last_surface": candidate.days_since_last_surface,
                "status": candidate.status,
                "metabolism_run_id": candidate.metabolism_run_id,
                "created_at": candidate.created_at,
            },
        )
        return candidate.id

    async def get_stale_truth_suggestion_candidate(
        self, id: str
    ) -> StaleTruthSuggestionCandidate | None:
        blob_path = self._blob_path("stale_truth_suggestion_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return StaleTruthSuggestionCandidate.from_dict(data)

    async def list_stale_truth_suggestion_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[StaleTruthSuggestionCandidate]:
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "stale_truth_suggestion_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results: list[StaleTruthSuggestionCandidate] = []
        for row in rows:
            blob_path = self._blob_path("stale_truth_suggestion_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(StaleTruthSuggestionCandidate.from_dict(data))
        return results

    async def update_stale_truth_suggestion_candidate_status(
        self, id: str, status: str
    ) -> bool:
        return await self.candidate_store.update_status(
            "stale_truth_suggestion_candidates",
            id,
            status,
        )

    # ---- ProceduralCandidate ----

    async def save_procedural_candidate(self, candidate: ProceduralCandidate) -> str:
        blob_path = self._blob_path("procedural_candidates", candidate.id)
        blob_path.write_text(json.dumps(candidate.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "procedural_candidates",
            {
                "id": candidate.id,
                "project_name": candidate.project_name,
                "activation_condition": candidate.activation_condition,
                "steps": candidate.steps,
                "termination_condition": candidate.termination_condition,
                "success_examples": candidate.success_examples,
                "source_session_id": candidate.source_session_id,
                "source": candidate.source,
                "confidence": candidate.confidence,
                "status": candidate.status,
                "created_at": candidate.created_at,
                "search_text": self._procedural_search_text(
                    activation_condition=candidate.activation_condition,
                    steps=candidate.steps,
                    termination_condition=candidate.termination_condition,
                    success_examples=candidate.success_examples,
                ),
            },
        )
        return candidate.id

    async def get_procedural_candidate(self, id: str) -> ProceduralCandidate | None:
        blob_path = self._blob_path("procedural_candidates", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return ProceduralCandidate.from_dict(data)

    async def list_procedural_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[ProceduralCandidate]:
        where_parts = ["project_name = ?"]
        params = [project_name]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        rows = await asyncio.to_thread(
            self._index.list,
            "procedural_candidates",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("procedural_candidates", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(ProceduralCandidate.from_dict(data))
        return results

    async def update_procedural_candidate_status(self, id: str, status: str) -> bool:
        return await self.candidate_store.update_status(
            "procedural_candidates", id, status
        )

    async def confirm_procedural_candidate(self, id: str) -> Skill | None:
        candidate = await self.get_procedural_candidate(id)
        if candidate is None or candidate.status != "pending":
            return None

        now = datetime.now(timezone.utc)
        skill = Skill(
            project_name=candidate.project_name,
            name=self._skill_name_for_candidate(candidate),
            activation_condition=candidate.activation_condition,
            steps=candidate.steps,
            termination_condition=candidate.termination_condition,
            success_examples=candidate.success_examples,
            source_candidate_id=candidate.id,
            source_session_id=candidate.source_session_id,
            scope="project",
            origin_project=candidate.project_name,
            source_ids=[
                source_id
                for source_id in (
                    candidate.id,
                    candidate.source_session_id,
                    candidate.source,
                )
                if source_id
            ],
            confidence=candidate.confidence,
            created_at=now,
            updated_at=now,
        )
        await self.save_skill(skill)
        updated = await self.update_procedural_candidate_status(
            candidate.id, user_confirm_status()
        )
        if not updated:
            return None
        return skill

    # ---- Skill ----
