"""Private, serial, caller-owned Codex stdio lifecycle. Never resumes a thread."""
from __future__ import annotations

import copy
from contextlib import ExitStack
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import queue
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, cast
from uuid import uuid4

from harness_mem.autonomous.hook_guard import (
    register_provider_process_lease,
    release_provider_process_lease,
)
from harness_mem.autonomous.provider import ProviderError, _classify_failure


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _config(overrides: list[str]) -> dict[str, Any]:
    try:
        toml = importlib.import_module("tomllib")
    except ModuleNotFoundError:
        toml = importlib.import_module("tomli")
    result = {}
    for index in range(0, len(overrides), 2):
        if overrides[index] != "-c":
            raise ProviderError("Invalid background override", kind="setup_required")
        key, separator, _ = overrides[index + 1].partition("=")
        if not separator:
            raise ProviderError("Invalid background override value", kind="setup_required")
        value = toml.loads(overrides[index + 1])
        for part in key.split("."):
            value = value[part]
        result[key] = value
    return result


def _lookup(config: dict[str, Any], key: str) -> Any:
    if key in config:
        return config[key]
    value: Any = config
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError(f"Invalid native {label}", kind="unrecoverable")
    return value


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError(f"Invalid native {label}", kind="unrecoverable")
    return value


