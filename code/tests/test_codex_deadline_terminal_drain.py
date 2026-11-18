"""Bounded post-deadline accounting drain; an offline stdio peer, no model."""
from __future__ import annotations

import json
import time

import pytest

import test_codex_app_server_transport as protocol
from harness_mem.autonomous.executors import codex_app_server as transport
from harness_mem.autonomous.provider import ProviderError

peer_factory = protocol.peer_factory


@pytest.fixture
def tail_peer(tmp_path, monkeypatch, peer_factory):
    """Only the fixture peer changes; production RPC/readers/cleanup still run."""
    source = protocol.PEER.read_text(encoding="utf-8")
    before = '        elif method == "turn/interrupt":\n            reply(request, {})'
    after = '''        elif method == "turn/interrupt":
            tail = plan.get("cancel_tail", "completed")
            if tail == "hang":
                continue
            reply(request, {})
            if tail in {"foreign", "foreign_usage"}:
                notify("rawResponse/completed", threadId="foreign", turnId=turn_id,
                       responseId="foreign-response", usage=usage)
                notify("rawResponse/completed", threadId=thread_id, turnId="foreign-turn",
                       responseId="foreign-turn-response", usage=usage)
                notify("turn/completed", threadId="foreign", turn={"id": turn_id, "status": "completed", "items": []})
                if tail == "foreign":
                    continue
            if tail not in {"late_usage", "foreign_usage"}:
                notify("rawResponse/completed", **ids,
                       responseId="response-1" if tail == "conflict" else "cancel-response",
                       usage=None if tail == "missing_response" else
                           {**usage, "inputTokens": 31, "totalTokens": 38} if tail == "conflict" else usage)
            if tail == "no_terminal":
                continue
            if tail in {"top_bound_nested_foreign", "top_foreign_nested_bound"}:
                notify("turn/completed", threadId=thread_id,
                       turnId=turn_id if tail == "top_bound_nested_foreign" else "foreign-turn",
                       turn={"id": "foreign-turn" if tail == "top_bound_nested_foreign" else turn_id,
                             "status": "completed", "items": []})
                continue
            notify("turn/completed", threadId=thread_id, turn={"id": turn_id,
                   "status": "interrupted" if tail == "interrupted" else "completed", "items": []})'''
    assert before in source
    source = source.replace(before, after)
    initial = '            if mode not in {"missing_usage", "eof_no_usage", "late_usage"}:'
    assert initial in source
    source = source.replace(initial, initial[:-1] + ' and not plan.get("suppress_initial_response"):')
    close = '            (directory / "unsubscribe-ack").touch()'
    assert close in source
    source = source.replace(close, '''            if plan.get("cancel_tail") == "late_usage":
                notify("rawResponse/completed", **ids, responseId="cancel-response", usage=usage)
''' + close)
    peer = tmp_path / "deadline_tail_peer.py"
    peer.write_text(source, encoding="utf-8")
    monkeypatch.setattr(protocol, "PEER", peer)
    # Only the accounting/cleanup allowance is shortened for bounded negative
    # fixtures. The request timeout remains the original argument to run().
    monkeypatch.setattr(transport, "_CANCEL_DRAIN_SECONDS", 0.30, raising=False)
    return peer_factory


def failed(context, *, heartbeat=None):
    started = time.monotonic()
    with pytest.raises(ProviderError) as caught:
        protocol._run(context, seconds=0.8, heartbeat=heartbeat)
    assert time.monotonic() - started < 4
    record, = caught.value.native_attempts
    assert record["thread_id"] == "thread-1" and record["turn_id"] == "turn-1"
    assert record["model_dispatched"] is True and record["status"] == "failed"
    wire = protocol._wire(context)
    assert [row["method"] for row in wire].count("turn/start") == 1
    interrupts = [row for row in wire if row["method"] == "turn/interrupt"]
    assert len(interrupts) == 1
    assert interrupts[0]["params"] == {"threadId": "thread-1", "turnId": "turn-1"}
    protocol._assert_clean(context)
    return caught.value, record


