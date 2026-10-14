#!/usr/bin/env python3
"""Development-only path adapter for a frozen, isolated memory comparison.

Usage: python matched_memory_host.py --mode hm|upstream --manifest ABS_PATH
       [index | run UUID... | bundle UUID... | deep --session-ids UUID... |
        mark UUID distilled]

The caller creates the manifest, project config and native fixtures. This file
does not create a second runtime or judge completion. HM delegates the complete
MCP surface/transport to the current source server. Upstream delegates to the
clone's commands and run_deep_batch without changing claim extraction. Its
KNOWLEDGE_FILE is explicitly mapped to kb_file (an experiment path adaptation).
Neither branch changes HOME/CODEX_HOME. Python audit guards are defense in depth
for this trusted development fixture runner, not an OS sandbox for hostile code.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import site
import subprocess
import sys
import time
import tomllib
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

REPO = Path(__file__).resolve().parents[2]
PATH_FIELDS = (
    "run_root", "project_root", "native_root", "data_dir", "notes_dir",
    "audit_path", "upstream_root", "upstream_distill", "kb_file",
)
ID_SUFFIX = re.compile(r"([0-9a-f-]{36})\.jsonl$")


class ScopeError(ValueError):
    """A caller or persisted path escaped the frozen experiment scope."""


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def absolute(value: Any) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not Path(value).is_absolute():
        raise ScopeError(f"absolute path required: {value!r}")
    return Path(value).resolve()


def fixed_uuid(value: Any) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise ScopeError(f"canonical session UUID required: {value!r}") from exc
    return value


class Manifest:
    def __init__(self, path: Path):
        self.path = absolute(path)
        self.raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.device_scope = self.raw.get("device_scope", False)
        if type(self.device_scope) is not bool:
            raise ScopeError("device_scope must be boolean")
        if type(self.raw.get("schema_version")) is not int or self.raw["schema_version"] != 1:
            raise ScopeError("schema_version must be 1")
        self.paths = {key: absolute(self.raw.get(key)) for key in PATH_FIELDS}
        run = self.paths["run_root"]
        if run == REPO / ".tmp" or not within(run, REPO / ".tmp"):
            raise ScopeError("run_root must be a child of REPO/.tmp")
        for key, target in self.paths.items():
            parent = REPO / ".tmp" if key == "upstream_root" else run
            if not within(target, parent) or (key != "run_root" and target == parent):
                raise ScopeError(f"{key} must be below {parent}")
        self.project_name = self.raw.get("project_name")
        if (not isinstance(self.project_name, str) or not self.project_name.strip()
                or any(c in self.project_name for c in "/\\")):
            raise ScopeError("project_name must be a nonempty project name")
        if self.device_scope and self.project_name != "global":
            raise ScopeError("device fixture uses the existing global memory context")
        ids = self.raw.get("session_ids")
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            raise ScopeError("session_ids must be a nonempty unique UUID array")
        self.session_ids = tuple(fixed_uuid(sid) for sid in ids)
        for key in ("project_root", "native_root", "upstream_root"):
            if not self.paths[key].is_dir():
                raise ScopeError(f"{key} must exist")
        protected = (self.paths["native_root"], self.paths["upstream_root"])
        for key in ("project_root", "data_dir", "notes_dir", "audit_path", "upstream_distill", "kb_file"):
            for root in protected:
                if within(self.paths[key], root) or within(root, self.paths[key]):
                    raise ScopeError(f"{key} overlaps a read-only source")
        self.check_config()
        self.check_tree(run)
        self.check_tree(self.paths["upstream_root"])
        self.check_native()

    def check_config(self) -> None:
        config = self.paths["project_root"] / ".harness-mem.toml"
        self.check_path(config, self.paths["project_root"])
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        if parsed.get("distill", {}).get("autonomous", {}).get("enabled") is not False:
            raise ScopeError("project config must explicitly set distill.autonomous.enabled=false")

    @staticmethod
    def check_path(path: Path, root: Path) -> Path:
        resolved = path.resolve()
        if not within(resolved, root):
            raise ScopeError(f"path escapes validated scope: {path}")
        return resolved

    def check_tree(self, root: Path) -> None:
        # Reject links even when their present target is in scope: later retargeting
        # must not make the snapshot or recursive native GC follow another tree.
        if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
            raise ScopeError(f"linked directory is not allowed: {root}")
        for path in root.rglob("*"):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ScopeError(f"linked path is not allowed: {path}")
            self.check_path(path, root)

    def check_native(self) -> None:
        found = set()
        for name in ("sessions", "archived_sessions"):
            root = self.paths["native_root"] / name
            self.check_path(root, self.paths["native_root"])
            for path in root.rglob("*.jsonl"):
                match = ID_SUFFIX.search(path.name)
                sid = fixed_uuid(match[1] if match else "")
                self.require_session(sid)
                with path.open(encoding="utf-8-sig") as handle:
                    header = json.loads(handle.readline())
                meta = header.get("payload", {})
                valid_context = (not meta.get("cwd") or within(absolute(meta["cwd"]), self.paths["run_root"])) if self.device_scope else absolute(meta.get("cwd")) == self.paths["project_root"]
                if (header.get("type") != "session_meta" or meta.get("id") != sid or not valid_context):
                    raise ScopeError(f"native metadata does not match fixed scope: {path}")
                found.add(sid)
        if found != set(self.session_ids):
            raise ScopeError("native fixture must contain every fixed session UUID")

    def require_session(self, sid: Any) -> None:
        if fixed_uuid(sid) not in self.session_ids:
            raise ScopeError(f"unknown session: {sid}")

    def validate_arguments(self, value: Any) -> None:
        """Check nested governance/evidence selectors as well as top-level scope."""
        if isinstance(value, list):
            for item in value:
                self.validate_arguments(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if item is None:
                    continue
                if key in {"project", "project_name"} and item != self.project_name:
                    raise ScopeError("project must match manifest")
                if key == "project_names" and item != [self.project_name]:
                    raise ScopeError("cross-project selection is not allowed")
                if key in {"root", "project_root", "cwd", "workspace", "project_path"}:
                    if self.device_scope and key == "project_root" and item == "":
                        continue
                    if (not within(absolute(item), self.paths["run_root"]) if self.device_scope
                            else absolute(item) != self.paths["project_root"]):
                        raise ScopeError("project root must match manifest")
                if key in {"client", "host_client", "resolved_client"} and item != "codex":
                    raise ScopeError("only codex is allowed")
                if key == "clients" and item != ["codex"]:
                    raise ScopeError("only codex is allowed")
                if key == "scope" and item != ("all" if self.device_scope else "project"):
                    raise ScopeError("only project scope is allowed")
                if key == "session_id":
                    self.require_session(item)
                if key == "session_ids":
                    if not isinstance(item, list):
                        raise ScopeError("session_ids must be an array")
                    for sid in item:
                        self.require_session(sid)
                if key in {"path", "file_path", "repository_path", "source_uri"}:
                    path = item
                    if key == "source_uri":
                        uri = urlsplit(item)
                        if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
                            raise ScopeError("only isolated file sources are allowed")
                        path = unquote(uri.path)
                        if os.name == "nt" and path.startswith("/") and path[2:3] == ":":
                            path = path[1:]
                    target = Path(path)
                    target = target if target.is_absolute() else self.paths["project_root"] / target
                    self.check_path(target, self.paths["run_root"])
                self.validate_arguments(item)


def append_audit(manifest: Manifest, record: dict) -> None:
    path = manifest.check_path(manifest.paths["audit_path"], manifest.paths["run_root"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def install_io_guard(manifest: Manifest) -> None:
    """Guard writes, source reads, SQLite, and unexpected model/process calls."""
    run = manifest.paths["run_root"]
    protected = (manifest.paths["native_root"], manifest.paths["upstream_root"])
    libraries = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    libraries.extend(Path(path).resolve() for path in site.getsitepackages())
    libraries.append(Path(site.getusersitepackages()).resolve())
    reads = [run, manifest.paths["upstream_root"], REPO / "harness_mem",
             Path(__file__).resolve(), manifest.path, *libraries]

    def check(value: Any, write: bool = False) -> None:
        if isinstance(value, int) or value is None:
            return  # already-open stdio / file descriptors
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        path = Path(value).resolve()
        if write:
            if not within(path, run) or any(within(path, root) for root in protected):
                raise ScopeError(f"write outside isolated data: {path}")
        elif not any(within(path, root) for root in reads):
            raise ScopeError(f"read outside validated scope: {path}")

    def audit(event: str, args: tuple) -> None:
        if event == "open":
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            check(args[0], writing)
        elif event in {"os.listdir", "os.scandir"}:
            check(args[0])
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
            check(args[0], True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            check(args[0], True)
            check(args[1], True)
            if event != "os.rename":
                raise ScopeError("link creation is not allowed")
        elif event == "sqlite3.connect":
            database = str(args[0])
            if database != ":memory:":
                if database.startswith("file:"):
                    database = unquote(urlsplit(database).path)
                    if os.name == "nt" and database.startswith("/") and database[2:3] == ":":
                        database = database[1:]
                check(database, True)
        elif event in {"socket.connect", "socket.bind"}:
            # Windows asyncio creates its wakeup pipe with stdlib socketpair,
            # implemented using an authenticated ephemeral loopback connection.
            frame = sys._getframe(1)
            while frame is not None:
                if (frame.f_code.co_name == "_fallback_socketpair"
                        and Path(frame.f_code.co_filename).resolve() == Path(sys.base_prefix) / "Lib" / "socket.py"
                        and args[1][0] in {"127.0.0.1", "::1"}):
                    return
                frame = frame.f_back
            raise ScopeError(f"external network execution is not allowed: {event}")
        elif event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            raise ScopeError(f"model/process execution is not allowed: {event}")

    sys.addaudithook(audit)


def run_hm(manifest: Manifest) -> int:
    # This import MUST stay inside the child; server import redirects FD 1.
    sys.path.insert(0, str(REPO))
    from harness_mem.mcp import server
    from harness_mem.adapters import AdapterRegistry
    from harness_mem.adapters.codex.adapter import CodexAdapter
    from harness_mem.commands import session_inventory, support
    from harness_mem.config import merge
    from harness_mem.mcp import distill_handlers

    merge._user_config_path = lambda: manifest.paths["data_dir"] / "config.toml"
    merge._legacy_user_config_path = lambda: manifest.paths["data_dir"] / "config.json"

    def build(client, backend=None, **kwargs):
        if client != "codex":
            raise ScopeError("only codex is allowed; no other native source scan")
        return CodexAdapter(backend, sessions_dir=manifest.paths["native_root"] / "sessions",
                            archive_dir=manifest.paths["native_root"] / "archived_sessions",
                            project_root=None if manifest.device_scope else manifest.paths["project_root"],
                            scope="all" if manifest.device_scope else "project")

    AdapterRegistry.build = staticmethod(build)
    session_inventory.build_inspection_adapter = build
    session_inventory.HOSTS = ("codex",)
    distill_handlers._session_notes_dir = lambda backend: manifest.paths["notes_dir"]
    # Existing imports can hold the old resolver. Replace just that path dependency.
    old_resolver = support.find_project_root

    def find_root(name):
        if name != manifest.project_name:
            raise ScopeError("unknown project")
        return manifest.paths["project_root"]

    for module_name, module in tuple(sys.modules.items()):
        if module_name.startswith("harness_mem.") and getattr(module, "find_project_root", None) is old_resolver:
            module.find_project_root = find_root
    dispatch = server.handle_request

    def audited_request(request):
        if request.get("method") != "tools/call":
            return dispatch(request)
        started = time.perf_counter()
        params = request.get("params", {})
        try:
            manifest.check_config()
            manifest.check_tree(manifest.paths["run_root"])
            manifest.check_native()
            arguments = params.get("arguments", {})
            manifest.validate_arguments(arguments)
            if (params.get("name") == "prepare_session_distill" and arguments.get("client") != "codex"
                    and not (manifest.device_scope and arguments.get("client", "auto") == "auto"
                             and (arguments.get("batch_id") or arguments.get("batch_sessions")))):
                raise ScopeError("prepare_session_distill requires explicit client=codex")
            response = dispatch(request)
        except ScopeError as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32602, "message": str(exc)}}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32603, "message": str(exc)}}
        append_audit(manifest, {"mode": "hm", "method": "tools/call", "params": params,
                                "response": response, "elapsed_seconds": time.perf_counter() - started})
        return response

    server.handle_request = audited_request
    install_io_guard(manifest)
    server.main()
    return 0


def load_upstream(manifest: Manifest):
    bin_dir = manifest.paths["upstream_root"] / "adapters" / "codex-session-distill" / "bin"
    script = manifest.check_path(bin_dir / "session-distill.py", manifest.paths["upstream_root"])
    sys.path.insert(0, str(bin_dir))
    spec = importlib.util.spec_from_file_location("matched_codex_adapter", script)
    if spec is None or spec.loader is None:
        raise ScopeError("cannot load native upstream adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    distill = manifest.paths["upstream_distill"]
    # Path constants only. CODEX_HOME here is a module variable, never os.environ.
    replacements = {
        "CODEX_HOME": manifest.paths["native_root"], "DISTILL_DIR": distill,
        "RAW_PRUNE_AUDIT_FILE": distill / "raw-prune-audit.jsonl",
        "MANIFEST_FILE": distill / "manifest.json", "KNOWLEDGE_FILE": manifest.paths["kb_file"],
        "KB_REVIEW_STATE_FILE": distill / "knowledge-review-state.json",
        "PACKETS_DIR": distill / "packets", "DISTILLED_DIR": manifest.paths["notes_dir"],
        "MEMORY_DRAFTS_DIR": distill / "memory-drafts",
        "ARCHIVED_DIR": manifest.paths["native_root"] / "archived_sessions",
        "LIVE_SESSIONS_DIR": manifest.paths["native_root"] / "sessions",
        "SESSION_INDEX_FILE": manifest.paths["native_root"] / "session_index.jsonl",
    }
    for key, path in replacements.items():
        setattr(module, key, path)
    return module


def upstream_command(manifest: Manifest, argv: list[str]) -> tuple[str, list[str]]:
    if argv == ["index"]:
        return "index", []
    if argv and argv[0] in {"run", "bundle"} and len(argv) > 1:
        ids = argv[1:]
    elif argv and argv[0] == "deep":
        ids = argv[2:] if argv[1:2] == ["--session-ids"] else argv[1:]
        if not ids or set(ids) != set(manifest.session_ids) or len(ids) != len(manifest.session_ids):
            raise ScopeError("deep must select the complete fixed session_ids")
    elif len(argv) == 3 and argv[0] == "mark" and argv[2] == "distilled":
        ids = [argv[1]]
    else:
        raise ScopeError("only index, run/bundle known UUIDs, deep fixed UUIDs, mark UUID distilled are allowed")
    for sid in ids:
        manifest.require_session(sid)
    if len(set(ids)) != len(ids):
        raise ScopeError("duplicate session selection")
    return argv[0], ids


def validate_upstream_state(manifest: Manifest, module) -> list[dict]:
    state = module.load_manifest()
    sessions = state.get("sessions", [])
    for session in sessions:
        manifest.require_session(session.get("session_id"))
        for key in ("file_path", "revision_path", "bundle_path", "distilled_path"):
            if session.get(key):
                root = manifest.paths["native_root"] if key == "file_path" else manifest.paths["run_root"]
                manifest.check_path(absolute(session[key]), root)
        if absolute(session.get("cwd")) != manifest.paths["project_root"]:
            raise ScopeError("upstream persisted project does not match manifest")
    if len({s["session_id"] for s in sessions}) != len(sessions):
        raise ScopeError("duplicate upstream session")
    return sessions


def snapshot_before_close(manifest: Manifest, module, sid: str) -> Path:
    target = manifest.paths["run_root"] / "audit-before-close" / sid
    if target.exists():
        raise ScopeError("before-close snapshot already exists; refusing to overwrite evidence")
    target.mkdir(parents=True)
    candidates = {
        "packet.md": module.PACKETS_DIR / f"{sid}.md",
        "answer-packet.md": module.DISTILL_DIR / "distilled" / "answer-packets" / f"{sid}.md",
        "revision": module.DISTILL_DIR / "revisions" / sid,
        "note.md": module.DISTILLED_DIR / f"{sid}.md",
        "knowledge-base.md": module.KNOWLEDGE_FILE,
        "manifest.json": module.MANIFEST_FILE,
    }
    saved, missing = [], []
    for label, source in candidates.items():
        manifest.check_path(source, manifest.paths["run_root"])
        if not source.exists():
            missing.append(label)
        elif source.is_dir():
            manifest.check_tree(source)
            shutil.copytree(source, target / label)
            saved.append(label)
        else:
            shutil.copy2(source, target / label)
            saved.append(label)
    (target / "snapshot.json").write_text(json.dumps({"session_id": sid, "saved": saved,
                                                     "missing": missing}, indent=2), encoding="utf-8")
    return target


def run_upstream(manifest: Manifest, argv: list[str]) -> int:
    command, ids = upstream_command(manifest, argv)
    module = load_upstream(manifest)
    # Imports remain native; all data access after this point is scope guarded.
    install_io_guard(manifest)
    sessions = validate_upstream_state(manifest, module)
    started = time.perf_counter()
    if command == "index":
        result = module.cmd_index()
    elif command in {"run", "bundle"}:
        result = getattr(module, f"cmd_{command}")(session_ids=ids)
    elif command == "deep":
        from deep_distill_runner import run_deep_batch
        by_id = {s["session_id"]: s for s in sessions}
        if set(ids) - set(by_id):
            raise ScopeError("index and bundle every fixed session before deep")
        result = run_deep_batch(
            mod=module, platform="codex", batch=[by_id[sid] for sid in ids],
            answer_dir=module.DISTILL_DIR / "distilled" / "answer-packets",
            check_work_dir=module.DISTILL_DIR / "distilled" / "check-work",
            packet_prefix="", project_path_key="cwd", offset=0,
            force_bundle=False, force_extract=False, queue_file=module.DISTILL_DIR / "deep-queue.md",
        )
    else:
        # Native validation, mark, and GC are kept intact. Snapshot before any GC.
        snapshot_before_close(manifest, module, ids[0])
        result = module.cmd_mark(ids[0], "distilled", force=False)
    append_audit(manifest, {"mode": "upstream", "argv": argv, "return_code": result,
                            "elapsed_seconds": time.perf_counter() - started,
                            "knowledge_file_path_adaptation": str(module.KNOWLEDGE_FILE)})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("hm", "upstream"), required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        manifest = Manifest(Path(args.manifest))
        if args.mode == "hm" and args.command:
            raise ScopeError("hm runs the unchanged MCP stdio server; no extra arguments")
        if args.mode == "upstream":
            upstream_command(manifest, args.command)
        if not args._child:
            child_env = os.environ.copy()
            if args.mode == "hm":
                child_env["HARNESS_MEM_DATA_DIR"] = str(manifest.paths["data_dir"])
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--mode", args.mode,
                       "--manifest", str(manifest.path), "--_child", *args.command]
            return subprocess.call(command, env=child_env, cwd=manifest.paths["project_root"])
        sys.dont_write_bytecode = True
        if args.mode == "hm":
            if absolute(os.environ.get("HARNESS_MEM_DATA_DIR")) != manifest.paths["data_dir"]:
                raise ScopeError("HM child requires its isolated HARNESS_MEM_DATA_DIR")
            return run_hm(manifest)
        return run_upstream(manifest, args.command)
    except (ScopeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"matched-memory-host: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
