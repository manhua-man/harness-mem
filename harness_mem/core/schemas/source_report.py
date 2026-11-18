"""A bounded report of what a source speaker said, never external truth."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, field_validator, model_serializer


class ReportTopicJudgment(BaseModel):
    """Semantic relationship between one stored report title and its successor.

    The selected host executor or the current manual Agent supplies this
    judgment. Runtime code checks that the named titles are the exact rendered
    titles and that the account identity matches. A caller-supplied flag or a
    hash of this object is not an unforgeable semantic oracle: the hash only
    shows those bytes were the ones judged. Same account, keyword overlap, and
    a generated topic id do not authorize a different topic.
    """

    relationship: Literal["same_topic", "unrelated", "unclear"]
    predecessor_title: str = Field(min_length=1)
    successor_title: str = Field(min_length=1)
    basis: str = Field(min_length=8, max_length=1000)

    model_config = {"extra": "forbid"}

    @field_validator("predecessor_title", "successor_title", "basis")
    @classmethod
    def single_line_judgment(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("report topic judgment fields must be nonempty single lines")
        return value.strip()

    def authorizes(self, predecessor: "SourceReport", successor: "SourceReport") -> bool:
        """True only for an explicit same-topic judgment of these exact titles."""

        return (
            self.relationship == "same_topic"
            and self.predecessor_title == predecessor.render_title()
            and self.successor_title == successor.render_title()
            and successor.same_account_source(predecessor)
        )


class SourceReport(BaseModel):
    """Runtime-bound attribution retained with current knowledge.

    The source identity is private revalidation metadata. ``period`` is a native
    source-session timestamp, not the exact time of each cited utterance.
    The readable statement
    retains speaker, period and source scope even in ordinary compact retrieval.
    A missing native date is explicitly unknown, not the capture time.
    ``topic_title`` is an optional content title. Absent, the row keeps the
    legacy speaker/period title. It is not derived from a hash.
    """

    speaker: Literal["user", "assistant"]
    period: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    exchange_indexes: list[int] = Field(min_length=1)
    text: str = Field(min_length=1)
    topic_title: str | None = None

    model_config = {"extra": "forbid"}

    @model_serializer(mode="wrap")
    def _omit_absent_topic(self, handler):
        payload = handler(self)
        if isinstance(payload, dict) and payload.get("topic_title") is None:
            payload.pop("topic_title", None)
        return payload

    @field_validator("period", "session_id", "source_id", "source_revision", "text")
    @classmethod
    def single_line(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("source-report fields must be nonempty single lines")
        return value.strip()

    @field_validator("topic_title")
    @classmethod
    def topic_line(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("source-report fields must be nonempty single lines")
        return value.strip()

    @field_validator("exchange_indexes")
    @classmethod
    def valid_exchanges(cls, value: list[int]) -> list[int]:
        if any(index < 1 for index in value) or len(value) != len(set(value)):
            raise ValueError("source-report exchanges must be distinct positive indexes")
        return sorted(value)

    def render_statement(self) -> str:
        """Keep the stored representation stable for source and version checks."""
        return (
            f"Source-scoped report — {self.speaker}, source-session timestamp: {self.period}, "
            f"in that session's cited exchanges: {self.text} "
            "[Reports that speaker's account only; not independently established "
            "current fact or user approval.]"
        )

    def readable_statement(self) -> str:
        """Present the complete account with a concise, explicit source boundary.

        The native session timestamp is not silently shortened to a claim date.
        The account itself, including all conditions, stays byte-for-byte intact.
        """
        if any("\u3400" <= char <= "\u9fff" for char in self.text):
            speaker = "用户" if self.speaker == "user" else "助手"
            return (
                f"据 {self.period} 会话中的{speaker}记述"
                f"（未独立核实，不能据此认定当前事实或用户授权）：{self.text}"
            )
        return (
            f"{self.speaker.capitalize()} account from session {self.period} "
            f"(not independently established as current fact or user approval): {self.text}"
        )

    def legacy_title(self) -> str:
        return f"Source report — {self.speaker} account (source-session timestamp: {self.period})"

    def render_title(self) -> str:
        if self.topic_title is not None:
            return self.topic_title
        return self.legacy_title()

    def same_account_source(self, other: SourceReport) -> bool:
        """Compare speaker, period, session and source only.

        A later revision of this account still has to name the same topic.
        Account equality alone does not authorize replacing another topic.
        """
        return (
            self.speaker == other.speaker
            and self.period == other.period
            and self.session_id == other.session_id
            and self.source_id == other.source_id
        )

    def same_report_topic(self, other: SourceReport) -> bool:
        return self.topic_title == other.topic_title

    def allows_same_topic_revision(self, other: SourceReport) -> bool:
        return self.same_account_source(other) and self.same_report_topic(other)

    def with_topic_revision(
        self,
        proposed_title: str,
        judgment: ReportTopicJudgment | None = None,
        *,
        predecessor: "SourceReport | None" = None,
    ) -> "SourceReport":
        """Accept a title when it is unchanged, filled, or explicitly the same topic.

        A differing stored title needs ``judgment`` naming both rendered titles.
        Without that judgment this stays the strict verified-account rule.
        """

        if "\n" in proposed_title or "\r" in proposed_title:
            raise ValueError("source-report topic title must be a nonempty single line")
        proposed = proposed_title.strip()
        if not proposed:
            raise ValueError("source-report topic title must be a nonempty single line")
        if proposed == self.render_title():
            return self
        successor = self.model_copy(update={
            "topic_title": None if proposed == self.legacy_title() else proposed,
        })
        if (
            predecessor is not None
            and judgment is not None
            and judgment.authorizes(predecessor, successor)
        ):
            if self.topic_title is not None and self.render_title() not in {
                predecessor.render_title(), successor.render_title(),
            }:
                raise ValueError("source-report topic does not match its verified account")
            return successor
        return self.with_accepted_topic(proposed)

    def retains_verified_account(self, written: SourceReport) -> bool:
        """Account, revision, exchanges and text match.

        A missing topic may be filled by the accepted output title. An existing
        topic cannot be swapped or cleared at commit.
        """
        if self.topic_title is not None and written.topic_title != self.topic_title:
            return False
        return self.model_copy(update={"topic_title": written.topic_title}) == written

    def with_accepted_topic(self, proposed_title: str) -> SourceReport:
        """Use an explicit content title. The legacy title does not invent one."""
        if "\n" in proposed_title or "\r" in proposed_title:
            raise ValueError("source-report topic title must be a nonempty single line")
        proposed = proposed_title.strip()
        if not proposed:
            raise ValueError("source-report topic title must be a nonempty single line")
        if proposed == self.legacy_title() or proposed == self.render_title():
            return self
        if self.topic_title is not None:
            raise ValueError("source-report topic does not match its verified account")
        return self.model_copy(update={"topic_title": proposed})


def report_revision_allowed(
    successor: "SourceReport",
    predecessor: "SourceReport",
    judgment: ReportTopicJudgment | None,
    *,
    disposition: str,
) -> bool:
    """Account identity is required and is not itself a topic relationship.

    Equal topic strings, including two legacy generic titles, do not authorize
    a different cited body. Comparison uses the stored cited text. A rendered
    statement that merely quotes that text is a different body, not a wrapper
    to unwrap. A body or title change needs ``judgment`` naming both exact
    rendered titles. Same account alone is not that judgment.
    """

    if not successor.same_account_source(predecessor):
        return False
    same_topic = successor.same_report_topic(predecessor)
    same_body = successor.text == predecessor.text
    if same_topic and same_body:
        return True
    if disposition == "confirm" and successor.topic_title is None and same_body:
        return True
    return judgment is not None and judgment.authorizes(predecessor, successor)


class ReportQualifier(BaseModel):
    """One qualifier the verifier says belongs to a report output.

    Unsupported support and independently useful qualifiers must remain in an
    output body. A temporary supported qualifier may be omitted. This object
    does not upgrade the original point's support.
    """

    text: str = Field(min_length=1)
    source_support: Literal["supported", "partial", "unsupported", "contradicted", "unclear"]
    source_use: Literal[
        "standing_decision",
        "reusable_knowledge",
        "explicit_undecided",
        "task_context",
        "unclear",
    ] = "unclear"
    independently_useful: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("text")
    @classmethod
    def exact_line(cls, value: str) -> str:
        if value == "" or "\n" in value or "\r" in value:
            raise ValueError("report qualifier text must be a nonempty single line")
        return value


class ReportOmission(BaseModel):
    """Original characters absent from every output.

    Only temporary context may be listed. A topic, an unsupported qualifier,
    or an independently useful qualifier cannot be omitted.
    """

    text: str = Field(min_length=1)
    classification: Literal["temporary_context"]

    model_config = {"extra": "forbid"}

    @field_validator("text")
    @classmethod
    def exact_span(cls, value: str) -> str:
        if value == "" or "\n" in value or "\r" in value:
            raise ValueError("report omission must be a nonempty single line")
        return value


class ReportScopeSegment(BaseModel):
    """Verifier partition of one output's final title, body, and attribution."""

    text: str = Field(min_length=1)
    source_use: Literal[
        "standing_decision",
        "reusable_knowledge",
        "explicit_undecided",
        "task_context",
        "unclear",
    ]
    future_scope: Literal["durable", "session_only", "unclear"]
    standalone: bool = True
    content_role: Literal["claim", "qualifier", "temporary_context", "unclear"] = "claim"
    source_support: Literal["supported", "partial", "unsupported", "contradicted", "unclear"] = "supported"

    model_config = {"extra": "forbid"}