class CodexAppServer:
    """One daemon per existing executor, guarded by its owning process scope."""

    def __init__(self, executable: str, *, scope_factory: Callable[..., Any],
                 remove_directory: Callable[[Path], None], poll_seconds: float) -> None:
        self.executable = executable
        self.scope_factory = scope_factory
        self.remove_directory = remove_directory
        self.poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._process: Any = None
        self._resources: Any = None
        self._stderr_file: Any = None
        self._root: Path | None = None
        self._lease: Path | None = None
        self._readers: list[threading.Thread] = []
        self._messages: Any = queue.Queue()
        self._writes: Any = queue.Queue()
        self._epoch: str | None = None
        self._key: Any = None
        self._next_id = 0
        self._seen_threads: set[str] = set()
        self._profile: Any = None
        self._active: dict[str, Any] | None = None
        self._closed = False
        self._starts = 0
        self._shutdown_seconds = 0.0
        self._cleanup_pending = False
        self._executable_stamp: Any = None
        self._executable_sha256: str | None = None
        self._instruction_contract: dict[str, str] | None = None
        self._stderr_tail = ""
        self._stderr_lock = threading.Lock()

    def _tick(self, deadline: float, heartbeat: Callable[[], None] | None) -> float:
        if heartbeat is not None:
            heartbeat()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderError("Codex app-server call deadline exceeded", kind="transient")
        return min(self.poll_seconds, remaining)

    def _acquire(self, deadline: float, heartbeat: Any) -> None:
        while not self._lock.acquire(timeout=self._tick(deadline, heartbeat)):
            pass

    def _spawn(self, command: list[str], cwd: Path, env: dict[str, str]) -> Any:
        # A private seam for local protocol-peer tests; no public transport switch.
        return subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="strict",
            creationflags=(subprocess.CREATE_NO_WINDOW | 0x00000004) if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )

    def _start(self, root: Path, env: dict[str, str], overrides: list[str],
               instructions: str, data_dir: Path, deadline: float, heartbeat: Any,
               record: dict[str, Any]) -> None:
        path = Path(shutil.which(self.executable) or self.executable)
        stat = path.stat()
        stamp = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ino)
        if stamp != self._executable_stamp:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            self._executable_sha256 = digest.hexdigest()
            self._executable_stamp = stamp
        record["executable_sha256"] = self._executable_sha256
        record["executable_kind"] = "native" if path.suffix.lower() == ".exe" else "launcher"
        # The inherited environment may contain credentials. Compare it only
        # in process memory; never serialize, hash or retain it in receipts.
        signature = (stamp, str(root.resolve()), tuple(overrides), _sha(instructions),
                     dict(env), str(data_dir.resolve()))
        if (self._process is not None and not self._cleanup_pending
                and signature == self._key and self._process.poll() is None):
            return
        # A previous stop may have reaped the leader but retained a locked
        # stream, directory or lease. Never overwrite that cleanup ownership.
        if (self._process is not None or self._resources is not None
                or self._stderr_file is not None or self._readers
                or self._root is not None or self._lease is not None):
            self._stop(deadline, heartbeat)
        self._tick(deadline, heartbeat)
        self._epoch = uuid4().hex
        self._messages = queue.Queue()
        self._writes = queue.Queue()
        self._root = Path(tempfile.mkdtemp(prefix="codex-app-server-", dir=root))
        self._resources = ExitStack()
        self._seen_threads = set()
        self._profile = None
        self._instruction_contract = None
        self._stderr_tail = ""
        self._key = signature
        instruction_path = self._root / "instructions.md"
        instruction_path.write_text(instructions, encoding="utf-8")
        command = [self.executable, "app-server", "--listen", "stdio://", *overrides,
                   "-c", "thread_unload_delay_secs=0", "-c",
                   "model_instructions_file=" + json.dumps(str(instruction_path))]
        self._stderr_file = stderr = tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", dir=self._root,
        )
        self._lease = register_provider_process_lease(data_dir, pid=os.getpid())
        self._process = self._spawn(command, self._root, env)
        record.update(server_epoch=self._epoch, server_pid=self._process.pid)
        self._resources.enter_context(self.scope_factory(self._process, enabled=True))
        self._starts += 1
        process, epoch, messages, writes = self._process, self._epoch, self._messages, self._writes

        def read_stdout() -> None:
            try:
                for line in process.stdout:
                    messages.put((epoch, json.loads(line)))
                messages.put((epoch, EOFError("Native app-server stdout closed")))
            except Exception as exc:
                messages.put((epoch, exc))

        def read_stderr() -> None:
            try:
                for text in process.stderr:
                    with self._stderr_lock:
                        self._stderr_tail = (self._stderr_tail + text)[-2000:]
                    stderr.write(text)
            except (OSError, ValueError):
                pass  # Process termination closes this owned stream.

        def write_stdin() -> None:
            try:
                while True:
                    text = writes.get()
                    if text is None:
                        return
                    process.stdin.write(text)
                    process.stdin.flush()
            except Exception as exc:
                messages.put((epoch, exc))

        self._readers = [threading.Thread(target=fn, daemon=True) for fn in
                         (read_stdout, read_stderr, write_stdin)]
        for thread in self._readers:
            thread.start()
        record["server_epoch"] = self._epoch
        record["server_pid"] = self._process.pid
        self._rpc("initialize", {"clientInfo": {"name": "harness_mem", "version": "1"},
                  "capabilities": {"experimentalApi": True, "requestAttestation": False}},
                  deadline, heartbeat, record)
        self._send({"method": "initialized", "params": {}})

    def _send(self, message: dict[str, Any]) -> None:
        self._writes.put(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _receive(self, deadline: float, heartbeat: Any, record: dict[str, Any]) -> dict[str, Any]:
        while True:
            try:
                epoch, value = self._messages.get(timeout=self._tick(deadline, heartbeat))
            except queue.Empty:
                if self._process is not None and self._process.poll() is not None:
                    raise self._process_exit_error()
                continue
            if epoch != self._epoch:
                continue
            if isinstance(value, Exception):
                if isinstance(value, EOFError) and self._process is not None:
                    # EOF can win the race against wait()/stderr. Do not erase
                    # a startup rejection behind an ambiguous stream error.
                    try:
                        self._process.wait(timeout=max(0.0, min(0.2, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        pass
                    if len(self._readers) > 1:
                        self._readers[1].join(timeout=0.05)
                    record["process_exit_code"] = self._process.poll()
                    with self._stderr_lock:
                        diagnostic = self._stderr_tail.lower()
                    if "is not recognized as an internal or external command" in diagnostic:
                        record["startup_failure_reason"] = "windows_launcher_command_resolution"
                        raise ProviderError(
                            "Native Codex launcher could not resolve its command dependency",
                            kind="setup_required", exit_code=self._process.poll(),
                        )
                    if "error parsing" in diagnostic or "invalid configuration" in diagnostic:
                        record["startup_failure_reason"] = "configuration_rejected"
                if self._process is not None and self._process.poll() not in (None, 0):
                    raise self._process_exit_error()
                raise ProviderError(f"Native app-server stream failed: {value}", kind="transient")
            message = _object(value, "message")
            record["event_count"] += 1
            # Config responses can contain opaque native provider settings.
            # Bind protocol identities, not the whole configuration payload.
            params = message.get("params") or {}
            identity = {"id": message.get("id"), "method": message.get("method")}
            if isinstance(params, dict):
                identity.update({key: params.get(key) for key in ("threadId", "turnId", "responseId")})
            record["protocol_sha256"] = _sha(record["protocol_sha256"] + json.dumps(identity, sort_keys=True))
            if "method" in message and "id" in message:
                self._send({"id": message["id"], "error": {"code": -32601,
                            "message": "Background memory decisions cannot service interactive requests"}})
                raise ProviderError("Unexpected native server request", kind="unrecoverable")
            return message

    def _process_exit_error(self) -> ProviderError:
        code = int(self._process.returncode or 0)
        with self._stderr_lock:
            classified = _classify_failure(self._stderr_tail, code)
        # Native stderr can contain opaque host/provider details. Preserve its
        # failure category and exit code without retaining it in receipts.
        labels = {"auth_invalid": "authentication denied", "quota_exhausted": "quota exhausted",
                  "setup_required": "setup required", "unrecoverable": "request rejected"}
        return ProviderError("Native Codex " + labels.get(classified.kind, "process exited") +
                             f" (exit {code})", kind=classified.kind, exit_code=code)

    def _rpc(self, method: str, params: dict[str, Any], deadline: float,
             heartbeat: Any, record: dict[str, Any]) -> dict[str, Any]:
        self._tick(deadline, heartbeat)
        self._next_id += 1
        request_id = self._next_id
        rpc = {"method": method, "id": request_id, "status": "sent",
               "params_sha256": _sha(json.dumps(params, sort_keys=True, ensure_ascii=False))}
        record["rpc"].append(rpc)
        if method == "turn/start":
            record["model_dispatched"] = True
        self._send({"id": request_id, "method": method, "params": params})
        while True:
            message = self._receive(deadline, heartbeat, record)
            if "method" in message:
                self._notification(message, record)
            elif message.get("id") == request_id:
                if "error" in message:
                    rpc["status"] = "error"
                    raise ProviderError("Native " + method + ": " + json.dumps(message["error"]),
                                        kind="unrecoverable")
                rpc["status"] = "completed"
                return _object(message.get("result"), method + " response")
            # Late RPC responses have no authority over this request.

    def _notification(self, message: dict[str, Any], record: dict[str, Any]) -> None:
        params = message.get("params")
        if not isinstance(params, dict) or params.get("threadId") != record.get("thread_id"):
            return
        method = message["method"]
        if method == "thread/closed":
            record["thread_closed"] = True
            return
        if not record.get("turn_id"):
            if method == "rawResponse/completed" and record["model_dispatched"]:
                # Paid completion evidence can precede the start reply. Bind
                # its observed identities without admitting pending semantics.
                self._response(params, record)
            record["early"].append(message)
            return
        if params.get("turnId") != record["turn_id"]:
            # turn/completed carries its id inside turn, not a top-level turnId.
            if method != "turn/completed" or (params.get("turn") or {}).get("id") != record["turn_id"]:
                return
        if method == "rawResponse/completed":
            self._response(params, record)
        elif method in {"item/started", "item/completed"}:
            self._item(_object(params.get("item"), "item"), record,
                       completed=method == "item/completed")
        elif method == "turn/completed":
            turn = _object(params.get("turn"), "terminal turn")
            record["terminal"] = turn.get("status")
            record["turn_error"] = turn.get("error")
            for item in turn.get("items") or []:
                self._item(_object(item, "terminal item"), record)
        elif method == "error":
            record["native_errors"].append(copy.deepcopy(params))
            if params.get("willRetry") is not True:
                raise ProviderError("Native turn error: " + json.dumps(params.get("error")), kind="transient")

    @staticmethod
    def _response(params: dict[str, Any], record: dict[str, Any]) -> None:
        turn_id = _identity(params.get("turnId"), "response turn id")
        response_id = _identity(params.get("responseId"), "response id")
        item = {"thread_id": record["thread_id"], "turn_id": turn_id,
                "response_id": response_id, "usage": params.get("usage")}
        key = (turn_id, response_id)
        prior = record["responses"].get(key)
        if prior is not None and prior != item:
            raise ProviderError("Conflicting duplicate native usage", kind="unrecoverable")
        record["responses"][key] = item

    def _item(self, item: dict[str, Any], record: dict[str, Any], *, completed: bool = True) -> None:
        if item.get("type") in {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall",
                                "collabAgentToolCall", "subAgentActivity", "webSearch", "imageView",
                                "imageGeneration"}:
            raise ProviderError("Codex memory decision attempted unexpected tool activity", kind="unrecoverable")
        if completed and item.get("type") == "agentMessage" and item.get("phase") in (None, "final_answer"):
            text = item.get("text")
            if not isinstance(text, str):
                raise ProviderError("Invalid native agent text", kind="unrecoverable")
            key = _identity(item.get("id"), "agent item id")
            prior = record["messages"].get(key)
            if prior is not None and prior != text:
                raise ProviderError("Conflicting duplicate native final item", kind="unrecoverable")
            record["messages"][key] = text

    def _attest(self, config: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
        for key, expected in overrides.items():
            if key == "mcp_servers":
                # Native deep merge retains command/env fields. Only the
                # enabled flags belong to this override's safety contract.
                servers = config.get(key)
                if not isinstance(servers, dict) or any(
                    name not in servers or not isinstance(servers[name], dict)
                    or servers[name].get("enabled") is not False for name in expected
                ):
                    raise ProviderError("Native background override unattested: " + key, kind="setup_required")
                continue
            if _lookup(config, key) != expected:
                raise ProviderError("Native background override unattested: " + key, kind="setup_required")
        servers = config.get("mcp_servers", {})
        if not isinstance(servers, dict) or any(
            not isinstance(value, dict) or value.get("enabled") is not False for value in servers.values()
        ):
            raise ProviderError("Native MCP isolation unattested", kind="setup_required")
        return sorted(servers)

    @staticmethod
    def _attestation_config(response: dict[str, Any]) -> dict[str, Any]:
        config = dict(_object(response.get("config"), "effective config"))
        key = "tools.experimental_request_user_input.enabled"
        if _lookup(config, key) is None:
            # ToolsV2 omits this supported native field. The official layers
            # are highest-to-lowest priority; inspect this one boolean only,
            # never serialize raw layers or unrelated provider/MCP settings.
            layers = response.get("layers")
            if isinstance(layers, list):
                for layer in layers:
                    if not isinstance(layer, dict) or layer.get("disabledReason") is not None:
                        continue
                    raw = layer.get("config")
                    value = _lookup(raw, key) if isinstance(raw, dict) else None
                    if value is not None:
                        config[key] = value
                        break
        return config

    @staticmethod
    def _home_instruction_contract(env: dict[str, str]) -> dict[str, str]:
        home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
        for name in ("AGENTS.override.md", "AGENTS.md"):
            path = home / name
            if path.is_file():
                body = path.read_bytes()
                if body.decode("utf-8", errors="replace").strip():
                    return {str(path.resolve()): hashlib.sha256(body).hexdigest()}
        return {}

    def run(self, *, runtime_dir: Path, data_dir: Path, cwd: Path, env: dict[str, str],
            overrides: list[str], instructions: str, prompt: str, schema: dict[str, Any],
            deadline: float, heartbeat: Any) -> tuple[str, dict[str, Any]]:
        started = time.monotonic()
        record: dict[str, Any] = {"call_id": uuid4().hex, "server_epoch": None, "rpc": [],
            "thread_id": None, "turn_id": None, "responses": {}, "messages": {}, "early": [],
            "model_dispatched": False, "terminal": None, "thread_closed": False,
            "input_sha256": _sha(prompt), "schema_sha256": _sha(json.dumps(schema, sort_keys=True)),
            "instructions_sha256": _sha(instructions), "event_count": 0,
            "protocol_sha256": "", "native_errors": [], "status": "running"}
        callback = heartbeat
        next_heartbeat = 0.0

        def call_heartbeat() -> None:
            nonlocal next_heartbeat
            now = time.monotonic()
            if callback is not None and now >= next_heartbeat:
                callback()
                next_heartbeat = now + self.poll_seconds

        # This closure belongs to one call, including its time waiting for the
        # owner lock. A second borrower must never advance this caller's gate.
        heartbeat = call_heartbeat if callback is not None else None
        locked = False
        try:
            self._acquire(deadline, heartbeat)
            locked = True
            if self._closed:
                raise ProviderError("Codex app-server owner is closed", kind="setup_required")
            self._active = record
            self._start(runtime_dir, env, overrides, instructions, data_dir, deadline, heartbeat, record)
            record.update(server_epoch=self._epoch, server_pid=self._process.pid)
            home_instructions = self._home_instruction_contract(env)
            if self._instruction_contract is not None and home_instructions != self._instruction_contract:
                raise ProviderError("Native home instructions changed within executor", kind="setup_required")
            config = self._attestation_config(self._rpc(
                "config/read", {"cwd": str(cwd), "includeLayers": True}, deadline, heartbeat, record,
            ))
            disabled = self._attest(config, _config(overrides))
            safe_config = dict(_config(overrides))
            safe_config["mcp_servers"] = {name: {"enabled": False} for name in disabled}
            safe_config.update({key: config.get(key) for key in (
                "model", "model_provider", "model_reasoning_effort", "service_tier",
            )})
            record["native_configuration_sha256"] = _sha(json.dumps(safe_config, sort_keys=True))
            record["tool_profile_attestation"] = "same_overrides_and_native_mcp_status; wire additional_tools requires qualification"
            model_profile = {key: config.get(key) for key in
                             ("model", "model_provider", "model_reasoning_effort", "service_tier")}
            if self._profile is not None and self._profile != model_profile:
                raise ProviderError("Native model profile changed within executor", kind="setup_required")
            self._profile = model_profile
            record["requested_profile"] = model_profile
            response = self._rpc("thread/start", {"cwd": str(cwd), "ephemeral": True,
                "approvalPolicy": "never", "sandbox": "read-only", "baseInstructions": instructions,
                "config": _config(overrides), "experimentalRawEvents": True}, deadline, heartbeat, record)
            thread = _object(response.get("thread"), "thread")
            thread_id = _identity(thread.get("id"), "thread id")
            record["thread_id"] = thread_id
            if thread_id in self._seen_threads or thread.get("ephemeral") is not True or thread.get("path") is not None:
                raise ProviderError("Native ephemeral thread isolation failed", kind="setup_required")
            sources = response.get("instructionSources")
            if thread.get("turns") != [] or not isinstance(sources, list) or any(
                not isinstance(source, str) for source in sources
            ) or [str(Path(source).resolve()) for source in sources] != list(home_instructions):
                raise ProviderError("Native thread inherited history or instructions", kind="setup_required")
            if self._home_instruction_contract(env) != home_instructions:
                raise ProviderError("Native home instructions changed during thread start", kind="setup_required")
            self._instruction_contract = home_instructions
            record["home_instruction_sources"] = home_instructions
            self._seen_threads.add(thread_id)
            if response.get("approvalPolicy") != "never" or (response.get("sandbox") or {}).get("type") != "readOnly":
                raise ProviderError("Native thread permissions unattested", kind="setup_required")
            record["effective_profile"] = {"model": response.get("model"),
                "model_provider": response.get("modelProvider"), "model_reasoning_effort": response.get("reasoningEffort"),
                "service_tier": response.get("serviceTier")}
            for key, expected in model_profile.items():
                if expected is not None and record["effective_profile"][key] != expected:
                    raise ProviderError("Native model profile mismatch: " + key, kind="setup_required")
            status = self._rpc("mcpServerStatus/list", {"threadId": thread_id, "detail": "toolsAndAuthOnly"},
                               deadline, heartbeat, record)
            rows = status.get("data")
            if not isinstance(rows, list) or status.get("nextCursor") is not None or any(
                not isinstance(row, dict) or row.get("name") not in disabled
                or row.get("tools") != {} or row.get("serverInfo") is not None for row in rows
            ):
                raise ProviderError("Native thread MCP isolation failed", kind="setup_required")
            params: dict[str, Any] = {"threadId": thread_id, "input": [{"type": "text", "text": prompt}],
                                      "outputSchema": schema}
            turn_response = self._rpc("turn/start", params, deadline, heartbeat, record)
            turn = _object(turn_response.get("turn"), "turn")
            record["turn_id"] = _identity(turn.get("id"), "turn id")
            record["responses"] = {key: row for key, row in record["responses"].items()
                                   if row["turn_id"] == record["turn_id"]}
            early, record["early"] = record["early"], []
            for message in early:
                self._notification(message, record)
            if turn.get("status") in {"completed", "failed", "interrupted"}:
                self._notification({"method": "turn/completed", "params": {"threadId": thread_id, "turn": turn}}, record)
            while record["terminal"] not in {"completed", "failed", "interrupted"}:
                self._notification(self._receive(deadline, heartbeat, record), record)
            self._rpc("thread/unsubscribe", {"threadId": thread_id}, deadline, heartbeat, record)
            while not record["thread_closed"]:
                self._notification(self._receive(deadline, heartbeat, record), record)
            if record["terminal"] != "completed":
                raise ProviderError("Native turn " + str(record["terminal"]) + ": " +
                                    json.dumps(record.get("turn_error")), kind="transient")
            if not record["messages"]:
                raise ProviderError("Native completed turn has no primary final message", kind="unrecoverable")
            text = list(record["messages"].values())[-1]
            record["status"] = "completed"
            self._tick(deadline, heartbeat)
            return text, self._seal(record, started)
        except BaseException as exc:
            record["status"] = "failed"
            record["error_type"] = type(exc).__name__
            # Never resend an ambiguously dispatched request. Native/semantic
            # retries retain their ordinary owner and an independent new thread.
            try:
                if locked and record.get("turn_id") and record["terminal"] is None and time.monotonic() < deadline:
                    self._rpc("turn/interrupt", {"threadId": record["thread_id"], "turnId": record["turn_id"]},
                              min(deadline, time.monotonic() + 5.0), None, record)
            except Exception as cleanup_error:
                record["interrupt_error"] = type(cleanup_error).__name__
            try:
                if locked:
                    self._stop(deadline, None)
            except Exception as cleanup_error:
                record["cleanup_error"] = str(cleanup_error)
            sealed = self._seal(record, started)
            if not isinstance(exc, Exception):
                raise
            error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc), kind="transient")
            raise ProviderError(str(error), kind=error.kind, exit_code=error.exit_code,
                attempt_results=error.attempt_results, unknown_attempt_count=error.unknown_attempt_count,
                native_attempts=(*error.native_attempts, sealed)) from exc
        finally:
            if locked:
                self._active = None
                self._lock.release()

    def _seal(self, record: dict[str, Any], started: float) -> dict[str, Any]:
        result = copy.deepcopy(record)
        result.pop("early", None)
        result["response_text_sha256"] = _sha(list(record["messages"].values())[-1]) if record["messages"] else ""
        result.pop("messages", None)
        result["responses"] = list(result["responses"].values())
        result["duration_seconds"] = time.monotonic() - started
        known = [value for row in result["responses"]
                 if (value := self._response_usage(row.get("usage"))) is not None]
        result["known_usage_subtotal"] = {
            key: sum(value[key] for value in known)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        result["known_usage_response_count"] = len(known)
        result["unknown_response_usage_count"] = len(result["responses"]) - len(known)
        result["usage"] = self.usage(result)
        result["usage_boundary"] = (
            "Per-response native completion usage only; cached/reasoning are subsets. "
            "Known prefixes remain subtotals. Missing, malformed or interrupted usage "
            "and native retry errors never become zero. Native notifications alone "
            "do not prove all HTTP transport attempts; wire accounting is separate."
        )
        return result

    @staticmethod
    def _response_usage(value: Any) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        i, o, total = (value.get(key) for key in ("inputTokens", "outputTokens", "totalTokens"))
        if not all(type(number) is int and number >= 0 for number in (i, o, total)):
            return None
        i, o, total = cast(int, i), cast(int, o), cast(int, total)
        if i + o != total:
            return None
        for key, limit in (("cachedInputTokens", i), ("reasoningOutputTokens", o)):
            part = value.get(key)
            if part is not None and (type(part) is not int or not 0 <= part <= limit):
                return None
        return {"input_tokens": i, "output_tokens": o, "total_tokens": total}

    @staticmethod
    def usage(record: dict[str, Any]) -> dict[str, Any]:
        rows = record.get("responses") or []
        values = [CodexAppServer._response_usage(row.get("usage")) for row in rows]
        complete = bool(values) and all(value is not None for value in values)
        if record.get("native_errors") or (
            record.get("model_dispatched") and record.get("terminal") not in {"completed", "failed", "interrupted"}
        ):
            complete = False
        return {key: sum(value[key] for value in values if value is not None) if complete else None
                for key in ("input_tokens", "output_tokens", "total_tokens")}

    def _stop(self, deadline: float, heartbeat: Any) -> None:
        started = time.monotonic()
        process = self._process
        self._cleanup_pending = True
        try:
            if process is not None:
                self._writes.put(None)
                if os.name != "nt":
                    try:
                        # Popen created this exact session/group. Its leader
                        # may already be reaped while children still hold pipes.
                        getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
                    except ProcessLookupError:
                        pass  # The owned group has already disappeared.
            if self._resources is not None:
                self._resources.close()  # Windows Job kills all owned children.
                self._resources = None
            if process is not None:
                try:
                    process.wait(timeout=max(0.01, min(5.0, deadline - time.monotonic())))
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.wait(timeout=5)
                    raise ProviderError("Native process cleanup exceeded deadline", kind="transient") from exc
            # Closing a buffered pipe while its reader/writer holds the lock
            # can hang indefinitely. On failure retain ownership for retry.
            for reader in self._readers:
                reader.join(timeout=max(0.01, min(5.0, deadline - time.monotonic())))
                if reader.is_alive():
                    raise ProviderError("Native reader cleanup failed", kind="transient")
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError as exc:
                            # A dead peer can leave buffered stdin whose final
                            # flush reports EPIPE (EINVAL on Windows). The
                            # process is already reaped; still join readers and
                            # release the scratch directory and lease.
                            if stream is not process.stdin or exc.errno not in {
                                errno.EPIPE, errno.EINVAL, errno.EBADF,
                            }:
                                raise
            if self._stderr_file is not None:
                self._stderr_file.close()
                self._stderr_file = None
            self._process = None
            self._readers = []
            if self._root is not None:
                self.remove_directory(self._root)
                self._root = None
            release_provider_process_lease(self._lease)
            self._lease = None
            self._cleanup_pending = False
        finally:
            self._shutdown_seconds += time.monotonic() - started

    def close(self) -> dict[str, Any]:
        deadline = time.monotonic() + 10.0
        self._acquire(deadline, None)
        try:
            self._closed = True
            self._stop(deadline, None)
            return {"server_starts": self._starts, "shutdown_seconds": self._shutdown_seconds,
                    "closed": True}
        except Exception as exc:
            record = {"call_id": uuid4().hex, "server_epoch": self._epoch,
                      "phase": "owner_close", "status": "failed", "model_dispatched": False,
                      "duration_seconds": 10.0 - max(0.0, deadline - time.monotonic()),
                      "error_type": type(exc).__name__, "usage": {"input_tokens": None,
                      "output_tokens": None, "total_tokens": None}}
            raise ProviderError(str(exc), kind="transient", native_attempts=(record,)) from exc
        finally:
            self._lock.release()
