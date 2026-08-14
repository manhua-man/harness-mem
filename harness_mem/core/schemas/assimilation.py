"""Shared vocabulary for the post-verification memory decision."""

from __future__ import annotations

from typing import Literal


AssimilationDisposition = Literal[
    "add",
    "refine",
    "confirm",
    "supersede",
    "no_write",
    "handoff",
    "defer",
    "conflict",
    "reject",
]


__all__ = ["AssimilationDisposition"]