class ReportOutputProposal(BaseModel):
    """One independent report proposed from a single legacy account.

    Account identity is copied from the predecessor at bind time. This proposal
    is not admission. A v7 literal-edit proof cannot supply it.
    """

    topic_title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    exchange_indexes: list[int] = Field(min_length=1)
    source_support: Literal["supported", "partial", "unsupported", "contradicted", "unclear"]
    source_use: Literal[
        "standing_decision",
        "reusable_knowledge",
        "explicit_undecided",
        "task_context",
        "unclear",
    ] = "standing_decision"
    future_scope: Literal["durable", "session_only", "unclear"] = "durable"
    qualifiers: list[ReportQualifier] = Field(default_factory=list)
    topic_judgment: ReportTopicJudgment
    scope_segments: list[ReportScopeSegment] = Field(min_length=1)

    model_config = {"extra": "forbid"}

    @field_validator("topic_title", "text")
    @classmethod
    def exact_output_line(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("report output fields must be nonempty single lines")
        return value.strip()

    @field_validator("exchange_indexes")
    @classmethod
    def distinct_exchanges(cls, value: list[int]) -> list[int]:
        if any(index < 1 for index in value) or len(value) != len(set(value)):
            raise ValueError("report output exchanges must be distinct positive indexes")
        return sorted(value)


_DURABLE_REPORT_USES = frozenset({
    "standing_decision",
    "reusable_knowledge",
    "explicit_undecided",
})


def source_report_snapshot(report: "SourceReport | None") -> dict | None:
    """Canonical report bytes for discovery, final proof, and precommit.

    The raw cited text is part of the identity. A rendered title or statement
    is not a substitute, and dropping the text makes those hashes disagree.
    """

    if report is None:
        return None
    return report.model_dump(mode="json")


def report_output_scope_text(report: "SourceReport") -> str:
    """Bind final verification to the exact title, rendered body, and attribution."""

    exchanges = ",".join(str(index) for index in report.exchange_indexes)
    attribution = (
        f"{report.speaker}|{report.period}|{report.session_id}|{report.source_id}|"
        f"{report.source_revision}|{exchanges}"
    )
    return report.render_title() + "\n" + report.render_statement() + "\n" + attribution


def _texts_tile(original: str, pieces: list[str]) -> bool:
    """True when pieces cover the original without overlap or remainder."""

    unused = list(pieces)
    cursor = 0
    while cursor < len(original):
        matches = [
            (len(piece), index, piece)
            for index, piece in enumerate(unused)
            if piece and original.startswith(piece, cursor)
        ]
        if not matches:
            return False
        _length, index, piece = max(matches)
        unused.pop(index)
        cursor += len(piece)
    return cursor == len(original) and not unused


def _qualifier_must_remain(qualifier: ReportQualifier) -> bool:
    if qualifier.source_support != "supported":
        return True
    if qualifier.independently_useful:
        return True
    return qualifier.source_use in _DURABLE_REPORT_USES


def _project_report_omissions(original: str, omissions: list["ReportOmission"]) -> str:
    """Delete unique exact temporary spans, without inventing output text."""
    if not omissions:
        raise ValueError("noncontiguous report output requires explicit temporary omissions")
    ranges: list[tuple[int, int]] = []
    for omission in omissions:
        start = original.find(omission.text)
        if start < 0:
            raise ValueError("report omission is not an exact original span")
        if original.find(omission.text, start + 1) >= 0:
            raise ValueError("report omission has ambiguous original occurrences")
        ranges.append((start, start + len(omission.text)))
    ranges.sort()
    cursor = 0
    retained: list[str] = []
    for start, end in ranges:
        if start < cursor:
            raise ValueError("report omission spans overlap")
        retained.append(original[cursor:start])
        cursor = end
    retained.append(original[cursor:])
    return "".join(retained)


def bind_report_split(
    predecessor: "SourceReport",
    *,
    original_support: str,
    outputs: list[ReportOutputProposal],
    omissions: list[ReportOmission] | None = None,
    mode: str = "literal_projection",
) -> list["SourceReport"]:
    """Bind one legacy account to one or more independent retained reports.

    The predecessor is replaced once. Partial original support stays partial.
    Each output keeps the predecessor account and a typed cited body. Output
    texts plus temporary omissions must tile the original cited text in the
    default literal mode. Trusted source-backed revision binds exactly one
    same-topic output; independent source and whole-update proofs remain
    required by the shared write owner. A
    noncontiguous output must equal the exact original-order remainder after
    deleting uniquely located nonoverlapping temporary omissions. A v7
    literal proof is not an input to this function.
    """

    if mode not in {"literal_projection", "source_backed_same_topic_revision"}:
        raise ValueError("source_report_revision_mode_invalid")
    literal = mode == "literal_projection"
    if literal and original_support != "supported":
        raise ValueError("partial source support cannot be upgraded into independent reports")
    if not outputs:
        raise ValueError("source-report refinement requires at least one retained account item")
    omissions = list(omissions or [])
    if not literal and (len(outputs) != 1 or omissions):
        raise ValueError("source-backed report revision requires one output and no literal omissions")
    if any(item.classification != "temporary_context" for item in omissions):
        raise ValueError("only temporary context may be omitted from a report split")
    projected = literal and any(output.text not in predecessor.text for output in outputs)
    if projected and _project_report_omissions(predecessor.text, omissions) != \
            "".join(output.text for output in outputs):
        raise ValueError("report outputs do not equal the exact temporary-omission projection")
    bound: list[SourceReport] = []
    seen_titles: set[str] = set()
    covered_exchanges: set[int] = set()
    for output in outputs:
        if output.source_support != "supported":
            raise ValueError("one report output is not source-supported; the whole split stays unchanged")
        if output.future_scope != "durable" or output.source_use not in _DURABLE_REPORT_USES:
            raise ValueError("one report output has no durable use; the whole split stays unchanged")
        if not set(output.exchange_indexes).issubset(predecessor.exchange_indexes):
            raise ValueError("report output exchanges are not in the predecessor account")
        covered_exchanges.update(output.exchange_indexes)
        written = predecessor.model_copy(update={
            "text": output.text,
            "topic_title": output.topic_title,
            "exchange_indexes": list(output.exchange_indexes),
        })
        if literal and not projected and written.text not in predecessor.text:
            raise ValueError("report output text is not a literal cited span of the predecessor")
        if not output.topic_judgment.authorizes(predecessor, written):
            raise ValueError("report output topic judgment does not authorize this predecessor")
        if written.render_title() in seen_titles:
            raise ValueError("report split outputs must have distinct topic titles")
        seen_titles.add(written.render_title())
        for qualifier in output.qualifiers:
            if qualifier.text not in written.text:
                raise ValueError("report output dropped a qualifier from its own body")
        scope = "".join(segment.text for segment in output.scope_segments)
        if scope != report_output_scope_text(written):
            raise ValueError("report output verification does not cover its title, body, and attribution")
        bound.append(written)
    if covered_exchanges != set(predecessor.exchange_indexes):
        raise ValueError("report split dropped a predecessor exchange")
    for output in outputs:
        for qualifier in output.qualifiers:
            if not _qualifier_must_remain(qualifier):
                continue
            if not any(qualifier.text in written.text for written in bound):
                raise ValueError("report split dropped an unsupported or independently useful qualifier")
    pieces = [written.text for written in bound] + [item.text for item in omissions]
    if literal and not projected and not _texts_tile(predecessor.text, pieces):
        raise ValueError("report split discarded original topic text")
    return bound


def report_preservation_mode(report_split: Mapping[str, Any] | None) -> Literal["literal_projection", "full_revision"]:
    """Resolve the bound report plan, retaining the legacy non-split contract."""
    if report_split is None:
        return "full_revision"
    mode = report_split.get("mode", "literal_projection")
    if mode == "source_backed_same_topic_revision":
        return "full_revision"
    if mode != "literal_projection":
        raise ValueError("source_report_revision_mode_invalid")
    return "literal_projection"


def account_write_allowed(
    before: "SourceReport",
    written: "SourceReport",
    judgment: ReportTopicJudgment | None,
    predecessors: list["SourceReport"],
) -> bool:
    """Keep the verified account. A judged same-topic retitle may change only that title."""

    if before.retains_verified_account(written):
        return True
    if judgment is None or not predecessors:
        return False
    if before.model_copy(update={"topic_title": written.topic_title}) != written:
        return False
    return all(
        judgment.authorizes(predecessor, written)
        and before.render_title() in {predecessor.render_title(), written.render_title()}
        for predecessor in predecessors
    )


def report_preservation_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def report_body_update_required(targets: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]]) -> bool:
    originals = [SourceReport.model_validate(row["source_report"]) for row in targets if row.get("source_report")]
    if not originals:
        return False
    return (len(originals) != 1 or len(items) != 1 or not items[0].get("source_report")
        or SourceReport.model_validate(items[0]["source_report"]).text != originals[0].text)


