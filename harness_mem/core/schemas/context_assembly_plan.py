"""ContextAssemblyPlan schema — read-only, layered description of assembled context.

v2.5.0 reframes context as an *explainable, budgeted, layered* assembly. This
module defines the pure data structure that records the result of that
assembly: a :class:`ContextAssemblyPlan` carrying exactly five ordered layers
(L0..L4), each holding zero or more :class:`PlanEntry` records plus per-layer
:class:`Budget` and :class:`TruncationAccounting` metadata.

The plan is a *description* of context, not rendered context text, and it is a
pure data structure: construction and serialization never read from or write to
any store (Req 1.9). Serialization follows the project ``to_dict()`` /
``from_dict()`` convention — datetimes become ISO 8601 strings and nested
records serialize to JSON-compatible structures (Req 1.5).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# The five fixed context tiers, in canonical order (Req 1.2).
LayerId = Literal["L0", "L1", "L2", "L3", "L4"]
LAYER_ORDER: tuple[LayerId, ...] = ("L0", "L1", "L2", "L3", "L4")

# Truth-status indicator carried by each Plan_Entry so pending / historical
# references are never presented as confirmed current truth (Req 10.3).
TruthStatus = Literal["confirmed_current", "pending", "historical"]
TokenCountBasis = Literal[
    "observed_usage",
    "tokenizer_estimate",
    "character_estimate",
]
ProjectionOutcome = Literal[
    "none",
    "truncated",
    "evicted",
    "compacted",
    "fallback",
]


def _validate_layer_id(value: object) -> None:
    """Raise ``ValueError`` naming the field and offending value (Req 1.8).

    This is an explicit guard so the message is stable
    (e.g. ``ValueError("layer: invalid value 'L9'")``) rather than relying on
    Pydantic's generic ``ValidationError`` text.
    """
    if value not in LAYER_ORDER:
        raise ValueError(f"layer: invalid value {value!r}")


class Budget(BaseModel):
    """Per-layer limit applied while assembling the plan (Req 6.1)."""

    max_entries: int = Field(gt=0)  # per-layer hard limit
    max_chars: int | None = Field(default=None, ge=0)  # optional hard text cap

    def to_dict(self) -> dict:
        return {
            "max_entries": self.max_entries,
            "max_chars": self.max_chars,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Budget":
        return cls(**data)


class TruncationAccounting(BaseModel):
    """Per-layer record of how candidates fared against the budget (Req 6.3)."""

    available: int = Field(ge=0)  # candidates considered
    included: int = Field(ge=0)  # entries placed in the layer
    dropped: int = Field(ge=0)  # candidates cut because the budget was reached

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "included": self.included,
            "dropped": self.dropped,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TruncationAccounting":
        return cls(**data)


class DrilldownPointer(BaseModel):
    """Expansion reference carried by an L4 Plan_Entry (Req 7.2, 7.6)."""

    source_id: str  # the record to expand
    read_surface: str  # e.g. "read_api.get_observations"
    locator: dict = Field(default_factory=dict)  # extra ids (session_id, etc.)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "read_surface": self.read_surface,
            "locator": dict(self.locator),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DrilldownPointer":
        return cls(**data)


class ContextProjectionReceipt(BaseModel):
    """Content-free audit record for one read-only context projection.

    The receipt describes selection and budgeting only. It is not durable
    truth and never embeds source text. ``compacted`` is valid only when a
    caller explicitly records that it created a summary.
    """

    schema_version: Literal["context_projection_receipt.v1"] = (
        "context_projection_receipt.v1"
    )
    source_revision: str | None = None
    before_tokens: int = Field(ge=0)
    after_tokens: int = Field(ge=0)
    kept_source_ids: list[str] = Field(default_factory=list)
    evicted_source_ids: list[str] = Field(default_factory=list)
    token_basis: TokenCountBasis
    outcome: ProjectionOutcome = "none"
    summary_generated: bool = False
    drilldown: list[DrilldownPointer] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.outcome == "compacted" and not self.summary_generated:
            raise ValueError(
                "outcome: 'compacted' requires summary_generated=true"
            )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "kept_source_ids": list(self.kept_source_ids),
            "evicted_source_ids": list(self.evicted_source_ids),
            "token_basis": self.token_basis,
            "outcome": self.outcome,
            "summary_generated": self.summary_generated,
            "drilldown": [pointer.to_dict() for pointer in self.drilldown],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextProjectionReceipt":
        data = dict(data)
        data["drilldown"] = [
            DrilldownPointer.from_dict(pointer)
            if isinstance(pointer, dict)
            else pointer
            for pointer in list(data.get("drilldown") or [])
        ]
        return cls(**data)


class PlanEntry(BaseModel):
    """A single item placed in a Layer (Req 1.4)."""

    layer: LayerId
    source_ids: list[str] = Field(min_length=1)  # >=1 element (Req 1.4, 8.1)
    why_included: str = Field(min_length=1)  # non-empty reason (Req 1.4)
    summary: str = Field(default="")  # L0-L3 content (Req 1.4)
    drilldown: DrilldownPointer | None = Field(default=None)  # L4 only (Req 7.1)
    truth_status: TruthStatus = "confirmed_current"  # (Req 10.3)

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "source_ids": list(self.source_ids),
            "why_included": self.why_included,
            "summary": self.summary,
            "drilldown": self.drilldown.to_dict() if self.drilldown else None,
            "truth_status": self.truth_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanEntry":
        data = dict(data)
        if "layer" in data:
            _validate_layer_id(data["layer"])
        drilldown = data.get("drilldown")
        if isinstance(drilldown, dict):
            data["drilldown"] = DrilldownPointer.from_dict(drilldown)
        return cls(**data)


class Layer(BaseModel):
    """One named context tier carrying its entries, budget, and accounting."""

    layer: LayerId
    entries: list[PlanEntry] = Field(default_factory=list)  # default [] (Req 1.3, 1.7)
    budget: Budget
    truncation: TruncationAccounting

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "entries": [entry.to_dict() for entry in self.entries],
            "budget": self.budget.to_dict(),
            "truncation": self.truncation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Layer":
        data = dict(data)
        if "layer" in data:
            _validate_layer_id(data["layer"])
        # Req 1.7: an absent (or null) ``entries`` key defaults to an empty list.
        raw_entries = data.get("entries")
        if raw_entries is None:
            data["entries"] = []
        else:
            data["entries"] = [
                PlanEntry.from_dict(entry) if isinstance(entry, dict) else entry
                for entry in raw_entries
            ]
        budget = data.get("budget")
        if isinstance(budget, dict):
            data["budget"] = Budget.from_dict(budget)
        truncation = data.get("truncation")
        if isinstance(truncation, dict):
            data["truncation"] = TruncationAccounting.from_dict(truncation)
        return cls(**data)


class ContextAssemblyPlan(BaseModel):
    """Canonical, serializable description of an assembled context (Req 1.1)."""

    project_name: str
    query: str | None = None
    layers: list[Layer]  # exactly 5, ordered L0..L4 (Req 1.1, 1.2)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context_budget: dict[str, int] = Field(default_factory=dict)
    compaction_outcome: str = "none"
    projection_receipt: ContextProjectionReceipt | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "query": self.query,
            "layers": [layer.to_dict() for layer in self.layers],
            "created_at": self.created_at.isoformat(),
            "context_budget": dict(self.context_budget),
            "compaction_outcome": self.compaction_outcome,
            "projection_receipt": (
                self.projection_receipt.to_dict()
                if self.projection_receipt is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextAssemblyPlan":
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        raw_layers = data.get("layers")
        if raw_layers is not None:
            data["layers"] = [
                Layer.from_dict(layer) if isinstance(layer, dict) else layer
                for layer in raw_layers
            ]
        receipt = data.get("projection_receipt")
        if isinstance(receipt, dict):
            data["projection_receipt"] = ContextProjectionReceipt.from_dict(receipt)
        return cls(**data)

    def layer(self, layer_id: LayerId) -> Layer:
        """Return the single Layer with the given id.

        Convenience accessor over the ordered ``layers`` collection. Raises
        ``ValueError`` when no layer carries ``layer_id``.
        """
        for layer_record in self.layers:
            if layer_record.layer == layer_id:
                return layer_record
        raise ValueError(f"layer: no layer with id {layer_id!r}")
