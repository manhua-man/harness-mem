"""MergeSuggestionCandidate — pending merge proposal between two truths.

v2.3.1 metabolism pass produces these as candidates when two confirmed
truths in the replay window have embedding similarity above the
configured threshold (default 0.85). The pass writes
``proposed_content=""``; the merged content is generated at confirm
time by the Agent calling ``confirm_merge_candidate`` (or by
``auto_review_candidates`` apply branch). This keeps the metabolism
pass a pure local algorithm with no LLM dependency.

Contract:
* Pair ordering: ``target_a_id < target_b_id`` enforced at construction.
* Scope: only ``memory_entry`` and ``confirmed_rule`` kinds; fact merges
  deferred to v2.3.2+.
* ``evidence_signal_ids`` may be empty — embedding similarity is the
  primary trigger, signals are supplementary evidence.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class MergeSuggestionCandidate(BaseModel):
    """Pending request to merge two truths into one new truth.

    Apply path: confirming this candidate sets ``valid_to=now`` on both
    ``target_a`` and ``target_b``, then creates a new ``MemoryEntry``
    with ``content=proposed_content`` whose ``supersedes`` chain points
    back to both targets.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    target_a_id: str = Field(description="Lex-min id of the pair (target_a_id < target_b_id).")
    target_a_kind: Literal["memory_entry", "confirmed_rule"]
    target_b_id: str = Field(description="Lex-max id of the pair (target_a_id < target_b_id).")
    target_b_kind: Literal["memory_entry", "confirmed_rule"]
    proposed_content: str = Field(
        default="",
        description="Empty when written by the pass; filled at confirm time by the Agent.",
    )
    similarity_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Embedding similarity between target_a and target_b that triggered the pair.",
    )
    evidence_signal_ids: list[str] = Field(default_factory=list)
    status: Literal["pending", "accepted", "rejected"] = Field(default="pending")
    metabolism_run_id: str = Field(description="Back-reference to the run that produced it.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _validate_pair_ordering(self) -> "MergeSuggestionCandidate":
        if self.target_a_id == self.target_b_id:
            raise ValueError(
                "MergeSuggestionCandidate: target_a_id and target_b_id must differ "
                "(a truth cannot merge with itself)."
            )
        if self.target_a_id >= self.target_b_id:
            raise ValueError(
                "MergeSuggestionCandidate: target_a_id must be lexicographically less "
                f"than target_b_id (got {self.target_a_id!r} >= {self.target_b_id!r}). "
                "Normalize the pair before constructing."
            )
        return self

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "target_a_id": self.target_a_id,
            "target_a_kind": self.target_a_kind,
            "target_b_id": self.target_b_id,
            "target_b_kind": self.target_b_kind,
            "proposed_content": self.proposed_content,
            "similarity_score": self.similarity_score,
            "evidence_signal_ids": list(self.evidence_signal_ids),
            "status": self.status,
            "metabolism_run_id": self.metabolism_run_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MergeSuggestionCandidate":
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "proposed_content" not in data:
            data["proposed_content"] = ""
        if "evidence_signal_ids" not in data:
            data["evidence_signal_ids"] = []
        if "status" not in data:
            data["status"] = "pending"
        return cls(**data)