def bind_report_preservation_inventory(
    *, owner: str, target: Mapping[str, Any], items: Sequence[Mapping[str, Any]],
    omissions: Sequence[Mapping[str, Any]], classification: Mapping[str, Any],
    mode: Literal["literal_projection", "full_revision"] = "literal_projection",
) -> dict[str, Any]:
    """Freeze complete ORIGINAL classification separately from final-output proof.

    Only offsets, classes and hashes are added. The exact body already exists
    in the bound predecessor; no selected output can redefine this inventory.
    """
    report = SourceReport.model_validate(target.get("source_report"))
    if mode not in {"literal_projection", "full_revision"}:
        raise ValueError("report_original_inventory_mode_invalid")
    segments, claims = classification.get("scope_segments"), classification.get("claim_units")
    if (not owner or not target.get("id") or not target.get("version") or not isinstance(segments, list)
            or not segments or not isinstance(claims, list) or not claims
            or "".join(str(row.get("text") or "") for row in segments) != report.text):
        raise ValueError("report_original_inventory_incomplete")
    parts, cursor = [], 0
    for segment in segments:
        text = str(segment["text"])
        part = {key: segment[key] for key in (
            "source_use", "future_scope", "standalone", "content_role", "source_support")}
        parts.append({**part, "start": cursor, "end": cursor + len(text),
                      "sha256": hashlib.sha256(text.encode()).hexdigest()})
        cursor += len(text)
    units = []
    frozen_claims = []
    covered: set[int] = set()
    for index, claim in enumerate(claims):
        first, end = claim.get("first_segment"), claim.get("end_segment_exclusive")
        if type(first) is not int or type(end) is not int or not 0 <= first < end <= len(parts):
            raise ValueError("report_original_inventory_range_invalid")
        frozen = {key: claim[key] for key in ("first_segment", "end_segment_exclusive", "standalone",
            "source_support", "source_use", "future_scope")}
        frozen_claims.append(frozen)
        covered.update(range(first, end))
        units.append({"kind": "claim_unit", "original_index": index, **frozen,
            "start": parts[first]["start"], "end": parts[end - 1]["end"]})
    if any(index not in covered and part["content_role"] == "claim" for index, part in enumerate(parts)):
        raise ValueError("report_original_claim_inventory_incomplete")
    for index, part in enumerate(parts):
        units.append({"kind": "segment", "original_index": index, **part})
    for unit in units:
        unit["sha256"] = hashlib.sha256(report.text[unit["start"]:unit["end"]].encode()).hexdigest()
    written = [SourceReport.model_validate(item.get("source_report")) for item in items]
    if any(not report.same_account_source(item) for item in written):
        raise ValueError("report_original_inventory_account_changed")
    bodies = [item.text for item in written]
    removed = []
    for omission in omissions if mode == "literal_projection" else []:
        text = str(omission.get("text") or "")
        start = report.text.find(text) if text else -1
        if start < 0 or report.text.find(text, start + 1) >= 0:
            raise ValueError("report_original_omission_range_invalid")
        end = start + len(text)
        removed.append({"start": start, "end": end, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "affected_units": [index for index, unit in enumerate(units)
                if unit["start"] < end and start < unit["end"]]})
    if mode == "full_revision":
        if omissions:
            raise ValueError("report_revision_cannot_borrow_literal_omissions")
        joined = "".join(bodies)
        offsets, cursor = [], 0
        for body in bodies:
            offsets.append((cursor, cursor + len(body)))
            cursor += len(body)
        for operation, start, end, new_start, new_end in SequenceMatcher(
                None, report.text, joined, autojunk=False).get_opcodes():
            if operation not in {"replace", "delete"}:
                continue
            ranges = [{"successor_index": index, "char_start": max(new_start, first) - first,
                "char_end": min(new_end, last) - first,
                "sha256": hashlib.sha256(body[max(new_start, first) - first:min(new_end, last) - first].encode()).hexdigest()}
                for index, (body, (first, last)) in enumerate(zip(bodies, offsets))
                if first < new_end and new_start < last]
            removed.append({"start": start, "end": end,
                "sha256": hashlib.sha256(report.text[start:end].encode()).hexdigest(),
                "affected_units": [index for index, unit in enumerate(units)
                    if unit["start"] < end and start < unit["end"]],
                "operation": operation, "successor_ranges": ranges})
    omitted_texts = [report.text[row["start"]:row["end"]] for row in removed]
    if mode == "literal_projection" and (any(body not in report.text for body in bodies)
            and _project_report_omissions(report.text, [ReportOmission(text=text,
                classification="temporary_context") for text in omitted_texts]) != "".join(bodies)):
        raise ValueError("report_original_omission_inventory_incomplete")
    if mode == "literal_projection" and not any(body not in report.text for body in bodies) and not _texts_tile(report.text, bodies + omitted_texts):
        raise ValueError("report_original_omission_inventory_incomplete")
    return {"contract": "report-original-preservation-v1", "mode": mode, "owner_candidate_id": owner,
        "predecessor_id": target["id"], "predecessor_version": target["version"],
        "report_sha256": report_preservation_digest(report.model_dump(mode="json")),
        "body_sha256": hashlib.sha256(report.text.encode()).hexdigest(),
        "segments": parts, "claim_units": frozen_claims, "units": units, "omissions": removed,
        "successor_sha256": [report_preservation_digest({key: item.get(key)
            for key in ("title", "statement", "source_report")}) for item in items]}


