"""Test-only, network-free app-server peer; never starts a native CLI or model.

Knobs arrive in a test plan file, not through a production configuration.
The JSONL witness retains every request/notification and full text verbatim.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _deny_network(event, _args):
    if event.startswith("socket."):
        raise AssertionError("stdio peer must not use a network")


sys.addaudithook(_deny_network)


def main():
    directory = Path(sys.argv[1])
    if sys.argv[2] == "--child":
        (directory / "child.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        while not (directory / "release-child").exists():
            time.sleep(0.01)
        return
    plan = json.loads(Path(sys.argv[2]).read_text("utf-8"))
    mode = plan.get("mode", "normal")
    witness = (directory / "wire.jsonl").open("a", encoding="utf-8")

    def log(direction, message):
        witness.write(json.dumps({"direction": direction, "message": message}, ensure_ascii=False) + "\n")
        witness.flush()

    def send(message):
        log("out", message)
        print(json.dumps(message, ensure_ascii=False), flush=True)

    def reply(request, result):
        send({"id": request["id"], "result": result})

    def notify(method, **params):
        send({"method": method, "params": params})

    log("startup", {"pid": os.getpid(), "cwd": str(Path.cwd())})
    if plan.get("child"):
        # Start before initialize, exercising suspended-start -> Job -> resume.
        subprocess.Popen(
            [sys.executable, "-I", "-u", "-X", "utf8", __file__, str(directory), "--child"],
            stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        until = time.monotonic() + 5
        while not (directory / "child.json").exists():
            if time.monotonic() > until:
                raise RuntimeError("child did not start")
            time.sleep(0.01)

    config = plan["config"]
    thread_count = 0
    turn_count = 0
    for line in sys.stdin:
        request = json.loads(line)
        log("in", request)
        method = request.get("method")
        params = request.get("params", {})
        if method == "initialize":
            if mode == "dead_leader":
                return  # The child still holds both output pipes open.
            reply(request, {"userAgent": "offline-python-peer"})
        elif method == "initialized":
            continue
        elif method == "config/read":
            effective = copy.deepcopy(config)
            effective["opaque_provider_settings"] = {"api_key": plan.get("secret", "fictional-secret")}
            effective.update(plan.get("config_patch", {}))
            reply(request, {"config": effective})
        elif method == "thread/start":
            thread_count += 1
            thread_id = "thread-1" if mode == "reused_thread" else f"thread-{thread_count}"
            thread = {"id": thread_id, "ephemeral": True, "path": None, "turns": []}
            thread.update(plan.get("thread_patch", {}))
            result = {
                "thread": thread, "instructionSources": [], "approvalPolicy": "never",
                "sandbox": {"type": "readOnly"}, "model": config["model"],
                "modelProvider": config["model_provider"],
                "reasoningEffort": config["model_reasoning_effort"],
                "serviceTier": config["service_tier"],
            }
            result.update(plan.get("profile_patch", {}))
            reply(request, result)
        elif method == "mcpServerStatus/list":
            rows = [{"name": name, "tools": {}, "serverInfo": None} for name in config["mcp_servers"]]
            reply(request, plan.get("mcp_status", {"data": rows, "nextCursor": None}))
        elif method == "turn/start":
            turn_count += 1
            thread_id = params["threadId"]
            turn_id = f"turn-{turn_count}"
            ids = {"threadId": thread_id, "turnId": turn_id}
            raw = plan.get("outputs", ['{"answer":"完整 source\\r\\n终点"}'])
            text = raw[(turn_count - 1) % len(raw)]
            item = {"type": "agentMessage", "id": f"message-{turn_count}",
                    "phase": "final_answer", "text": text}
            terminal = {"id": turn_id, "status": plan.get("terminal", "completed"),
                        "error": None, "items": [item]}
            (directory / "turn-received").touch()
            if mode not in {"early", "early_eof", "early_timeout", "terminal_reply"}:
                reply(request, {"turn": {"id": turn_id, "status": "inProgress", "items": []}})
            if mode.startswith("early"):
                notify("rawResponse/completed", threadId="foreign", turnId=turn_id,
                       responseId="foreign-response", usage={"inputTokens": 900, "outputTokens": 99,
                                                             "totalTokens": 999})
                if plan.get("early_foreign_turn"):
                    foreign = {"threadId": thread_id, "turnId": "foreign-turn"}
                    notify("rawResponse/completed", **foreign, responseId=f"response-{turn_count}",
                           usage={"inputTokens": 900, "outputTokens": 99, "totalTokens": 999})
                    notify("item/completed", **foreign, item={**item, "text": "foreign text"})
                    notify("turn/completed", threadId=thread_id,
                           turn={**terminal, "id": "foreign-turn"})
            if mode == "foreign":
                for foreign_ids in ({"threadId": "foreign", "turnId": turn_id},
                                    {"threadId": thread_id, "turnId": "foreign"}):
                    notify("rawResponse/completed", **foreign_ids, responseId="foreign", usage={"totalTokens": 999})
                    notify("item/completed", **foreign_ids, item={**item, "text": "foreign text"})
                    notify("turn/completed", **foreign_ids, turn={**terminal, "id": foreign_ids["turnId"]})
            notify("item/started", **ids, item={**item, "text": "incomplete prefix"})
            if mode == "tool_activity":
                notify("item/started", **ids, item={"type": "mcpToolCall", "id": "forbidden-tool"})
            usage = {"inputTokens": 30, "cachedInputTokens": 11, "cacheWriteInputTokens": 0,
                     "outputTokens": 7, "reasoningOutputTokens": 3, "totalTokens": 37}
            usage.update(plan.get("usage_patch", {}))
            if mode not in {"missing_usage", "eof_no_usage", "late_usage"}:
                response = {**ids, "responseId": f"response-{turn_count}",
                            "usage": usage, "usageMetadata": None}
                notify("rawResponse/completed", **response)
                if mode in {"duplicate", "conflict_usage", "early_eof", "early_timeout"}:
                    duplicate = copy.deepcopy(response)
                    if mode == "conflict_usage":
                        duplicate["usage"]["totalTokens"] = 38
                    notify("rawResponse/completed", **duplicate)
                if mode in {"unknown_suffix", "two_responses"}:
                    notify("rawResponse/completed", **ids, responseId=f"response-{turn_count}-2",
                           usage=None if mode == "unknown_suffix" else usage, usageMetadata=None)
                if plan.get("early_unknown_suffix"):
                    notify("rawResponse/completed", **ids, responseId=f"response-{turn_count}-unknown",
                           usage=None, usageMetadata=None)
            for _ in range(2):
                notify("thread/tokenUsage/updated", **ids, tokenUsage={
                    "total": {**usage, "inputTokens": 3000, "totalTokens": 3007},
                    "last": usage, "modelContextWindow": 475000,
                })
            if mode == "native_retry":
                notify("error", **ids, error={"message": "fictional transport retry"}, willRetry=True)
            if mode in {"eof", "eof_no_usage"}:
                return
            if mode in {"timeout", "heartbeat"}:
                continue
            if mode != "started_only":
                notify("item/completed", **ids, item=item)
            else:
                terminal["items"] = []
            if mode in {"duplicate", "conflict_message"}:
                notify("item/completed", **ids, item={**item, "text": "conflicting final"} if mode == "conflict_message" else item)
            if mode == "terminal_reply":
                reply(request, {"turn": terminal})
            elif mode in {"early", "early_eof", "early_timeout"}:
                notify("turn/completed", threadId=thread_id, turn=terminal)
                if mode == "early_eof":
                    return
                if mode == "early_timeout":
                    continue
                reply(request, {"turn": {"id": turn_id, "status": "inProgress", "items": []}})
            else:
                notify("turn/completed", threadId=thread_id, turn=terminal)
        elif method == "thread/unsubscribe":
            reply(request, {"status": "unsubscribed"})
            if mode == "late_usage":
                notify("rawResponse/completed", **ids, responseId=f"response-{turn_count}",
                       usage=usage, usageMetadata=None)
            (directory / "unsubscribe-ack").touch()
            notify("thread/closed", threadId="foreign")
            if plan.get("hold_close"):
                until = time.monotonic() + 5
                while not (directory / "release-close").exists():
                    if time.monotonic() > until:
                        raise RuntimeError("close barrier was not released")
                    time.sleep(0.01)
            if mode != "missing_close":
                notify("thread/closed", threadId=params["threadId"])
        elif method == "turn/interrupt":
            reply(request, {})
        else:
            raise AssertionError(f"unexpected request: {request!r}")


if __name__ == "__main__":
    main()
