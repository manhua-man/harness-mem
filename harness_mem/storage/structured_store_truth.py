"""Skill, rule, and relation persistence for LocalStructuredStore."""

# The concrete LocalStructuredStore supplies persistence primitives and sibling
# capability methods through composition. Contract tests exercise the complete host.
# mypy: disable-error-code="attr-defined"

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from typing import Any

from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.governance_status import (
    GOVERNANCE_STATUSES,
    READABLE_TRUTH_FILTER,
    statuses_for_list_filter,
    validate_status_transition,
)
from harness_mem.storage.structured_store_support import (
    _copy_search_score_fields,
)


class StructuredTruthMixin:
    async def save_skill(self, skill: Skill) -> str:
        blob_path = self._blob_path("skills", skill.id)
        blob_path.write_text(json.dumps(skill.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "skills",
            {
                "id": skill.id,
                "project_name": skill.project_name,
                "name": skill.name,
                "activation_condition": skill.activation_condition,
                "steps": skill.steps,
                "termination_condition": skill.termination_condition,
                "success_examples": skill.success_examples,
                "source_candidate_id": skill.source_candidate_id,
                "source_session_id": skill.source_session_id,
                "scope": skill.scope,
                "origin_project": skill.origin_project,
                "source_ids": skill.source_ids,
                "portability_notes": skill.portability_notes,
                "disabled_assumptions": skill.disabled_assumptions,
                "confidence": skill.confidence,
                "status": skill.status,
                "usage_count": skill.usage_count,
                "success_count": skill.success_count,
                "failure_count": skill.failure_count,
                "success_rate": skill.success_rate,
                "created_at": skill.created_at,
                "updated_at": skill.updated_at,
                "last_used_at": skill.last_used_at,
                "search_text": self._procedural_search_text(
                    name=skill.name,
                    activation_condition=skill.activation_condition,
                    steps=skill.steps,
                    termination_condition=skill.termination_condition,
                    success_examples=skill.success_examples,
                ),
            },
        )
        return skill.id

    async def get_skill(self, id: str) -> Skill | None:
        blob_path = self._blob_path("skills", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return Skill.from_dict(data)

    async def list_skills(
        self,
        project_name: str,
        status: str = "active",
    ) -> list[Skill]:
        rows = await asyncio.to_thread(
            self._index.list,
            "skills",
            "project_name = ? AND COALESCE(status, 'active') = ? AND COALESCE(scope, 'project') = 'project'",
            (project_name, status),
            order_by="updated_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("skills", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(Skill.from_dict(data))
        return results

    async def list_skills_any_scope(
        self,
        project_name: str,
        status: str = "active",
    ) -> list[Skill]:
        rows = await asyncio.to_thread(
            self._index.list,
            "skills",
            "project_name = ? AND COALESCE(status, 'active') = ?",
            (project_name, status),
            order_by="updated_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("skills", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(Skill.from_dict(data))
        return results

    async def search_skills(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 10,
        status: str = "active",
        shared_scope: str = "exclude",
    ) -> list[Skill]:
        if shared_scope not in {"exclude", "include", "only"}:
            raise ValueError("shared_scope must be one of: exclude, include, only")

        def load_rows(rows: list[dict]) -> list[Skill]:
            results: list[Skill] = []
            for row in rows:
                blob_path = self._blob_path("skills", row["id"])
                if not blob_path.exists():
                    continue
                data = json.loads(blob_path.read_text())
                if data.get("status", "active") != status:
                    continue
                _copy_search_score_fields(data, row)
                results.append(Skill.from_dict(data))
            return results

        async def run_search(
            where_parts: list[str], params: tuple[object, ...]
        ) -> list[Skill]:
            rows = await asyncio.to_thread(
                self._index.search,
                "skills",
                query,
                limit,
                " AND ".join(where_parts),
                params,
            )
            return load_rows(rows)

        if not project_name:
            where_parts = ["COALESCE(status, 'active') = ?"]
            params: tuple[object, ...] = (status,)
            if shared_scope == "only":
                where_parts.append(
                    "COALESCE(scope, 'project') IN ('workspace', 'global')"
                )
            return await run_search(where_parts, params)

        project_where_parts = [
            "COALESCE(status, 'active') = ?",
            "project_name = ?",
            "COALESCE(scope, 'project') = 'project'",
        ]
        project_params: tuple[object, ...] = (status, project_name)
        if shared_scope == "exclude":
            return await run_search(project_where_parts, project_params)

        shared_where_parts = [
            "COALESCE(status, 'active') = ?",
            "COALESCE(scope, 'project') IN ('workspace', 'global')",
        ]
        shared_params: tuple[object, ...] = (status,)

        shared_matches = await run_search(shared_where_parts, shared_params)
        if shared_scope == "only":
            return shared_matches[:limit]

        project_matches = await run_search(project_where_parts, project_params)
        ordered_matches: list[Skill] = []
        seen_ids: set[str] = set()
        for skill in [*project_matches, *shared_matches]:
            if skill.id in seen_ids:
                continue
            seen_ids.add(skill.id)
            ordered_matches.append(skill)
            if len(ordered_matches) >= limit:
                break
        return ordered_matches

    async def record_skill_result(
        self,
        id: str,
        *,
        success: bool,
        used_at: datetime | None = None,
    ) -> Skill | None:
        skill = await self.get_skill(id)
        if skill is None:
            return None
        updated_skill = skill.record_result(success=success, used_at=used_at)
        blob_path = self._blob_path("skills", updated_skill.id)
        blob_path.write_text(json.dumps(updated_skill.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "skills",
            updated_skill.id,
            {
                "usage_count": updated_skill.usage_count,
                "success_count": updated_skill.success_count,
                "failure_count": updated_skill.failure_count,
                "success_rate": updated_skill.success_rate,
                "updated_at": updated_skill.updated_at,
                "last_used_at": updated_skill.last_used_at,
            },
        )
        return updated_skill

    async def update_skill_status(self, id: str, status: str) -> Skill | None:
        skill = await self.get_skill(id)
        if skill is None:
            return None
        updated_skill = skill.model_copy(
            update={
                "status": status,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        blob_path = self._blob_path("skills", updated_skill.id)
        blob_path.write_text(json.dumps(updated_skill.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "skills",
            updated_skill.id,
            {
                "status": updated_skill.status,
                "updated_at": updated_skill.updated_at,
            },
        )
        return updated_skill

    # ---- ConfirmedRule ----

    async def save_confirmed_rule(self, rule: ConfirmedRule) -> str:
        blob_path = self._blob_path("confirmed_rules", rule.id)
        blob_path.write_text(json.dumps(rule.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "confirmed_rules",
            {
                "id": rule.id,
                "project_name": rule.project_name,
                "pattern": rule.pattern,
                "trigger": rule.trigger,
                "examples": rule.examples,
                "confirmed_at": rule.confirmed_at,
                "source_candidate_id": rule.source_candidate_id,
                "source_session_id": rule.source_session_id,
                "tags": rule.tags,
                "usage_count": rule.usage_count,
                "last_surfaced_at": rule.last_surfaced_at,
                "valid_from": rule.valid_from,
                "valid_to": rule.valid_to,
                "recorded_at": rule.recorded_at,
                "supersedes": rule.supersedes,
                "superseded_by": rule.superseded_by,
            },
        )
        return rule.id

    async def get_confirmed_rule(self, id: str) -> ConfirmedRule | None:
        blob_path = self._blob_path("confirmed_rules", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return ConfirmedRule.from_dict(data)

    async def touch_confirmed_rule(
        self, id: str, accessed_at: datetime | None = None
    ) -> bool:
        """Record that a confirmed rule was surfaced (e.g. by wake-up).

        Increments ``usage_count`` and updates ``last_surfaced_at`` on the
        blob and the index. Mirrors :meth:`touch_memory_entry` so wake-up
        and search can use a uniform "I just showed this to a user" signal
        regardless of which structured truth type they touched.
        """
        blob_path = self._blob_path("confirmed_rules", id)
        if not blob_path.exists():
            return False

        touched_at = accessed_at or datetime.now(timezone.utc)
        data = json.loads(blob_path.read_text())
        usage_count = int(data.get("usage_count") or 0) + 1
        data["usage_count"] = usage_count
        data["last_surfaced_at"] = touched_at.isoformat()
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "confirmed_rules",
            id,
            {
                "usage_count": usage_count,
                "last_surfaced_at": touched_at,
            },
        )
        return True

    async def list_confirmed_rules(
        self,
        project_name: str,
        include_history: bool = False,
    ) -> list[ConfirmedRule]:
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if not include_history:
            clause, clause_params = self._current_only_clause()
            where_parts.append(clause)
            params.extend(clause_params)
        rows = await asyncio.to_thread(
            self._index.list,
            "confirmed_rules",
            " AND ".join(where_parts),
            tuple(params),
            order_by="confirmed_at DESC",
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("confirmed_rules", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if not include_history and not self._is_current_data(data):
                    continue
                results.append(ConfirmedRule.from_dict(data))
        return results

    # ---- RelationFact ----

    async def save_relation_fact(self, fact: RelationFact) -> str:
        blob_path = self._blob_path("relation_facts", fact.id)
        blob_path.write_text(json.dumps(fact.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.upsert,
            "relation_facts",
            {
                "id": fact.id,
                "project_name": fact.project_name,
                "source_entity": fact.source_entity,
                "target_entity": fact.target_entity,
                "relation_type": fact.relation_type,
                "confidence": fact.confidence,
                "status": fact.status,
                "evidence": fact.evidence,
                "source": fact.source,
                "created_at": fact.created_at,
                "updated_at": fact.updated_at,
                "tags": fact.tags,
                "valid_from": fact.valid_from,
                "valid_to": fact.valid_to,
                "recorded_at": fact.recorded_at,
                "supersedes": fact.supersedes,
                "superseded_by": fact.superseded_by,
            },
        )
        return fact.id

    async def get_relation_fact(self, id: str) -> RelationFact | None:
        blob_path = self._blob_path("relation_facts", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return RelationFact.from_dict(data)

    async def list_relation_facts(
        self,
        project_name: str,
        source_entity: str | None = None,
        target_entity: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        include_provisional: bool = False,
    ) -> list[RelationFact]:
        status_filter = statuses_for_list_filter(
            status,
            include_provisional=include_provisional,
            include_superseded=include_history,
        )
        placeholders = ",".join(["?"] * len(status_filter))
        where_parts = [
            "project_name = ?",
            f"COALESCE(status, 'pending') IN ({placeholders})",
        ]
        params: list[Any] = [project_name, *status_filter]
        if not include_history:
            clause, clause_params = self._current_only_clause()
            where_parts.append(clause)
            params.extend(clause_params)
        if source_entity:
            where_parts.append("source_entity = ?")
            params.append(source_entity)
        if target_entity:
            where_parts.append("target_entity = ?")
            params.append(target_entity)
        if relation_type:
            where_parts.append("relation_type = ?")
            params.append(relation_type)

        rows = await asyncio.to_thread(
            self._index.list,
            "relation_facts",
            " AND ".join(where_parts),
            tuple(params),
            order_by="created_at DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("relation_facts", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("status", "pending") not in status_filter:
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                results.append(RelationFact.from_dict(data))
        return results

    async def search_relation_facts(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
        include_provisional: bool = False,
    ) -> list[RelationFact]:
        status_filter = statuses_for_list_filter(
            status,
            include_provisional=include_provisional,
            include_superseded=include_history,
        )
        placeholders = ",".join(["?"] * len(status_filter))
        extra_where_parts = [f"COALESCE(status, 'pending') IN ({placeholders})"]
        extra_params: tuple = tuple(status_filter)
        if not include_history:
            clause, clause_params = self._current_only_clause()
            extra_where_parts.append(clause)
            extra_params = (*extra_params, *clause_params)
        if project_name:
            extra_where_parts.append("project_name = ?")
            extra_params = (*extra_params, project_name)
        window_clause, window_params = self._time_window_clause(time_window)
        if window_clause:
            extra_where_parts.append(window_clause)
            extra_params = (*extra_params, *window_params)

        rows = await asyncio.to_thread(
            self._index.search,
            "relation_facts",
            query,
            limit,
            " AND ".join(extra_where_parts) if extra_where_parts else None,
            extra_params,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path("relation_facts", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("status", "pending") not in status_filter:
                    continue
                if not include_history and not self._is_current_data(data):
                    continue
                if not self._truth_in_time_window(data, time_window):
                    continue
                _copy_search_score_fields(data, row)
                results.append(RelationFact.from_dict(data))
        return results

    async def update_relation_fact_status(self, id: str, status: str) -> bool:
        """Update the governance status of a relation fact."""
        if status not in GOVERNANCE_STATUSES:
            return False
        blob_path = self._blob_path("relation_facts", id)
        if not blob_path.exists():
            return False
        data = json.loads(blob_path.read_text())
        current = data.get("status", "pending")
        if not validate_status_transition(current, status):
            return False
        data["status"] = status
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(
            self._index.update,
            "relation_facts",
            id,
            {"status": status},
        )
        return True

    # ---- MetabolismRun ----