def validate_report_preservation_inventory(
    inventory: Mapping[str, Any], *, owner: str, targets: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]], expected_mode: str | None = None,
) -> None:
    """Rebuild all indexed bindings against the actual canonical endpoints."""
    if inventory.get("contract") == "report-original-preservation-group-v1":
        originals = inventory.get("predecessor_inventories")
        if not isinstance(originals, list) or len(originals) < 2 or len(originals) != len(targets):
            raise ValueError("report_original_inventory_predecessors_incomplete")
        expected = bind_report_preservation_inventories(owner=owner, targets=targets, items=items,
            inventories=originals, expected_mode=expected_mode)
        if dict(inventory) != expected:
            raise ValueError("report_original_inventory_binding_changed")
        return
    if len(targets) != 1 or not targets[0].get("source_report"):
        raise ValueError("report_original_inventory_predecessors_incomplete")
    mode = inventory.get("mode")
    if mode not in {"literal_projection", "full_revision"} or (expected_mode is not None and mode != expected_mode):
        raise ValueError("report_original_inventory_mode_changed")
    report = SourceReport.model_validate(targets[0]["source_report"])
    classification = {"scope_segments": [{**row, "text": report.text[row["start"]:row["end"]]}
        for row in inventory.get("segments") or []], "claim_units": inventory.get("claim_units")}
    expected = bind_report_preservation_inventory(owner=owner, target=targets[0], items=items,
        omissions=[{"text": report.text[row["start"]:row["end"]]} for row in inventory.get("omissions") or []]
            if mode == "literal_projection" else [], classification=classification, mode=mode)
    if dict(inventory) != expected:
        raise ValueError("report_original_inventory_binding_changed")


