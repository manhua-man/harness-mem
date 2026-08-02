"""StructuredStore interface — structured memory read/write abstraction."""

from __future__ import annotations
from datetime import datetime
from typing import Protocol, runtime_checkable

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.core.schemas.merge_suggestion_candidate import MergeSuggestionCandidate
from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.procedural_candidate import ProceduralCandidate
from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.metabolism_run import MetabolismRun
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.governance_status import READABLE_TRUTH_FILTER


@runtime_checkable
class StructuredStore(Protocol):
    """Structured memory store interface.

    Handles MemoryEntry, TaskHandoff, RuleCandidate, and ConfirmedRule.
    Each entity type has its own namespace and access patterns.
    """

    # ---- MemoryEntry ----

    async def save_memory_entry(self, entry: MemoryEntry) -> str:
        """Save a memory entry. Returns the entry id."""
        ...

    async def get_memory_entry(self, id: str) -> MemoryEntry | None:
        """Get a single memory entry by id."""
        ...

    async def list_memory_entries(
        self,
        project_name: str,
        category: str | None = None,
        limit: int = 100,
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        deep_recall: bool = False,
        include_provisional: bool = False,
    ) -> list[MemoryEntry]:
        """List memory entries for a project.

        v1.7.0: ``include_history=False`` returns current truth only.
        """
        ...

    async def search_memory_entries(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        mode: str = "auto",
        status: str = READABLE_TRUTH_FILTER,
        memory_type: list[str] | None = None,
        include_history: bool = False,
        deep_recall: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
        include_provisional: bool = False,
        as_of: datetime | None = None,
    ) -> list[MemoryEntry]:
        """Full-text search memory entries with status filtering.

        v1.6.1: ``memory_type`` is an optional OR-filter list ({episodic,
        semantic, procedural}); ``None`` / ``[]`` means no filtering.
        """
        ...

    async def update_memory_entry_status(self, id: str, status: str) -> bool:
        """Update the governance status of a memory entry."""
        ...

    async def soft_delete_memory_entry(self, id: str) -> bool:
        """Soft-delete a memory entry by setting compacted=True. Returns True if updated."""
        ...

    async def touch_memory_entry(self, id: str, accessed_at: datetime | None = None) -> bool:
        """Record that a memory entry was surfaced to a user or MCP client."""
        ...

    # ---- TaskHandoff ----

    async def save_task_handoff(self, handoff: TaskHandoff) -> str:
        """Save a task handoff. Returns the handoff id."""
        ...

    async def get_task_handoff(self, id: str) -> TaskHandoff | None:
        """Get a single task handoff by id."""
        ...

    async def get_latest_handoffs(
        self,
        project_name: str,
        limit: int = 5,
    ) -> list[TaskHandoff]:
        """Get most recent handoffs for a project."""
        ...

    # ---- RuleCandidate ----

    async def save_rule_candidate(
        self,
        candidate: RuleCandidate,
    ) -> str:
        """Save a rule candidate. Returns the candidate id."""
        ...

    async def get_rule_candidate(self, id: str) -> RuleCandidate | None:
        """Get a single rule candidate by id."""
        ...

    async def list_rule_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[RuleCandidate]:
        """List rule candidates for a project, optionally filtered by status."""
        ...

    async def update_rule_candidate_status(
        self,
        id: str,
        status: str,
    ) -> bool:
        """Update candidate status (governance or maintenance-review status)."""
        ...

    # ---- SupersedeCandidate ----

    async def save_supersede_candidate(
        self,
        candidate: SupersedeCandidate,
    ) -> str:
        """Save a supersede candidate. Returns the candidate id."""
        ...

    async def get_supersede_candidate(self, id: str) -> SupersedeCandidate | None:
        """Get a single supersede candidate by id."""
        ...

    async def list_supersede_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[SupersedeCandidate]:
        """List supersede candidates for a project, optionally filtered by status."""
        ...

    async def update_supersede_candidate_status(
        self,
        id: str,
        status: str,
        *,
        reviewed_at: datetime | None = None,
        reviewer_id: str | None = None,
    ) -> bool:
        """Update supersede candidate review status."""
        ...

    # ---- ConfirmedRule ----

    async def save_confirmed_rule(self, rule: ConfirmedRule) -> str:
        """Save a confirmed rule. Returns the rule id."""
        ...

    async def get_confirmed_rule(self, id: str) -> ConfirmedRule | None:
        """Get a single confirmed rule by id."""
        ...

    async def list_confirmed_rules(
        self,
        project_name: str,
        include_history: bool = False,
    ) -> list[ConfirmedRule]:
        """List confirmed rules for a project.

        v1.7.0: ``include_history=False`` returns current truth only.
        """
        ...

    async def touch_confirmed_rule(
        self, id: str, accessed_at: datetime | None = None
    ) -> bool:
        """Record that a confirmed rule was surfaced (e.g. by wake-up).

        Mirrors :meth:`touch_memory_entry`: increments ``usage_count`` and
        updates ``last_surfaced_at`` so doctor / dashboards can flag rules
        that were confirmed but never actually consumed.
        """
        ...

    # ---- RelationFact ----

    async def save_relation_fact(self, fact: RelationFact) -> str:
        """Save a relation fact. Returns the fact id."""
        ...

    async def get_relation_fact(self, id: str) -> RelationFact | None:
        """Get a single relation fact by id."""
        ...

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
        """List relation facts for a project with optional filters."""
        ...

    async def search_relation_facts(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        status: str = READABLE_TRUTH_FILTER,
        include_history: bool = False,
        time_window: tuple[datetime | None, datetime | None] | None = None,
        include_provisional: bool = False,
        as_of: datetime | None = None,
    ) -> list[RelationFact]:
        """Search relation facts by indexed evidence text with status filtering."""
        ...

    async def update_relation_fact_status(self, id: str, status: str) -> bool:
        """Update the status of a relation fact."""
        ...

    async def confirm_supersede_candidate(
        self,
        id: str,
        *,
        reviewed_at: datetime | None = None,
        reviewer_id: str | None = None,
    ) -> SupersedeCandidate | None:
        """Confirm a pending supersede candidate and link target/replacement truth."""
        ...

    # ---- ProceduralCandidate / Skill ----

    async def save_procedural_candidate(
        self,
        candidate: ProceduralCandidate,
    ) -> str:
        """Save a procedural candidate. Returns the candidate id."""
        ...

    async def get_procedural_candidate(self, id: str) -> ProceduralCandidate | None:
        """Get a single procedural candidate by id."""
        ...

    async def list_procedural_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[ProceduralCandidate]:
        """List procedural candidates for a project, optionally filtered by status."""
        ...

    async def update_procedural_candidate_status(
        self,
        id: str,
        status: str,
    ) -> bool:
        """Update procedural candidate status."""
        ...

    async def confirm_procedural_candidate(self, id: str) -> Skill | None:
        """Promote a pending procedural candidate into a confirmed skill."""
        ...

    async def save_skill(self, skill: Skill) -> str:
        """Save a confirmed skill. Returns the skill id."""
        ...

    async def get_skill(self, id: str) -> Skill | None:
        """Get a single skill by id."""
        ...

    async def list_skills(
        self,
        project_name: str,
        status: str = "active",
    ) -> list[Skill]:
        """List confirmed skills for a project."""
        ...

    async def list_skills_any_scope(
        self,
        project_name: str,
        status: str = "active",
    ) -> list[Skill]:
        """List confirmed skills for a project across every scope."""
        ...

    async def search_skills(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 10,
        status: str = "active",
        shared_scope: str = "exclude",
    ) -> list[Skill]:
        """Search confirmed skills by activation, steps, and examples."""
        ...

    async def record_skill_result(
        self,
        id: str,
        *,
        success: bool,
        used_at: datetime | None = None,
    ) -> Skill | None:
        """Record one skill execution outcome and return the updated skill."""
        ...

    async def update_skill_status(self, id: str, status: str) -> Skill | None:
        """Update a skill's status and return the updated skill."""
        ...

    # ---- MergeSuggestionCandidate (read-side) ----

    async def get_merge_suggestion_candidate(
        self, id: str
    ) -> MergeSuggestionCandidate | None:
        """Get a single merge suggestion candidate by id."""
        ...

    async def list_merge_suggestion_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[MergeSuggestionCandidate]:
        """List merge suggestion candidates for a project, optionally filtered by status."""
        ...

    # ---- StaleTruthSuggestionCandidate (read-side) ----

    async def save_stale_truth_suggestion_candidate(
        self, candidate: StaleTruthSuggestionCandidate
    ) -> str:
        """Persist a stale-truth proposal and return its id."""
        ...

    async def get_stale_truth_suggestion_candidate(
        self, id: str
    ) -> StaleTruthSuggestionCandidate | None:
        """Get a single stale-truth suggestion candidate by id."""
        ...

    async def list_stale_truth_suggestion_candidates(
        self,
        project_name: str,
        status: str | None = None,
    ) -> list[StaleTruthSuggestionCandidate]:
        """List stale-truth suggestion candidates for a project, optionally filtered by status."""
        ...

    # ---- MetabolismRun (read-side) ----

    async def list_metabolism_runs(
        self,
        project_name: str,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MetabolismRun]:
        """List metabolism runs for a project, newest first.

        Writers (``save_metabolism_run``) stay implementation-side; only
        the read path is exposed on the Protocol, mirroring how
        ``touch_*`` and other write helpers are handled.
        """
        ...

    # ---- DreamRun (read-side) ----

    async def get_dream_run(self, id: str) -> DreamRun | None:
        """Get a single dream run by id."""
        ...

    async def list_dream_runs(
        self,
        project_name: str,
        *,
        limit: int = 20,
    ) -> list[DreamRun]:
        """List dream runs for a project, newest first."""
        ...

    # ---- RetrievalSignal (read-side) ----

    async def query_retrieval_signals(
        self,
        project_name: str,
        *,
        signal_type: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[RetrievalSignal]:
        """Query retrieval signals by filters; newest first."""
        ...
