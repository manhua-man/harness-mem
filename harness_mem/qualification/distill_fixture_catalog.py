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
            "required_terms": ["time", "token", "quality"],
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
            "required_terms": ["latency", "token", "quality"],
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