@pytest.mark.parametrize("tail", ["completed", "late_usage"])
@pytest.mark.parametrize("initial_response", [True, False])
def test_original_deadline_drains_bound_terminal_and_each_late_response(tail_peer, tail, initial_response):
    context = tail_peer(mode="timeout", cancel_tail=tail, suppress_initial_response=not initial_response)
    error, record = failed(context)
    assert error.failure_reason == record["failure_reason"] == "native_request_deadline_exceeded"
    assert record["terminal"] == "completed" and record["thread_closed"] is True
    count = 2 if initial_response else 1
    assert record["usage"] == {key: number * count for key, number in protocol.KNOWN.items()}
    assert len(record["responses"]) == record["known_usage_response_count"] == count
    assert record["request_timeout_seconds"] <= 0.8
    assert record["cancel_drain_state"] == "terminal_closed"


@pytest.mark.parametrize("tail", ["interrupted", "missing_response", "no_terminal", "foreign", "hang", "conflict"])
def test_incomplete_interrupted_foreign_or_ambiguous_tail_stays_unknown(tail_peer, tail):
    context = tail_peer(mode="timeout", cancel_tail=tail)
    _error, record = failed(context)
    assert record["usage"] == protocol.UNKNOWN
    assert record["known_usage_subtotal"]["total_tokens"] >= protocol.KNOWN["total_tokens"]
    assert all(row["thread_id"] == "thread-1" and row["turn_id"] == "turn-1"
               for row in record["responses"])
    if tail in {"foreign", "hang", "no_terminal"}:
        assert record["terminal"] is None
        assert record["cancel_drain_state"] == "incomplete"
    if tail == "missing_response":
        assert record["unknown_response_usage_count"] == 1


def test_foreign_response_usage_never_inflates_bound_completed_turn(tail_peer):
    context = tail_peer(mode="timeout", cancel_tail="foreign_usage")
    _error, record = failed(context)
    assert record["usage"] == protocol.KNOWN
    assert len(record["responses"]) == 1


def test_terminal_and_cumulative_token_updates_without_bound_raw_usage_remain_unknown(tail_peer):
    context = tail_peer(mode="timeout", cancel_tail="foreign_usage", suppress_initial_response=True)
    _error, record = failed(context)
    assert record["terminal"] == "completed" and record["thread_closed"] is True
    assert record["usage"] == protocol.UNKNOWN
    assert record["known_usage_subtotal"] == dict.fromkeys(protocol.KNOWN, 0)
    assert record["responses"] == []


@pytest.mark.parametrize("tail", ["top_bound_nested_foreign", "top_foreign_nested_bound"])
def test_contradictory_top_and_nested_turn_identity_cannot_complete_paid_prefix(tail_peer, tail):
    context = tail_peer(mode="timeout", cancel_tail=tail)
    _error, record = failed(context)
    assert record["terminal"] is None
    assert record["usage"] == protocol.UNKNOWN
    assert record["known_usage_subtotal"] == {key: number * 2 for key, number in protocol.KNOWN.items()}
    assert record["cancel_drain_state"] == "incomplete"


def test_heartbeat_failure_cleans_up_without_reclassifying_as_request_deadline(tail_peer):
    context = tail_peer(mode="timeout", cancel_tail="completed")

    def heartbeat():
        if (context.server._active or {}).get("turn_id"):
            raise RuntimeError("fixture failure must not be retained verbatim")

    error, record = failed(context, heartbeat=heartbeat)
    assert error.failure_reason == record["failure_reason"] == "native_request_failed"
    assert record["usage"] == {key: number * 2 for key, number in protocol.KNOWN.items()}
    assert "fixture failure" not in json.dumps(record)


def test_normal_call_does_not_enter_cancellation_or_add_a_turn(tail_peer):
    context = tail_peer()
    _text, record = protocol._run(context)
    assert record["usage"] == protocol.KNOWN
    assert not any(row["method"] == "turn/interrupt" for row in protocol._wire(context))
    assert "cancel_drain_state" not in record
    context.server.close()
    protocol._assert_clean(context)


def test_preflight_refusal_never_sends_interrupt_or_infers_a_turn(tail_peer):
    context = tail_peer(config_patch={"web_search": "auto"})
    with pytest.raises(ProviderError) as caught:
        protocol._run(context)
    record, = caught.value.native_attempts
    assert record["model_dispatched"] is False and record["turn_id"] is None
    assert record["usage"] == protocol.UNKNOWN
    assert not any(row["method"] in {"turn/start", "turn/interrupt"} for row in protocol._wire(context))
    assert record["cancel_drain_state"] == "unbound"
    protocol._assert_clean(context)