def _aggregate_report_preservation_inventories(
    *, owner: str, inventories: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Flatten complete inventories without merging their original meanings."""
    if len(inventories) < 2:
        raise ValueError("report_original_inventory_predecessors_incomplete")
    originals = deepcopy([dict(row) for row in inventories])
    mode = originals[0].get("mode")
    if mode not in {"literal_projection", "full_revision"}:
        raise ValueError("report_original_inventory_mode_changed")
    identities = []
    units: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    for predecessor_index, original in enumerate(originals):
        identity, version = original.get("predecessor_id"), original.get("predecessor_version")
        if (original.get("contract") != "report-original-preservation-v1"
                or original.get("owner_candidate_id") != owner or not owner or not identity or not version
                or not isinstance(original.get("units"), list) or not original["units"]
                or not isinstance(original.get("omissions"), list)):
            raise ValueError("report_original_inventory_predecessors_incomplete")
        if original.get("mode") != mode:
            raise ValueError("report_original_inventory_mode_changed")
        identities.append(identity)
        binding = {"predecessor_index": predecessor_index,
            "predecessor_id": identity, "predecessor_version": version}
        offset = len(units)
        units.extend({**unit, **binding, "original_unit_index": index}
            for index, unit in enumerate(original["units"]))
        for index, omission in enumerate(original["omissions"]):
            affected = omission.get("affected_units")
            if (not isinstance(affected, list) or any(type(value) is not int
                    or not 0 <= value < len(original["units"]) for value in affected)):
                raise ValueError("report_original_inventory_binding_changed")
            omissions.append({**omission, **binding, "original_omission_index": index,
                "affected_units": [offset + value for value in affected]})
    if len(identities) != len(set(identities)):
        raise ValueError("report_original_inventory_predecessors_incomplete")
    return {"contract": "report-original-preservation-group-v1", "mode": mode,
        "owner_candidate_id": owner, "predecessor_inventories": originals,
        "units": units, "omissions": omissions}


def bind_report_preservation_inventories(
    *, owner: str, targets: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]],
    inventories: Sequence[Mapping[str, Any]], expected_mode: str | None = None,
) -> dict[str, Any]:
    """Bind every same-account predecessor to its independently complete inventory.

    Call ``bind_report_preservation_inventory`` once per target, against the
    same final ``items``, before calling this helper. Target order is retained;
    missing, duplicate, nested or foreign inventories never authorize a group.
    The single-target result remains byte-for-byte the original v1 format.
    Flattened units/omissions use the existing final-vote transport, while each
    original inventory remains available for independent revalidation.
    """
    if not targets or len(targets) != len(inventories) or not items:
        raise ValueError("report_original_inventory_predecessors_incomplete")
    originals = [SourceReport.model_validate(target.get("source_report")) for target in targets]
    if any(not originals[0].same_account_source(report) for report in originals[1:]):
        raise ValueError("report_original_inventory_account_changed")
    for target, inventory in zip(targets, inventories):
        if inventory.get("contract") != "report-original-preservation-v1":
            raise ValueError("report_original_inventory_predecessors_incomplete")
        validate_report_preservation_inventory(inventory, owner=owner, targets=[target],
            items=items, expected_mode=expected_mode)
    if len(targets) == 1:
        return deepcopy(dict(inventories[0]))
    return _aggregate_report_preservation_inventories(owner=owner, inventories=inventories)


def report_preservation_block(inventory: Mapping[str, Any], proof: Mapping[str, Any] | None,
                              items: Sequence[Mapping[str, Any]]) -> str | None:
    """Require the independent final vote for every original unit and omission."""
    grouped = inventory.get("contract") == "report-original-preservation-group-v1"
    if grouped:
        try:
            originals = inventory.get("predecessor_inventories")
            if not isinstance(originals, list):
                return "final_report_original_inventory_incomplete"
            expected_group = _aggregate_report_preservation_inventories(
                owner=str(inventory.get("owner_candidate_id") or ""), inventories=originals)
            if dict(inventory) != expected_group:
                return "final_report_original_inventory_changed"
        except (KeyError, TypeError, ValueError):
            return "final_report_original_inventory_incomplete"
    if (not proof or proof.get("inventory_complete") is not True
            or proof.get("inventory_sha256") != report_preservation_digest(dict(inventory))
            or proof.get("owner_candidate_id") != inventory.get("owner_candidate_id")):
        return "final_report_original_inventory_unproved"
    units, omissions = proof.get("units") or [], proof.get("omissions") or []
    if ([row.get("unit_index") for row in units] != list(range(len(inventory["units"])))
            or [row.get("omission_index") for row in omissions] != list(range(len(inventory["omissions"])))):
        return "final_report_original_inventory_incomplete"
    for expected, row in zip(inventory["units"], units):
        if row.get("unit_sha256") != report_preservation_digest(expected):
            return "final_report_original_unit_changed"
        if row.get("verdict") not in {"preserved", "disposable"}:
            return "final_report_original_meaning_lost"
        if row.get("verdict") == "disposable" and (expected.get("future_scope") != "session_only"
                or expected.get("source_use") != "task_context"):
            return "final_report_original_durable_unit_discarded"
        spans = row.get("successor_spans") or []
        if (row.get("verdict") == "preserved") != bool(spans):
            return "final_report_original_unit_unbound"
        for span in spans:
            index, start, end = (span.get(key) for key in ("successor_index", "char_start", "char_end"))
            if any(type(value) is not int for value in (index, start, end)) or not 0 <= index < len(items):
                return "final_report_original_unit_unbound"
            if not items[index].get("source_report"):
                return "final_report_original_unit_unbound"
            text = SourceReport.model_validate(items[index]["source_report"]).text
            if not 0 <= start < end <= len(text) or span.get("text_sha256") != hashlib.sha256(text[start:end].encode()).hexdigest():
                return "final_report_original_unit_unbound"
    for expected, row in zip(inventory["omissions"], omissions):
        if (row.get("omission_sha256") != report_preservation_digest(expected)
                or row.get("affected_units") != expected["affected_units"]
                or any(type(index) is not int for index in row.get("affected_units") or [])
                or any(row.get(key) not in {"preserved", "not_applicable"}
                       for key in ("claim", "evidence", "causality", "boundary", "permission", "scope"))):
            return "final_report_omission_meaning_unproved"
    if grouped:
        # Each flattened vote names its own predecessor and unit through the
        # bound hash. Reindex that same semantic vote for the original v1 gate;
        # no positive vote from a different predecessor is copied or inferred.
        unit_offset, omission_offset = 0, 0
        for original in inventory["predecessor_inventories"]:
            original_units = []
            for index, bound in enumerate(original["units"]):
                row = units[unit_offset + index]
                original_units.append({**row, "unit_index": index,
                    "unit_sha256": report_preservation_digest(bound)})
            original_omissions = []
            for index, bound in enumerate(original["omissions"]):
                row = omissions[omission_offset + index]
                original_omissions.append({**row, "omission_index": index,
                    "omission_sha256": report_preservation_digest(bound),
                    "affected_units": bound["affected_units"]})
            blocked = report_preservation_block(original, {
                "owner_candidate_id": proof["owner_candidate_id"],
                "inventory_complete": proof["inventory_complete"],
                "inventory_sha256": report_preservation_digest(original),
                "units": original_units, "omissions": original_omissions,
            }, items)
            if blocked is not None:
                return blocked
            unit_offset += len(original["units"])
            omission_offset += len(original["omissions"])
    return None


def readable_knowledge_statement(
    statement: str, source_report: SourceReport | Mapping[str, Any] | None = None,
) -> str:
    """Only project typed, exactly bound reports; never strip arbitrary prose."""
    if source_report is None:
        return statement
    try:
        report = SourceReport.model_validate(source_report)
    except (TypeError, ValueError):
        return statement
    if statement != report.render_statement():
        return statement
    return report.readable_statement()


__all__ = [
    "ReportOmission",
    "ReportOutputProposal",
    "ReportQualifier",
    "ReportScopeSegment",
    "ReportTopicJudgment",
    "SourceReport",
    "account_write_allowed",
    "bind_report_preservation_inventories",
    "bind_report_split",
    "report_output_scope_text",
    "readable_knowledge_statement",
    "report_revision_allowed",
    "source_report_snapshot",
]
