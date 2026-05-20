"""StructuredStore interface — structured memory read/write abstraction."""

from __future__ import annotations
from datetime import datetime
from typing import Protocol, runtime_checkable

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.relation_fact import RelationFact


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
        status: str = "accepted",
        include_history: bool = False,
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
        status: str = "accepted",
        memory_type: list[str] | None = None,
        include_history: bool = False,
    ) -> list[MemoryEntry]:
        """Full-text search memory entries with status filtering.

        v1.6.1: ``memory_type`` is an optional OR-filter list ({episodic,
        semantic, procedural}); ``None`` / ``[]`` means no filtering.
        """
        ...

    async def update_memory_entry_status(self, id: str, status: str) -> bool:
        """Update the status of a memory entry (e.g. pending -> accepted)."""
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
        """Update candidate status (pending/accepted/rejected)."""
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
        status: str = "accepted",
        include_history: bool = False,
    ) -> list[RelationFact]:
        """List relation facts for a project with optional filters."""
        ...

    async def search_relation_facts(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
        status: str = "accepted",
        include_history: bool = False,
    ) -> list[RelationFact]:
        """Search relation facts by indexed evidence text with status filtering."""
        ...

    async def update_relation_fact_status(self, id: str, status: str) -> bool:
        """Update the status of a relation fact."""
        ...
