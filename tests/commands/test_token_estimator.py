"""Unit tests for the v2.3.1 token estimator (task 3.4).

Exercises the three-tier resolution chain in
``harness_mem.commands.token_estimator``:

1. ``tiktoken`` cl100k_base path (success).
2. Char-heuristic fallback when ``tiktoken`` cannot be imported.
3. Char-heuristic fallback when the encoder fails to load.

The third tier (dim-weight fallback fired by the *caller* on
content-fetch failure) lives in ``test_replay_window.py`` because it
is a selector-level concern, not a token_estimator concern.
"""

from __future__ import annotations

import sys

import pytest

from harness_mem.commands import token_estimator
from harness_mem.commands.token_estimator import count_tokens, reset_for_tests


class FakeEncoder:
    def encode(self, text: str) -> list[str]:
        return text.split()


def test_count_tokens_tiktoken_path_uses_loaded_encoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tiktoken path returns the loaded encoder's token count."""
    reset_for_tests()

    # Patch the loader instead of reaching for the real cl100k_base
    # vocabulary. Fresh tiktoken installs may download that file on first
    # use, which makes this unit test depend on network/cache state.
    tiktoken = pytest.importorskip("tiktoken")
    encoder = FakeEncoder()
    monkeypatch.setattr(tiktoken, "get_encoding", lambda _name: encoder)

    short = "Hello, world!"
    assert count_tokens(short) == len(encoder.encode(short))
    assert token_estimator.tokenizer_kind == "tiktoken"

    longer = "Hello, world! This is a test sentence."
    assert count_tokens(longer) == len(encoder.encode(longer))
    assert token_estimator.tokenizer_kind == "tiktoken"

    # Empty input returns 0 without changing tokenizer_kind to a
    # misleading value (the implementation deliberately leaves the
    # flag alone for empty input).
    assert count_tokens("") == 0
    assert token_estimator.tokenizer_kind == "tiktoken"


def test_count_tokens_falls_back_when_tiktoken_unimported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``import tiktoken`` raises, fall back to len(text) // 4."""
    reset_for_tests()

    # ``setitem(sys.modules, "tiktoken", None)`` makes ``import
    # tiktoken`` raise ImportError without uninstalling the package.
    monkeypatch.setitem(sys.modules, "tiktoken", None)

    text = "Some text here that is not too short."
    assert count_tokens(text) == len(text) // 4
    assert token_estimator.tokenizer_kind == "char-heuristic"

    # Reset state so subsequent tests in this module / suite start
    # from a known-clean slate (the monkeypatch fixture lifts the
    # sys.modules patch automatically; reset_for_tests clears the
    # sticky failure flag inside the estimator).
    reset_for_tests()


def test_count_tokens_falls_back_when_encoder_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``tiktoken.get_encoding`` raises, set the sticky failure flag."""
    reset_for_tests()

    tiktoken = pytest.importorskip("tiktoken")

    def _raise(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated load failure")

    monkeypatch.setattr(tiktoken, "get_encoding", _raise)

    text = "Hello, world!"
    assert count_tokens(text) == len(text) // 4  # 13 // 4 == 3
    assert token_estimator.tokenizer_kind == "char-heuristic"
    # Sticky failure flag is the contract that prevents repeated
    # encoder-load attempts on every call.
    assert token_estimator._encoder_load_failed is True

    reset_for_tests()
