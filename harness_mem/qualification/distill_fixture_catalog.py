"""Versioned, synthetic fixtures for distill acceptance qualification."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _turn(index: int, user: str, assistant: str) -> str:
    return (
        f"## Turn {index * 2 - 1} (user-{index})\n\nUser: {user}\n\n"
        f"## Turn {index * 2} (assistant-{index})\n\nAssistant: {assistant}\n\n"
    )


def _long_fixture() -> str:
    parts = ["# F5 long indexed session\n\n"]
    for index in range(1, 61):
        user = f"Inspect routine item {index} and report the current session result."
        assistant = f"Routine item {index} was inspected for this session only."
        if index == 1:
            user = "Prefer compact responses, but never hide required evidence."
            assistant = "The opening preference was acknowledged. F5-BEGIN-ANCHOR"
        elif index == 30:
            user = "Migration v9.1.0 failed with error F5-MIDDLE-ERROR; preserve rollback proof."
            assistant = "Rollback preserved canonical storage. F5-MIDDLE-PROOF"
        elif index == 60:
            user = "Finish the audit and preserve any remaining handoff."
            assistant = "Security review remains unfinished. F5-END-ANCHOR"
        parts.append(_turn(index, user, assistant))
    return "".join(parts)


def _raw_fixture() -> str:
    filler = "raw-audit-padding " * 1800
    return (
        "# F6 raw lossless session\n\n"
        + _turn(
            1,
            "Run exact command `harness-mem doctor -p fixture-six`.",
            "Version v6.4.2 returned error HM-F6-409 before recovery.",
        )
        + filler
        + "\n\nF6-CROSS-CHUNK-PROOF\n\n"
        + _turn(
            2,
            "Preserve the exact command, version, and error for raw audit.",
            "The raw audit retained every byte and the recovery remained session-only.",
        )
    )


DISTILL_FIXTURES: dict[str, dict[str, Any]] = {
    "F1": {
        "name": "noise",
        "transcript": "# F1 noise\n\n" + _turn(1, "Say hello once.", "Hello."),
        "expected": {
            "candidate_count": 0,
            "promotion_decision": "no_promotion",
            "unfinished": False,
        },
    },
    "F2": {
        "name": "preference",
        "transcript": "# F2 preference\n\n"
        + _turn(
            1,
            "I prefer distillation to use much less time and fewer tokens while keeping the same result quality.",
            "I will preserve that explicit performance preference.",
        ),
        "expected": {
            "candidate_count": 1,
            "promotion_decision": "promote",
            "candidate_basis": "user_statement",
            "required_term_groups": [
                ["time", "latency", "时间", "延迟", "耗时"],
                ["token", "令牌"],
                ["quality", "质量"],
            ],
            "unfinished": False,
        },
    },
    "F3": {
        "name": "partial",
        "transcript": "# F3 partial\n\n"
        + _turn(
            1,
            "I prefer much lower distill latency and token use without reducing result quality.",
            "That performance preference is explicit and durable.",
        )
        + _turn(
            2,
            "The older truncate-first approach is superseded. Measure one fixed model sample next.",
            "The preference is answered, but the fixed model measurement remains unfinished as a handoff.",
        ),
        "expected": {
            "candidate_count": 1,
            "promotion_decision": "partial",
            "candidate_basis": "user_statement",
            "required_term_groups": [
                ["latency", "time", "延迟", "时间"],
                ["token", "令牌"],
                ["quality", "质量"],
            ],
            "unfinished": True,
        },
    },
    "F4": {
        "name": "revision",
        "transcript": "# F4 revision one\n\n"
        + _turn(1, "Record revision one.", "Revision one completed."),
        "appended_transcript": _turn(
            2,
            "Record a later revision independently.",
            "Revision two completed after revision one.",
        ),
        "expected": {"immutable_notes": 2, "latest_revision": 2},
    },
    "F5": {
        "name": "long",
        "transcript": _long_fixture(),
        "expected": {
            "exchange_count": 60,
            "anchors": ["F5-BEGIN-ANCHOR", "F5-MIDDLE-PROOF", "F5-END-ANCHOR"],
            "anchor_indexes": [1, 30, 60],
        },
    },
    "F6": {
        "name": "raw",
        "transcript": _raw_fixture(),
        "expected": {
            "proofs": [
                "harness-mem doctor -p fixture-six",
                "v6.4.2",
                "HM-F6-409",
                "F6-CROSS-CHUNK-PROOF",
            ]
        },
    },
    "F7": {
        "name": "legacy",
        "transcript": "Legacy observation without a native transcript revision.",
        "expected": {"coverage": "legacy_partial", "truth_count": 0},
    },
    "F8": {
        "name": "multi-promotion-shadow",
        "expected": {
            "promotion_point_count": 5,
            "forbidden_write_ids": ["f8-no-write", "f8-handoff"],
        },
        "shadow": {
            "fixture_id": "F8",
            "current_truth": [
                {"id": "truth-f8-sync", "statement": "The worker performs a sync."},
                {"id": "truth-f8-response", "statement": "The API returns request_id."},
            ],
            "promotion_points": [
                {
                    "id": "f8-add",
                    "answer_status": "ANSWERED",
                    "title": "Provider receipt binding",
                    "statement": "A completed autonomous distill receipt binds the provider result to its distill job.",
                    "long_term_utility": True,
                    "relationship": "new",
                },
                {
                    "id": "f8-refine",
                    "answer_status": "ANSWERED",
                    "title": "Worker sync cadence",
                    "statement": "The worker syncs the provider receipt before a terminal job transition.",
                    "long_term_utility": True,
                    "relationship": "refines",
                    "matched_truth_id": "truth-f8-sync",
                },
                {
                    "id": "f8-confirm",
                    "answer_status": "ANSWERED",
                    "title": "API response identity",
                    "statement": "The API returns request_id.",
                    "long_term_utility": True,
                    "relationship": "equivalent",
                    "matched_truth_id": "truth-f8-response",
                },
                {
                    "id": "f8-no-write",
                    "answer_status": "ANSWERED",
                    "title": "Current audit request",
                    "statement": "Show the current archive audit list.",
                    "long_term_utility": False,
                    "relationship": "new",
                },
                {
                    "id": "f8-handoff",
                    "answer_status": "PARTIAL",
                    "title": "Remaining rollout",
                    "statement": "Run the production rollout after the final result contract is green.",
                    "long_term_utility": False,
                    "route": "handoff",
                },
            ],
            "forbidden_write_ids": ["f8-no-write", "f8-handoff"],
        },
    },
    "F9": {
        "name": "request-vs-preference-shadow",
        "expected": {
            "forbidden_write_ids": ["f9-list-now"],
            "durable_preference_ids": ["f9-future-audit-preference"],
        },
        "shadow": {
            "fixture_id": "F9",
            "current_truth": [],
            "promotion_points": [
                {
                    "id": "f9-list-now",
                    "answer_status": "ANSWERED",
                    "title": "Current list request",
                    "statement": "List every stored long-term memory now.",
                    "long_term_utility": False,
                },
                {
                    "id": "f9-future-audit-preference",
                    "answer_status": "ANSWERED",
                    "title": "Memory audit presentation",
                    "statement": "When presenting a memory audit, provide a complete itemized list rather than only aggregate counts.",
                    "long_term_utility": True,
                },
            ],
            "forbidden_write_ids": ["f9-list-now"],
        },
    },
    "F10": {
        "name": "assimilation-conflict-shadow",
        "expected": {
            "terminal_dispositions": {
                "f10-confirm": "confirm",
                "f10-refine": "refine",
                "f10-conflict": "conflict",
            }
        },
        "shadow": {
            "fixture_id": "F10",
            "current_truth": [
                {"id": "truth-f10-timeout", "statement": "The hook waits for a terminal receipt."},
                {"id": "truth-f10-cleanup", "statement": "Cleanup retains a source on safety uncertainty."},
                {"id": "truth-f10-provider", "statement": "The configured provider produces the receipt."},
            ],
            "promotion_points": [
                {
                    "id": "f10-confirm",
                    "answer_status": "ANSWERED",
                    "title": "Hook terminal receipt",
                    "statement": "The hook waits for a terminal receipt.",
                    "long_term_utility": True,
                    "relationship": "equivalent",
                    "matched_truth_id": "truth-f10-timeout",
                },
                {
                    "id": "f10-refine",
                    "answer_status": "ANSWERED",
                    "title": "Cleanup safety boundary",
                    "statement": "When destructive source cleanup cannot be verified as safe, retain the source and fail closed.",
                    "long_term_utility": True,
                    "relationship": "refines",
                    "matched_truth_id": "truth-f10-cleanup",
                },
                {
                    "id": "f10-conflict",
                    "answer_status": "ANSWERED",
                    "title": "Provider ownership",
                    "statement": "A different provider owns the terminal receipt.",
                    "long_term_utility": True,
                    "relationship": "conflicts",
                    "matched_truth_id": "truth-f10-provider",
                },
            ],
            "forbidden_write_ids": ["f10-conflict"],
        },
    },
    "F11": {
        "name": "clean-retrieval-shadow",
        "expected": {
            "default_projection": ["title", "statement", "scope"],
            "forbidden_projection_fields": [
                "session_id",
                "distill_job_id",
                "candidate_id",
                "evidence_id",
                "content_sha256",
                "reason_code",
                "provider_receipt",
            ],
        },
        "shadow": {
            "fixture_id": "F11",
            "current_truth": [
                {"id": "truth-f11-cleanup", "statement": "Cleanup fails closed."},
            ],
            "promotion_points": [],
            "forbidden_write_ids": [],
            "retrieval_record": {
                "title": "Archive cleanup safety",
                "statement": "When destructive source cleanup cannot be verified as safe, fail closed and retain the source.",
                "scope": "harness-mem maintenance",
                "session_id": "019ffb67-1ff6-7593-b3c1-87d98760d44b",
                "distill_job_id": "fixture-job-F11",
                "candidate_id": "f11-cleanup",
                "evidence_id": "evidence-f11",
                "content_sha256": "not-for-default-retrieval",
                "reason_code": "verified",
                "provider_receipt": "receipt-f11",
            },
            "forbidden_projection_fields": [
                "session_id",
                "distill_job_id",
                "candidate_id",
                "evidence_id",
                "content_sha256",
                "reason_code",
                "provider_receipt",
            ],
        },
    },
}


def fixture(fixture_id: str) -> dict[str, Any]:
    """Return a defensive copy of one versioned fixture."""

    return json.loads(json.dumps(DISTILL_FIXTURES[fixture_id]))


def catalog_fingerprint() -> str:
    payload = json.dumps(
        DISTILL_FIXTURES,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = ["DISTILL_FIXTURES", "catalog_fingerprint", "fixture"]
