"""Shared support helpers for split CLI command modules."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.protocol import SessionRecord
from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile
from harness_mem.event_log import EventType, get_event_logger
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"
CONFIG_TOML_PATH = Path.home() / ".harness-mem" / "config.toml"
LEGACY_CONFIG_JSON_PATH = Path.home() / ".harness-mem" / "config.json"

NATIVE_INGEST_CLIENTS = {"claude-code", "codex", "codex-archive"}
AUTO_DETECT_CLIENTS = {
    "auto",
    "agent",
    "cursor",
    "antigravity",
    "opencode",
    "hermes",
}
SUPPORTED_INGEST_CLIENTS = NATIVE_INGEST_CLIENTS | AUTO_DETECT_CLIENTS


# v1.6.1: wake-up bucket quota defaults & validation.
DEFAULT_BUCKET_QUOTAS: dict[str, float] = {
    "semantic": 0.5,
    "episodic": 0.5,
    "procedural": 0.0,
}
_BUCKET_QUOTA_TOLERANCE: float = 0.001

# v1.6.2: embedding model configuration
DEFAULT_EMBEDDING_MODEL_ID: str = "all-MiniLM-L6-v2"
EMBEDDING_MODEL_ENV: str = "HARNESS_MEM_EMBEDDING_MODEL_ID"


class WakeBucketQuotaError(ValueError):
    """``[wake] bucket_quota_*`` 段配置非法时抛出。

    ``code`` 字段 = ``"HM-101"`` (sum mismatch) / ``"HM-102"`` (out of range)，
    ``harness-mem doctor`` 会按此码格式化提示。
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def wake_bucket_enabled(config: dict | None = None) -> bool:
    """``[wake] bucket_quota_enabled`` 默认 True。"""
    cfg = config if config is not None else get_config()
    value = cfg.get("wake", {}).get("bucket_quota_enabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def wake_bucket_quotas(config: dict | None = None) -> dict[str, float]:
    """读取并校验 ``[wake] bucket_quota_*``，返回归一化的三桶比例。

    校验规则：
    - 单值必须在 ``[0.0, 1.0]``；否则 raise ``HM-102``
    - 三值之和必须在 ``[0.999, 1.001]``；否则 raise ``HM-101``

    缺省 / 缺字段时回落到 ``DEFAULT_BUCKET_QUOTAS``。
    """
    cfg = config if config is not None else get_config()
    wake_cfg = cfg.get("wake", {}) or {}
    quotas: dict[str, float] = {}
    for bucket, default in DEFAULT_BUCKET_QUOTAS.items():
        raw = wake_cfg.get(f"bucket_quota_{bucket}", default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise WakeBucketQuotaError(
                f"wake.bucket_quota_{bucket} must be a float; got {raw!r}",
                code="HM-102",
            )
        if value < 0.0 or value > 1.0:
            raise WakeBucketQuotaError(
                f"wake.bucket_quota_{bucket}={value} is out of range [0.0, 1.0]",
                code="HM-102",
            )
        quotas[bucket] = value
    total = sum(quotas.values())
    if abs(total - 1.0) > _BUCKET_QUOTA_TOLERANCE:
        raise WakeBucketQuotaError(
            f"wake bucket quotas must sum to 1.0; got "
            f"semantic={quotas['semantic']} episodic={quotas['episodic']} "
            f"procedural={quotas['procedural']} (sum={total:g})",
            code="HM-101",
        )
    return quotas


def get_embedding_model_id(config: dict | None = None) -> str:
    """读取 ``[embedding] model_id``，默认 all-MiniLM-L6-v2。"""
    env_model_id = os.environ.get(EMBEDDING_MODEL_ENV)
    if env_model_id:
        return env_model_id
    cfg = config if config is not None else get_config()
    return cfg.get("embedding", {}).get("model_id", DEFAULT_EMBEDDING_MODEL_ID)


def clean_cli_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def clean_cli_list(values: list[str] | None) -> list[str]:
    return [
        cleaned
        for value in values or []
        if (cleaned := clean_cli_text(value)) is not None
    ]


def normalize_handoff_status(value: str | None) -> str:
    cleaned = clean_cli_text(value)
    if cleaned is None:
        return "in_progress"
    return cleaned.lower().replace("-", "_")


def get_config() -> dict:
    """Read user configuration, preferring config.toml over legacy JSON."""
    if CONFIG_TOML_PATH.exists():
        try:
            with CONFIG_TOML_PATH.open("rb") as fh:
                data = tomllib.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    if not LEGACY_CONFIG_JSON_PATH.exists():
        return {}

    try:
        return json.loads(LEGACY_CONFIG_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

_ADOPTED_NEXT_STEP_COMMANDS = {
    "ingest",
    "wake-up",
    "search",
    "purge",
    "correct",
    "handoff",
}


def log_cli_event(
    event_type: EventType,
    *,
    project_name: str | None = None,
    command: str | None = None,
    next_step: str | None = None,
    session_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """Best-effort local event logging. Never fail the command path."""
    try:
        get_event_logger(DEFAULT_DATA_DIR).log_sync(
            event_type,
            project_name=project_name,
            command=command,
            next_step=next_step,
            session_id=session_id,
            extra=extra,
        )
    except Exception:
        pass


def log_command_invoked(
    command: str,
    *,
    project_name: str | None = None,
    session_id: str | None = None,
    extra: dict | None = None,
) -> None:
    log_cli_event(
        EventType.COMMAND_INVOKED,
        project_name=project_name,
        command=command,
        session_id=session_id,
        extra=extra,
    )
    if command in _ADOPTED_NEXT_STEP_COMMANDS:
        log_cli_event(
            EventType.NEXT_STEP_ADOPTED,
            project_name=project_name,
            command=command,
            next_step=f"harness-mem {command}",
            session_id=session_id,
            extra=extra,
        )


def log_next_step_shown(project_name: str | None, source_command: str, next_step: str) -> None:
    log_cli_event(
        EventType.NEXT_STEP_SHOWN,
        project_name=project_name,
        command=source_command,
        next_step=next_step,
    )


def active_project_path() -> Path:
    return DEFAULT_DATA_DIR / "active_project.txt"


def ensure_data_dir() -> None:
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_active_project() -> str | None:
    current_path = active_project_path()
    if not current_path.exists():
        return None
    project = current_path.read_text(encoding="utf-8").strip()
    return project or None


def set_active_project(project_name: str) -> None:
    ensure_data_dir()
    active_project_path().write_text(project_name.strip(), encoding="utf-8")


def safe_project_slug(project_name: str) -> str:
    return project_name.replace("/", "_").replace("\\", "_").replace(":", "_").replace(" ", "_")


def current_agent_client() -> str:
    """Infer the current assistant runtime for default session ingestion.

    Explicit native ``HARNESS_MEM_CLIENT`` wins. Generic agent runtime names
    such as cursor/antigravity/opencode/hermes are treated as auto-detect
    requests. Otherwise Codex-specific markers win
    over generic Claude Code environment flags, because Claude-related env vars
    can be present in nested or bridged shells while ``CODEX_THREAD_ID`` is a
    stronger signal that the active conversation is a Codex rollout.
    """
    configured = normalize_client_name(os.environ.get("HARNESS_MEM_CLIENT"))
    if configured in NATIVE_INGEST_CLIENTS:
        return configured
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex-archive"
    if any(key.startswith("CLAUDE_CODE") for key in os.environ):
        return "claude-code"
    return "claude-code"


def normalize_client_name(client: str | None) -> str:
    """Normalize user/runtime-facing client names for ingestion."""
    value = (client or "auto").strip().lower()
    aliases = {
        "claude": "claude-code",
        "claude_code": "claude-code",
        "claudecode": "claude-code",
        "codex_archive": "codex-archive",
        "codexarchive": "codex-archive",
        "open-code": "opencode",
        "open_code": "opencode",
        "generic-agent": "agent",
        "generic_agent": "agent",
    }
    return aliases.get(value, value)


def resolve_ingest_client(client: str | None) -> str:
    """Resolve a requested client to a concrete adapter-backed source."""
    normalized = normalize_client_name(client)
    if normalized in NATIVE_INGEST_CLIENTS:
        return normalized
    if normalized in AUTO_DETECT_CLIENTS:
        return current_agent_client()
    return normalized


def claude_project_name_from_path(path: Path) -> str:
    """Return Claude Code's filesystem-safe project directory name for a path."""
    candidates = claude_project_name_candidates_from_path(path)
    return candidates[0] if candidates else path.name


def claude_project_name_candidates_from_path(path: Path) -> list[str]:
    """Return likely Claude Code project directory names for a path.

    Claude Code has used slightly different casing/escaping across versions and
    platforms. Keep the lookup tolerant so MCP servers do not miss real sessions
    just because their own process cwd differs from the client workspace.
    """
    resolved = path.expanduser().resolve()
    drive = resolved.drive.rstrip(":")
    parts = list(resolved.parts)
    if drive and parts:
        parts = parts[1:]
    raw_parts = [
        part
        for part in parts
        if part not in {"\\", "/"} and part.strip("\\/")
    ]

    def encode(allow_underscore: bool) -> str:
        pattern = r"[^A-Za-z0-9_-]" if allow_underscore else r"[^A-Za-z0-9]"
        safe_parts = [
            re.sub(pattern, "-", part).strip("-")
            for part in raw_parts
        ]
        return "-".join(part for part in safe_parts if part)

    suffixes = [encode(False), encode(True)]
    drive_variants = [drive]
    if drive:
        drive_variants.extend([drive.lower(), drive.upper()])

    candidates: list[str] = []
    for suffix in suffixes:
        if drive:
            for drive_variant in drive_variants:
                candidate = f"{drive_variant}--{suffix}" if suffix else drive_variant
                if candidate not in candidates:
                    candidates.append(candidate)
        elif suffix:
            if suffix not in candidates:
                candidates.append(suffix)

    if not candidates:
        candidates.append(resolved.name)
    return candidates


def is_path_within(child: Path, parent: Path) -> bool:
    """Case-insensitive containment check that is stable on Windows paths."""
    try:
        child_text = os.path.normcase(str(child.expanduser().resolve()))
        parent_text = os.path.normcase(str(parent.expanduser().resolve()))
    except OSError:
        child_text = os.path.normcase(str(child.expanduser()))
        parent_text = os.path.normcase(str(parent.expanduser()))
    return child_text == parent_text or child_text.startswith(parent_text.rstrip("\\/") + os.sep)


def project_runtime_dir(project_name: str) -> Path:
    path = DEFAULT_DATA_DIR / "projects" / safe_project_slug(project_name) / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_ingest_lock_path(project_name: str) -> Path:
    return project_runtime_dir(project_name) / ".ingest-lock"


def project_ingest_scan_stamp_path(project_name: str) -> Path:
    return project_runtime_dir(project_name) / ".ingest-scan-stamp"


def project_adapter_cursor_path(project_name: str, client: str) -> Path:
    safe_client = safe_project_slug(client)
    return project_runtime_dir(project_name) / f".ingest-cursor-{safe_client}.json"


def can_prompt() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def prompt_text(label: str, default: str | None = None, *, allow_empty: bool = False, allow_clear: bool = False) -> str | None:
    if not can_prompt():
        return default if allow_empty else None

    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if allow_clear and value == "!clear":
            return ""
        if value:
            return value
        if default is not None:
            return default
        if allow_empty:
            return ""
        print(f"{label} is required.")


def prompt_list(label: str) -> list[str]:
    if not can_prompt():
        return []

    print(f"{label} (one per line, blank to finish):")
    values: list[str] = []
    while True:
        value = input("> ").strip()
        if not value:
            return values
        values.append(value)


def prompt_list_labeled(
    field_label: str, item_description: str, existing: list[str] | None = None,
) -> list[str] | None:
    """Prompt for a list of strings, showing existing items.

    - existing profile edit: blank returns None (keep existing), '!clear' resets to [].
    - new profile creation: pass existing=[] so blank returns [].
    """
    if not can_prompt():
        return None
    has_existing = existing is not None and len(existing) > 0
    if has_existing:
        print(f"{field_label} (current: {', '.join(existing or [])}):")
        print(f"  (Enter new {item_description}, blank to keep existing, '!clear' to reset)")
    else:
        print(f"{field_label} (one per line, blank to finish):")
    values: list[str] = []
    while True:
        value = input("> ").strip()
        if not value:
            if has_existing:
                return None
            return values
        if value == "!clear":
            return []
        values.append(value)


def suggested_purge_command(project_name: str | None) -> str:
    project_flag = f" -p {project_name}" if project_name else ""
    return f"harness-mem purge{project_flag} --before <DATE> --category all --dry-run"


def resolve_project_name(
    project_name: str | None,
    *,
    required: bool = True,
    action_label: str = "this command",
) -> str | None:
    resolved = project_name or os.environ.get("HARNESS_MEM_PROJECT") or get_active_project()
    if required and not resolved and can_prompt():
        resolved = prompt_text("Project name")
        if resolved:
            set_active_project(resolved)
    if required and not resolved:
        print(
            f"Project name required for {action_label}. Pass -p/--project, "
            "set HARNESS_MEM_PROJECT, or call MCP set_active_project first."
        )
        return None
    return resolved


def project_roots(project_name: str) -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    cwd = Path.cwd()
    return [
        cwd,
        cwd / project_name,
        cwd.parent / project_name,
        repo_root.parent / "tests" / "fixtures" / project_name,
    ]


def find_project_root(project_name: str) -> Path | None:
    for candidate in project_roots(project_name):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


async def ensure_project_profile(project_name: str) -> tuple[object | None, Path | None]:
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    existing = await profile_store.get(project_name)
    if existing:
        return existing, None

    root = find_project_root(project_name)
    if root is None:
        return None, None

    profile = build_project_profile(root, project_name)
    await profile_store.save(profile)
    return profile, root


def recent_claude_sessions(project_name: str, limit: int | None = 3) -> list[SessionRecord]:
    adapter = AdapterRegistry.build("claude-code", None)
    return adapter.list_sessions(project_name, min_size_kb=0, limit=limit)


def recent_codex_sessions(limit: int | None = 3) -> list[SessionRecord]:
    adapter = AdapterRegistry.build("codex", None)
    return adapter.list_sessions(min_size_kb=0, limit=limit)


def claude_session_count(project_name: str) -> int:
    return len(recent_claude_sessions(project_name, limit=None))


def codex_session_count() -> int:
    return len(recent_codex_sessions(limit=None))


def session_identifier(session: SessionRecord) -> str:
    session_id = session.get("session_id")
    if session_id:
        return str(session_id)
    name = session.get("name")
    if name:
        return Path(str(name)).stem
    return "unknown-session"


def format_session_summary(session: SessionRecord) -> str:
    session_id = session_identifier(session)
    modified = session.get("mtime")
    if isinstance(modified, datetime):
        modified_text = modified.astimezone().strftime("%Y-%m-%d %H:%M")
    else:
        modified_text = "unknown time"
    size = session.get("size")
    if size:
        return f"- {session_id} ({modified_text}, {size})"
    return f"- {session_id} ({modified_text})"


def print_recent_sessions(title: str, sessions: list[SessionRecord]) -> None:
    if not sessions:
        return
    print(title)
    for session in sessions:
        print(f"  {format_session_summary(session)}")


def codex_scope_note() -> str:
    return "Codex sessions are global across projects, not project-scoped, and need manual review before ingest."


def profile_text(profile: object | None) -> str:
    if not profile:
        return ""
    description = getattr(profile, "description", "") or ""
    stacks = getattr(profile, "stacks", []) or []
    key_files = getattr(profile, "key_files", []) or []
    conventions = getattr(profile, "conventions", []) or []
    return description + " " + " ".join(stacks) + " " + " ".join(key_files) + " " + " ".join(conventions)


def chars_to_tokens(chars: int) -> int:
    return round(chars / 4)


def disclosure_level(tokens: int) -> str:
    if tokens < 500:
        return "L0"
    if tokens < 2000:
        return "L1"
    if tokens < 8000:
        return "L2"
    if tokens < 32000:
        return "L3"
    return "L4+"


def wake_budget(
    profile: object | None,
    entries: list,
    rules: list,
    handoffs: list,
    relation_facts: list | None = None,
) -> tuple[int, str]:
    profile_tokens = chars_to_tokens(len(profile_text(profile)))
    entry_tokens = chars_to_tokens(sum(len(entry.content) for entry in entries))
    rule_tokens = chars_to_tokens(sum(len(rule.pattern) + len(rule.trigger) for rule in rules))
    handoff_tokens = chars_to_tokens(
        sum(len(handoff.summary) + sum(len(step) for step in handoff.next_steps) for handoff in handoffs)
    )
    relation_tokens = chars_to_tokens(
        sum(
            len(fact.source_entity)
            + len(fact.relation_type)
            + len(fact.target_entity)
            + len(fact.evidence)
            for fact in (relation_facts or [])
        )
    )
    total_tokens = profile_tokens + entry_tokens + rule_tokens + handoff_tokens + relation_tokens
    return total_tokens, disclosure_level(total_tokens)


def suggested_next_step(
    *,
    project_name: str,
    observation_count: int,
    memory_entry_count: int,
    claude_sessions: list[SessionRecord],
    codex_sessions: list[SessionRecord],
) -> tuple[str, str]:
    if observation_count == 0:
        if claude_sessions:
            latest = session_identifier(claude_sessions[0])
            return (
                f'MCP ingest_sessions(project_name="{project_name}", client="claude-code", limit={min(5, len(claude_sessions))})',
                f"Recent Claude Code sessions were found. Start by ingesting the newest session: {latest}.",
            )
        if codex_sessions:
            return (
                f'MCP ingest_sessions(project_name="{project_name}", client="auto", limit={min(5, len(codex_sessions))})',
                f"{codex_scope_note()} The default auto ingest path is project-scoped; use `--scope all` only for an explicit cross-project import.",
            )
        return (
            f'MCP ingest_sessions(project_name="{project_name}", client="claude-code", limit=5)',
            "No local sessions have been ingested yet; ingestion should be driven by the agent through MCP.",
        )

    if memory_entry_count == 0 and claude_sessions:
        return (
            "/hm:distill",
            (
                "Sessions are ingested but no memory entries exist yet. "
                "Run /hm:distill in your AI agent (Claude Code, Codex, "
                "Cursor, etc.) so it can read sessions and write candidates "
                "via MCP suggest_memory_entry. v2.0 removed the heuristic "
                "CLI distill — distill is LLM-driven only."
            ),
        )

    if memory_entry_count == 0:
        return (
            'MCP search_memory(query="<query>")',
            "Observations are searchable, but wake-up needs structured memory before it becomes useful.",
        )

    return (
        f'MCP wake(project_name="{project_name}")',
        "Structured memory is ready, so MCP wake is the shortest path back into project context.",
    )


async def project_state(project_name: str) -> dict[str, int]:
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        all_obs = await backend.verbatim_store.list(limit=10000)
        project_obs = [obs for obs in all_obs if obs.metadata.get("project_name") == project_name]
        entries = await backend.structured_store.list_memory_entries(project_name, limit=1000)
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=100)
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        return {
            "observations": len(project_obs),
            "memory_entries": len(entries),
            "task_handoffs": len(handoffs),
            "confirmed_rules": len(rules),
        }
    finally:
        await backend.close()
