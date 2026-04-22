"""StructuredStore interface — structured memory read/write abstraction."""

from __future__ import annotations
from typing import Protocol, runtime_checkable

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule


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
    ) -> list[MemoryEntry]:
        """List memory entries for a project, optionally filtered by category."""
        ...

    async def search_memory_entries(
        self,
        query: str,
        project_name: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Full-text search memory entries."""
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
    ) -> list[ConfirmedRule]:
        """List all confirmed rules for a project."""
        ...
