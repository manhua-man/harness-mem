#!/usr/bin/env python3
"""
Claude Code Session Distiller - Python implementation
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

# Configuration
DISTILL_DIR = Path.home() / ".claude" / "session-distill"
MANIFEST_FILE = DISTILL_DIR / "manifest.json"
KNOWLEDGE_FILE = DISTILL_DIR / "knowledge-base.md"
PACKETS_DIR = DISTILL_DIR / "packets"
DISTILLED_DIR = DISTILL_DIR / "distilled" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
ALLOWED_STATUSES = {"new", "bundled", "distilled", "skipped"}
TEXT_LIMIT = 1200
OUTPUT_LIMIT = 900
OUTPUT_LINE_LIMIT = 16
FILE_REF_RENDER_LIMIT = 20
TRACKED_FILE_RENDER_LIMIT = 20
FILE_REF_REGEX = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|\.{1,2}[\\/])?[A-Za-z0-9_.\\/-]+?\.(?:"
    r"markdown|md|ya?ml|jsonl?|tsx|jsx|mjs|cjs|ts|js|cs|csproj|sln|py|ps1|sh|bat|cmd|sql|env|txt|"
    r"log|prefab|html|css|scss|xml|csv|tsv"
    r"))(?::\d+)?",
    re.IGNORECASE,
)
META_XML_TAG_REGEX = re.compile(
    r"^<(?P<tag>[a-z0-9_-]+)>.*</(?P=tag)>$",
    re.IGNORECASE | re.DOTALL,
)
REQUEST_ID_REGEX = re.compile(r"\s*\(request id:[^)]+\)", re.IGNORECASE)


def now_iso():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_project_name(value):
    return value.replace(":", "-").replace("\\", "-").replace("/", "-")


def ensure_dirs():
    """Create necessary directories"""
    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    DISTILLED_DIR.mkdir(parents=True, exist_ok=True)

    if not KNOWLEDGE_FILE.exists():
        KNOWLEDGE_FILE.write_text("# Session Distill Knowledge Base\n", encoding="utf-8")

    if not MANIFEST_FILE.exists():
        manifest = {"version": 1, "updated_at": "", "sessions": []}
        save_manifest(manifest)


def load_manifest():
    """Load manifest file"""
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": "", "sessions": []}


def save_manifest(manifest):
    """Save manifest file"""
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def find_project_path(project_name=None):
    """Find project directory"""
    candidates = []
    if project_name:
        candidates.append(project_name)
        candidates.append(normalize_project_name(project_name))
    else:
        cwd = str(Path.cwd().resolve())
        candidates.append(Path.cwd().name)
        candidates.append(normalize_project_name(cwd))

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        project_path = PROJECTS_DIR / candidate
        if project_path.exists():
            return project_path
    return None


def list_project_sessions(project_path, min_size_kb=100):
    """List session files in project directory"""
    if not project_path or not project_path.exists():
        return []

    sessions = []
    for session_file in project_path.glob("*.jsonl"):
        stat = session_file.stat()
        size_bytes = stat.st_size
        size_kb = size_bytes / 1024
        if size_kb >= min_size_kb:
            sessions.append({
                "path": session_file,
                "size_bytes": size_bytes,
                "size": f"{size_kb:.1f}KB",
                "lines": len(session_file.read_text(encoding="utf-8", errors="replace").splitlines()),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                "mtime_iso": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "name": session_file.name
            })

    return sorted(sessions, key=lambda x: x["mtime_iso"], reverse=True)


def cmd_index(project_path):
    """Index sessions"""
    print("==> Index: Scanning sessions")
    manifest = load_manifest()
    timestamp = now_iso()
    sessions = list_project_sessions(project_path, min_size_kb=0)
    previous_entries = {s["session_id"]: s for s in manifest["sessions"]}
    count = 0
    refreshed_sessions = []
    for session in sessions:
        session_id = session["name"].replace(".jsonl", "")
        previous = previous_entries.get(session_id)
        if previous is None:
            print(f"  + {session['name']} ({session['size']})")
            count += 1
        status = previous.get("status", "new") if previous else "new"
        if status not in ALLOWED_STATUSES:
            status = "new"
        refreshed_sessions.append({
            "session_id": session_id,
            "file_name": session["name"],
            "file_path": str(session["path"]),
            "size": session["size"],
            "size_bytes": session["size_bytes"],
            "mtime": session["mtime"],
            "mtime_iso": session["mtime_iso"],
            "status": status,
            "bundle_path": previous.get("bundle_path") if previous else None,
            "bundle_source_mtime": previous.get("bundle_source_mtime") if previous else None,
            "bundle_source_size_bytes": previous.get("bundle_source_size_bytes") if previous else None,
            "distilled_path": previous.get("distilled_path") if previous else None,
            "notes": previous.get("notes", "") if previous else "",
        })

    manifest["sessions"] = refreshed_sessions
    manifest["updated_at"] = timestamp
    save_manifest(manifest)
    print(f"==> Index done: {count} new sessions")


def needs_bundle_refresh(session):
    return (
        session.get("bundle_source_mtime") != session.get("mtime_iso")
        or session.get("bundle_source_size_bytes") != session.get("size_bytes")
    )


def cmd_bundle(project_path, next_count=1, force=False):
    """Generate packets"""
    print("==> Bundle: Generating packets")
    manifest = load_manifest()
    count = 0
    pending_sessions = [
        session
        for session in manifest["sessions"]
        if session["status"] == "new" or force or (session["status"] == "bundled" and needs_bundle_refresh(session))
    ]
    if next_count > 0:
        pending_sessions = pending_sessions[:next_count]

    for session in pending_sessions:
        if session["status"] not in ["new", "bundled"]:
            continue

        session_id = session["session_id"]
        packet_path = PACKETS_DIR / f"{session_id}.md"

        if packet_path.exists() and not force and session["status"] == "bundled" and not needs_bundle_refresh(session):
            print(f"  -> Skipped: {session_id}")
            continue

        print(f"  -> Generating: {session_id}")
        session["status"] = "bundled"
        generate_packet(session, packet_path)
        session["bundle_path"] = str(packet_path)
        session["bundle_source_mtime"] = session.get("mtime_iso")
        session["bundle_source_size_bytes"] = session.get("size_bytes")
        count += 1

    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"==> Bundle done: {count} packets")


def normalize_text(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def squeeze_text(text, limit=TEXT_LIMIT):
    cleaned = normalize_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def squeeze_lines(text, max_lines=OUTPUT_LINE_LIMIT, max_chars=OUTPUT_LIMIT):
    cleaned = normalize_text(text)
    lines = cleaned.splitlines()
    clipped = "\n".join(lines[:max_lines]).strip()
    if len(clipped) <= max_chars:
        return clipped
    return clipped[: max_chars - 3].rstrip() + "..."


def text_would_clip(text, limit=TEXT_LIMIT):
    return len(normalize_text(text)) > limit


def output_would_clip(text, max_lines=OUTPUT_LINE_LIMIT, max_chars=OUTPUT_LIMIT):
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    lines = cleaned.splitlines()
    if len(lines) > max_lines:
        return True
    clipped = "\n".join(lines[:max_lines]).strip()
    return len(clipped) > max_chars


def dedupe_texts(values):
    seen = set()
    result = []
    for value in values:
        cleaned = normalize_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def collect_file_refs(counter, text):
    cleaned = normalize_text(text)
    if not cleaned:
        return
    for match in FILE_REF_REGEX.finditer(cleaned):
        candidate = match.group("path")
        if not candidate:
            continue
        normalized = candidate.strip("`'\"()[]{}<>")
        if "://" in normalized:
            continue
        if normalized.startswith("http://") or normalized.startswith("https://"):
            continue
        if not any(separator in normalized for separator in ("\\", "/", ":")) and not normalized.startswith("."):
            stem = Path(normalized).stem
            if len(stem) < 2 or normalized.lower() == "this.log":
                continue
        if normalized.lower() == "this.log":
            continue
        counter[normalized] += 1


def strip_request_id(text):
    return REQUEST_ID_REGEX.sub("", normalize_text(text)).strip()


def sanitize_user_prompt(text, is_meta=False):
    cleaned = normalize_text(text)
    if not cleaned or is_meta:
        return ""
    tag_match = META_XML_TAG_REGEX.match(cleaned)
    if tag_match:
        tag = tag_match.group("tag").lower()
        if tag.startswith("ide_") or tag.startswith("local-command-") or tag.startswith("command-"):
            return ""
    if cleaned.startswith("<local-command-caveat>"):
        return ""
    if "<command-name>" in cleaned and "<command-message>" in cleaned:
        return ""
    return strip_request_id(cleaned)


def extract_message_text(content):
    if isinstance(content, str):
        return normalize_text(content)
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text"):
            parts.append(str(item.get("text")))
    return normalize_text("\n\n".join(parts))


def extract_tool_result_text(content):
    if isinstance(content, str):
        return normalize_text(content)
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text"):
            parts.append(str(item.get("text")))
            continue
        if item.get("content"):
            parts.append(str(item.get("content")))
    return normalize_text("\n\n".join(parts))


def make_turn(record):
    return {
        "turn_id": record.get("promptId") or record.get("uuid") or f"turn-{record.get('timestamp', '')}",
        "cwd": record.get("cwd") or "",
        "timestamp": record.get("timestamp") or "",
        "user_messages": [],
        "assistant_updates": [],
        "assistant_finals": [],
        "commands": [],
        "system_events": [],
        "file_refs": Counter(),
        "artifacts": [],
        "duration_ms": None,
        "message_count": None,
    }


def update_session_meta(session_meta, record, models):
    for key in ("cwd", "entrypoint", "version", "sessionId"):
        value = record.get(key)
        if value and not session_meta.get(key):
            session_meta[key] = value
    if record.get("gitBranch"):
        session_meta["git_branch"] = record.get("gitBranch")
    if record.get("permissionMode"):
        session_meta["permission_modes"].add(record.get("permissionMode"))
    timestamp = record.get("timestamp")
    if timestamp and not session_meta.get("start_timestamp"):
        session_meta["start_timestamp"] = timestamp
    if timestamp:
        session_meta["last_timestamp"] = timestamp
    if record.get("type") == "assistant":
        model = ((record.get("message") or {}).get("model") or "").strip()
        if model and model != "<synthetic>":
            models.add(model)


def summarize_api_error(record):
    error = record.get("error")
    cause = record.get("cause")

    status = ""
    message = ""
    if isinstance(error, dict):
        status = str(error.get("status") or "")
        message = error.get("message") or ""
        nested = error.get("error")
        if isinstance(nested, dict):
            message = message or nested.get("message") or ""
            nested_error = nested.get("error")
            if isinstance(nested_error, dict):
                message = message or nested_error.get("message") or ""
        cause = cause or error.get("cause")

    code = ""
    path = ""
    if isinstance(cause, dict):
        code = str(cause.get("code") or "")
        path = str(cause.get("path") or "")

    parts = []
    if status:
        parts.append(f"status {status}")
    if code:
        parts.append(code)

    cleaned_message = strip_request_id(message)
    if cleaned_message:
        parts.append(cleaned_message)
    elif path:
        parts.append(path)

    retry_attempt = record.get("retryAttempt")
    if retry_attempt:
        max_retries = record.get("maxRetries") or "?"
        parts.append(f"retry {retry_attempt}/{max_retries}")

    return " ".join(part for part in parts if part) or "api error"


def append_system_event(turn, event_type, summary):
    summary = normalize_text(summary)
    if not summary:
        return
    for event in turn["system_events"]:
        if event["type"] == event_type and event["summary"] == summary:
            event["count"] += 1
            return
    turn["system_events"].append(
        {
            "type": event_type,
            "summary": summary,
            "count": 1,
        }
    )


def append_artifact(turn, artifact_type, summary):
    summary = normalize_text(summary)
    if not summary:
        return
    turn["artifacts"].append(
        {
            "type": artifact_type,
            "summary": summary,
        }
    )


def summarize_attachment(record):
    attachment = record.get("attachment") or {}
    attachment_type = attachment.get("type") or ""

    if attachment_type == "file":
        content = attachment.get("content") or {}
        file_info = content.get("file") or {}
        file_path = (
            attachment.get("displayPath")
            or file_info.get("filePath")
            or attachment.get("filename")
        )
        line_count = file_info.get("numLines")
        if not file_path:
            return None, None
        if line_count:
            return "attached_file", f"{file_path} ({line_count} line(s))"
        return "attached_file", str(file_path)

    if attachment_type == "selected_lines_in_ide":
        file_path = attachment.get("displayPath") or attachment.get("filename")
        line_start = attachment.get("lineStart")
        line_end = attachment.get("lineEnd")
        if not file_path:
            return None, None
        if line_start and line_end:
            return "ide_selection", f"{file_path}:{line_start}-{line_end}"
        return "ide_selection", str(file_path)

    if attachment_type == "opened_file_in_ide":
        file_path = attachment.get("displayPath") or attachment.get("filename")
        if file_path:
            return "ide_opened_file", str(file_path)

    return None, None


def summarize_tool_input(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return squeeze_text(str(tool_input), limit=220)

    def value(name):
        raw = tool_input.get(name)
        return str(raw) if raw not in (None, "") else ""

    if tool_name == "Bash":
        return value("command") or value("cmd") or json.dumps(tool_input, ensure_ascii=False)
    if tool_name == "Read":
        parts = [value("file_path") or value("path")]
        if value("offset"):
            parts.append(f"offset={value('offset')}")
        if value("limit"):
            parts.append(f"limit={value('limit')}")
        return " ".join(part for part in parts if part)
    if tool_name == "Grep":
        parts = [value("pattern")]
        if value("glob"):
            parts.append(f"glob={value('glob')}")
        if value("path"):
            parts.append(f"path={value('path')}")
        return " ".join(part for part in parts if part)
    if tool_name == "Glob":
        parts = [value("pattern")]
        if value("path"):
            parts.append(f"path={value('path')}")
        return " ".join(part for part in parts if part) or json.dumps(tool_input, ensure_ascii=False)
    if tool_name == "WebFetch":
        return value("url") or json.dumps(tool_input, ensure_ascii=False)
    if tool_name in {"Edit", "Write", "MultiEdit"}:
        return value("file_path") or value("path") or json.dumps(tool_input, ensure_ascii=False)
    if tool_name == "ToolSearch":
        return value("query") or json.dumps(tool_input, ensure_ascii=False)
    if tool_name == "Skill":
        return value("skill") or json.dumps(tool_input, ensure_ascii=False)
    if tool_name == "AskUserQuestion":
        questions = tool_input.get("questions") or []
        if isinstance(questions, list) and questions:
            headers = [q.get("header") for q in questions if isinstance(q, dict) and q.get("header")]
            if headers:
                return " | ".join(headers[:3])
        return "ask user question"
    if tool_name == "Agent":
        description = value("description")
        prompt = value("prompt")
        if description:
            return description
        if prompt:
            return squeeze_text(prompt.splitlines()[0], limit=220)
        return "spawn agent"
    if tool_name == "ExitPlanMode":
        return "leave plan mode"
    if tool_name.endswith("__timeline"):
        parts = []
        if value("query"):
            parts.append(value("query"))
        if value("depth_before"):
            parts.append(f"before={value('depth_before')}")
        if value("depth_after"):
            parts.append(f"after={value('depth_after')}")
        return " ".join(parts) or json.dumps(tool_input, ensure_ascii=False)
    if tool_name.endswith("__get_observations"):
        ids = tool_input.get("ids")
        if ids:
            return f"ids={ids}"
        return json.dumps(tool_input, ensure_ascii=False)
    if tool_name.endswith("__search"):
        return value("query") or json.dumps(tool_input, ensure_ascii=False)
    return json.dumps(tool_input, ensure_ascii=False)


def summarize_tool_result(tool_name, tool_use_result, result_text, is_error=False):
    result_text = normalize_text(result_text)
    summary = ""
    important = bool(is_error)
    excerpt_clipped = False

    if isinstance(tool_use_result, dict):
        if tool_name == "Bash":
            stdout = normalize_text(tool_use_result.get("stdout"))
            stderr = normalize_text(tool_use_result.get("stderr"))
            if stdout:
                first_line = stdout.splitlines()[0].strip()
                line_count = len(stdout.splitlines())
                if line_count == 1 and len(first_line) <= 160:
                    summary = first_line
                else:
                    summary = f"{line_count} line(s) stdout"
            elif stderr:
                summary = stderr.splitlines()[0].strip()
                important = True
            elif not tool_use_result.get("interrupted"):
                summary = "completed with no output"

        file_info = tool_use_result.get("file")
        if isinstance(file_info, dict):
            line_count = file_info.get("numLines")
            file_path = file_info.get("filePath") or ""
            if line_count is not None:
                summary = f"read {line_count} line(s)"
                if file_path:
                    summary += f" from {Path(file_path).name}"
        elif tool_use_result.get("filePath"):
            file_name = Path(str(tool_use_result.get("filePath"))).name
            if "updated successfully" in result_text.lower():
                summary = f"updated {file_name}"
            else:
                summary = file_name
        elif "numFiles" in tool_use_result:
            file_count = int(tool_use_result.get("numFiles") or 0)
            summary = "no files found" if file_count == 0 else f"{file_count} file(s)"
            important = file_count == 0
        elif "code" in tool_use_result or "bytes" in tool_use_result:
            code = tool_use_result.get("code")
            code_text = tool_use_result.get("codeText") or ""
            byte_count = tool_use_result.get("bytes")
            parts = [str(part) for part in (code, code_text) if part not in (None, "")]
            if byte_count:
                parts.append(f"{byte_count} bytes")
            summary = " ".join(parts).strip()

    lowered = result_text.lower()
    if not summary and result_text:
        first_line = re.sub(r"<[^>]+>", "", result_text.splitlines()[0]).strip()
        if "<persisted-output>" in result_text:
            summary = "large output saved to tool-results"
            important = True
        elif "completed with no output" in lowered:
            summary = "completed with no output"
        elif "no files found" in lowered:
            summary = "no files found"
            important = True
        elif "warning" in lowered or "error" in lowered:
            summary = first_line or "warning"
            important = True
        elif len(first_line) <= 140:
            summary = first_line

    if not important:
        important = any(
            marker in lowered
            for marker in (
                "warning",
                "error",
                "no files found",
                "<persisted-output>",
                "shorter than the provided offset",
            )
        )

    if important and result_text:
        excerpt_clipped = output_would_clip(result_text)
        result_excerpt = squeeze_lines(result_text)
    else:
        result_excerpt = ""
    return summary, result_excerpt, important, excerpt_clipped


def select_compact_window(values, head, tail):
    if len(values) <= head + tail:
        return values, 0
    omitted = len(values) - head - tail
    return values[:head] + values[-tail:], omitted


def render_text_block(title, values, limit=TEXT_LIMIT):
    if not values:
        return []
    lines = [f"### {title}", ""]
    for value in values:
        lines.append("```text")
        lines.append(squeeze_text(value, limit=limit))
        lines.append("```")
        lines.append("")
    return lines


def render_commands(commands):
    if not commands:
        return []
    lines = ["### Commands", ""]
    for command in commands:
        summary = squeeze_text(command["summary"], limit=220).replace("\n", " ")
        result_part = f" => {command['result_summary']}" if command.get("result_summary") else ""
        lines.append(f"- `{command['tool']}` {summary}{result_part}")
        if command.get("result_excerpt"):
            lines.append("")
            lines.append("```text")
            lines.append(command["result_excerpt"])
            lines.append("```")
    lines.append("")
    return lines


def render_artifacts(artifacts):
    if not artifacts:
        return []
    lines = ["### Context Artifacts", ""]
    for artifact in artifacts:
        lines.append(f"- `{artifact['type']}` {artifact['summary']}")
    lines.append("")
    return lines


def render_system_events(events):
    if not events:
        return []
    lines = ["### System Events", ""]
    for event in events:
        suffix = f" x{event['count']}" if event.get("count", 1) > 1 else ""
        lines.append(f"- `{event['type']}` {event['summary']}{suffix}")
    lines.append("")
    return lines


def render_file_refs(file_refs):
    if not file_refs:
        return []
    lines = ["### Referenced Files", ""]
    for path, count in file_refs.most_common(FILE_REF_RENDER_LIMIT):
        lines.append(f"- `{path}` ({count})")
    if len(file_refs) > FILE_REF_RENDER_LIMIT:
        lines.append(f"- ... {len(file_refs) - FILE_REF_RENDER_LIMIT} more referenced files")
    lines.append("")
    return lines


def render_tracked_files(tracked_files):
    if not tracked_files:
        return []
    lines = ["## Tracked File Backups", ""]
    items = sorted(tracked_files.items(), key=lambda item: (-item[1], item[0]))
    for path, version in items[:TRACKED_FILE_RENDER_LIMIT]:
        suffix = f" (v{version})" if version else ""
        lines.append(f"- `{path}`{suffix}")
    if len(items) > TRACKED_FILE_RENDER_LIMIT:
        lines.append(f"- ... {len(items) - TRACKED_FILE_RENDER_LIMIT} more tracked files")
    lines.append("")
    return lines


def build_packet_audit(session_meta, turns):
    file_refs = Counter()
    total_user_messages = 0
    total_assistant_updates = 0
    total_assistant_finals = 0
    total_commands = 0
    total_artifacts = 0
    total_system_events = 0
    compaction_events = 0
    error_events = 0
    unfinished_turns = 0
    clipped_text_blocks = 0
    clipped_command_excerpts = 0

    for turn in turns:
        total_user_messages += len(turn["user_messages"])
        total_assistant_updates += len(turn["assistant_updates"])
        total_assistant_finals += len(turn["assistant_finals"])
        total_commands += len(turn["commands"])
        total_artifacts += len(turn["artifacts"])
        total_system_events += len(turn["system_events"])
        file_refs.update(turn["file_refs"])

        clipped_text_blocks += sum(1 for value in turn["user_messages"] if text_would_clip(value))
        clipped_text_blocks += sum(1 for value in turn["assistant_updates"] if text_would_clip(value))
        clipped_text_blocks += sum(1 for value in turn["assistant_finals"] if text_would_clip(value))
        clipped_command_excerpts += sum(1 for command in turn["commands"] if command.get("result_excerpt_clipped"))

        for event in turn["system_events"]:
            count = int(event.get("count") or 1)
            if event["type"] == "compaction":
                compaction_events += count
            if event["type"] in {"assistant_api_error", "api_error", "hook_error"}:
                error_events += count
            if event["type"] == "unfinished_turn":
                unfinished_turns += count

    tracked_files_count = len(session_meta.get("tracked_files") or {})
    warnings = []
    lossy_transforms = [
        f"Text blocks longer than {TEXT_LIMIT} chars are clipped in rendered packet sections.",
        f"Command result excerpts longer than {OUTPUT_LINE_LIMIT} lines or {OUTPUT_LIMIT} chars are clipped.",
        f"Referenced Files renders the top {FILE_REF_RENDER_LIMIT} paths by frequency.",
        f"Tracked File Backups renders the top {TRACKED_FILE_RENDER_LIMIT} paths by version/count.",
    ]

    if compaction_events:
        warnings.append(
            f"Detected {compaction_events} compaction event(s); some upstream context may already be condensed in the raw transcript."
        )
    if session_meta.get("invalid_json_lines"):
        warnings.append(
            f"Skipped {session_meta['invalid_json_lines']} invalid JSON line(s) while parsing the raw session."
        )
    if session_meta.get("orphan_tool_results"):
        warnings.append(
            f"Encountered {session_meta['orphan_tool_results']} orphan tool result(s) that could not be matched back to a tool call."
        )
    if unfinished_turns:
        warnings.append(
            f"Detected {unfinished_turns} unfinished turn(s) where a user request has no assistant response in the captured transcript."
        )
    if session_meta.get("parse_error"):
        warnings.append(
            f"Parser reported an exception: {session_meta['parse_error']}"
        )
    if clipped_text_blocks:
        warnings.append(
            f"{clipped_text_blocks} text block(s) exceed {TEXT_LIMIT} chars and are clipped inside the packet."
        )
    if clipped_command_excerpts:
        warnings.append(
            f"{clipped_command_excerpts} command/result excerpt(s) exceed {OUTPUT_LINE_LIMIT} line(s) or {OUTPUT_LIMIT} chars and are clipped."
        )
    if len(file_refs) > FILE_REF_RENDER_LIMIT:
        warnings.append(
            f"Referenced Files shows only the top {FILE_REF_RENDER_LIMIT} paths out of {len(file_refs)} unique paths."
        )
    if tracked_files_count > TRACKED_FILE_RENDER_LIMIT:
        warnings.append(
            f"Tracked File Backups shows only the top {TRACKED_FILE_RENDER_LIMIT} paths out of {tracked_files_count} tracked files."
        )

    return {
        "coverage": "partial" if warnings else "high",
        "turns": len(turns),
        "user_messages": total_user_messages,
        "assistant_updates": total_assistant_updates,
        "assistant_finals": total_assistant_finals,
        "commands": total_commands,
        "artifacts": total_artifacts,
        "system_events": total_system_events,
        "unique_file_refs": len(file_refs),
        "tracked_files": tracked_files_count,
        "invalid_json_lines": int(session_meta.get("invalid_json_lines") or 0),
        "orphan_tool_results": int(session_meta.get("orphan_tool_results") or 0),
        "unfinished_turns": unfinished_turns,
        "compaction_events": compaction_events,
        "error_events": error_events,
        "lossy_transforms": lossy_transforms,
        "warnings": warnings,
    }


def parse_jsonl_session(session_path):
    """Parse Claude Code .jsonl session file"""
    session_meta = {
        "session_id": session_path.stem,
        "cwd": "",
        "entrypoint": "",
        "version": "",
        "git_branch": "",
        "start_timestamp": "",
        "last_timestamp": "",
        "permission_modes": set(),
        "tracked_files": {},
        "invalid_json_lines": 0,
        "orphan_tool_results": 0,
        "parse_error": "",
    }
    models = set()
    turns = []
    current_turn = None
    tool_call_lookup = {}
    assistant_turn_lookup = {}

    try:
        with open(session_path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                try:
                    record = json.loads(raw_line.strip())
                except json.JSONDecodeError:
                    session_meta["invalid_json_lines"] += 1
                    continue

                update_session_meta(session_meta, record, models)
                record_type = record.get("type")

                if record_type == "user":
                    message = record.get("message") or {}
                    content = message.get("content")

                    if isinstance(content, str):
                        prompt = sanitize_user_prompt(content, is_meta=record.get("isMeta", False))
                        if prompt:
                            current_turn = make_turn(record)
                            turns.append(current_turn)
                            current_turn["user_messages"].append(prompt)
                            collect_file_refs(current_turn["file_refs"], prompt)
                        continue

                    if isinstance(content, list):
                        prompt_parts = []
                        for item in content:
                            if not isinstance(item, dict):
                                continue

                            if item.get("type") == "tool_result":
                                tool_use_id = item.get("tool_use_id") or item.get("toolUseId")
                                tool_lookup = tool_call_lookup.get(tool_use_id)
                                if not tool_lookup:
                                    session_meta["orphan_tool_results"] += 1
                                target_turn = (
                                    tool_lookup["turn"]
                                    if tool_lookup
                                    else assistant_turn_lookup.get(record.get("sourceToolAssistantUUID")) or current_turn
                                )
                                if not target_turn:
                                    continue

                                result_text = extract_tool_result_text(item.get("content"))
                                tool_name = tool_lookup["entry"]["tool"] if tool_lookup else "tool_result"
                                result_summary, result_excerpt, important, result_excerpt_clipped = summarize_tool_result(
                                    tool_name,
                                    record.get("toolUseResult"),
                                    result_text,
                                    is_error=bool(item.get("is_error")),
                                )

                                if tool_lookup:
                                    command_entry = tool_lookup["entry"]
                                    if result_summary:
                                        command_entry["result_summary"] = result_summary
                                    if result_excerpt:
                                        command_entry["result_excerpt"] = result_excerpt
                                    command_entry["result_excerpt_clipped"] = result_excerpt_clipped
                                    command_entry["important_result"] = bool(
                                        command_entry.get("important_result") or important
                                    )
                                elif result_summary:
                                    append_system_event(target_turn, "orphan_tool_result", result_summary)

                                collect_file_refs(target_turn["file_refs"], result_text)
                                continue

                            if item.get("type") == "text":
                                prompt = sanitize_user_prompt(item.get("text", ""), is_meta=record.get("isMeta", False))
                                if prompt:
                                    prompt_parts.append(prompt)
                        if prompt_parts:
                            current_turn = make_turn(record)
                            turns.append(current_turn)
                            combined_prompt = "\n\n".join(prompt_parts)
                            current_turn["user_messages"].append(combined_prompt)
                            collect_file_refs(current_turn["file_refs"], combined_prompt)
                        continue

                if record_type == "assistant":
                    if current_turn is None:
                        current_turn = make_turn(record)
                        turns.append(current_turn)

                    if record.get("isApiErrorMessage"):
                        error_text = extract_message_text((record.get("message") or {}).get("content"))
                        append_system_event(current_turn, "assistant_api_error", squeeze_text(error_text, limit=220))
                        continue

                    message = record.get("message") or {}
                    content = message.get("content") or []
                    text = extract_message_text(content)
                    has_tool_use = False

                    if isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") != "tool_use":
                                continue

                            has_tool_use = True
                            command_entry = {
                                "tool": item.get("name") or "tool_use",
                                "call_id": item.get("id") or "",
                                "summary": summarize_tool_input(item.get("name"), item.get("input")),
                                "result_summary": "",
                                "result_excerpt": "",
                                "result_excerpt_clipped": False,
                                "important_result": False,
                            }
                            current_turn["commands"].append(command_entry)
                            if command_entry["call_id"]:
                                tool_call_lookup[command_entry["call_id"]] = {
                                    "entry": command_entry,
                                    "turn": current_turn,
                                }
                            collect_file_refs(current_turn["file_refs"], command_entry["summary"])

                    if text:
                        collect_file_refs(current_turn["file_refs"], text)
                        if message.get("stop_reason") in {"end_turn", "stop_sequence"} and not has_tool_use:
                            current_turn["assistant_finals"].append(text)
                        else:
                            current_turn["assistant_updates"].append(text)

                    if record.get("uuid"):
                        assistant_turn_lookup[record["uuid"]] = current_turn
                    continue

                if record_type == "attachment":
                    if current_turn is None:
                        continue
                    artifact_type, artifact_summary = summarize_attachment(record)
                    if artifact_type and artifact_summary:
                        append_artifact(current_turn, artifact_type, artifact_summary)
                        collect_file_refs(current_turn["file_refs"], artifact_summary)
                    continue

                if record_type == "file-history-snapshot":
                    tracked_backups = ((record.get("snapshot") or {}).get("trackedFileBackups") or {})
                    for file_path, backup in tracked_backups.items():
                        if not file_path:
                            continue
                        version = 0
                        if isinstance(backup, dict):
                            version = int(backup.get("version") or 0)
                        session_meta["tracked_files"][file_path] = max(
                            version,
                            int(session_meta["tracked_files"].get(file_path) or 0),
                        )
                        if current_turn is not None:
                            collect_file_refs(current_turn["file_refs"], file_path)
                    continue

                if record_type == "system":
                    if current_turn is None:
                        continue

                    subtype = record.get("subtype") or ""
                    if subtype == "api_error":
                        append_system_event(current_turn, "api_error", summarize_api_error(record))
                    elif subtype == "turn_duration":
                        current_turn["duration_ms"] = record.get("durationMs") or current_turn["duration_ms"]
                        current_turn["message_count"] = record.get("messageCount") or current_turn["message_count"]
                    elif subtype == "compact_boundary":
                        metadata = record.get("compactMetadata") or {}
                        summary = record.get("content") or "conversation compacted"
                        if metadata.get("preTokens") and metadata.get("postTokens"):
                            summary += f" ({metadata['preTokens']} -> {metadata['postTokens']} tokens)"
                        append_system_event(current_turn, "compaction", summary)
                    elif subtype == "away_summary":
                        append_system_event(
                            current_turn,
                            "away_summary",
                            squeeze_text(record.get("content"), limit=220),
                        )
                    elif subtype == "stop_hook_summary" and record.get("hookErrors"):
                        append_system_event(
                            current_turn,
                            "hook_error",
                            f"{len(record.get('hookErrors') or [])} hook error(s)",
                        )
                    continue

    except Exception as error:
        print(f"Warning: Error parsing session: {error}")
        session_meta["parse_error"] = str(error)

    cleaned_turns = []
    for turn in turns:
        turn["user_messages"] = dedupe_texts(turn["user_messages"])
        turn["assistant_updates"] = dedupe_texts(turn["assistant_updates"])
        turn["assistant_finals"] = dedupe_texts(turn["assistant_finals"])
        if (
            turn["user_messages"]
            and not turn["assistant_updates"]
            and not turn["assistant_finals"]
            and not turn["commands"]
        ):
            append_system_event(
                turn,
                "unfinished_turn",
                "user request has no assistant response in the captured transcript",
            )
        deduped_artifacts = []
        artifact_keys = set()
        for artifact in turn["artifacts"]:
            key = (artifact["type"], artifact["summary"])
            if key in artifact_keys:
                continue
            artifact_keys.add(key)
            deduped_artifacts.append(artifact)
        turn["artifacts"] = deduped_artifacts
        if (
            not turn["user_messages"]
            and not turn["assistant_updates"]
            and not turn["assistant_finals"]
            and not turn["commands"]
            and not turn["system_events"]
            and not turn["artifacts"]
        ):
            continue
        cleaned_turns.append(turn)

    session_meta["models"] = sorted(models)
    session_meta["permission_modes"] = sorted(session_meta["permission_modes"])
    return session_meta, cleaned_turns


def generate_packet(session, packet_path):
    """Generate a packet file with actual session content"""
    session_path = Path(session["file_path"])
    session_meta, turns = parse_jsonl_session(session_path)
    packet_audit = build_packet_audit(session_meta, turns)

    lines = [
        f"# Session Packet: {session['session_id']}",
        "",
        "## Metadata",
        "",
        f"- Source: `{session['file_name']}`",
        f"- Size: {session['size']}",
        f"- Path: `{session['file_path']}`",
        f"- Queue status: `{session.get('status', 'new')}`",
    ]

    if session_meta.get("cwd"):
        lines.append(f"- CWD: `{session_meta['cwd']}`")
    if session_meta.get("entrypoint"):
        lines.append(f"- Entry point: `{session_meta['entrypoint']}`")
    if session_meta.get("version"):
        lines.append(f"- Claude version: `{session_meta['version']}`")
    if session_meta.get("git_branch"):
        lines.append(f"- Git branch: `{session_meta['git_branch']}`")
    if session_meta.get("start_timestamp"):
        lines.append(f"- First timestamp: `{session_meta['start_timestamp']}`")
    if session_meta.get("last_timestamp"):
        lines.append(f"- Last timestamp: `{session_meta['last_timestamp']}`")
    if session_meta.get("models"):
        lines.append(f"- Model(s): `{', '.join(session_meta['models'])}`")
    if session_meta.get("permission_modes"):
        lines.append(f"- Permission mode(s): `{', '.join(session_meta['permission_modes'])}`")

    lines.extend(
        [
            "",
            "## Packet Audit",
            "",
            f"- Coverage: `{packet_audit['coverage']}`",
            f"- Turns rendered: {packet_audit['turns']}",
            f"- User request blocks: {packet_audit['user_messages']}",
            f"- Assistant updates: {packet_audit['assistant_updates']}",
            f"- Final answers: {packet_audit['assistant_finals']}",
            f"- Commands: {packet_audit['commands']}",
            f"- Context artifacts: {packet_audit['artifacts']}",
            f"- System events: {packet_audit['system_events']}",
            f"- Unique referenced files: {packet_audit['unique_file_refs']}",
            f"- Tracked file backups: {packet_audit['tracked_files']}",
        ]
    )
    if packet_audit["invalid_json_lines"]:
        lines.append(f"- Invalid JSON lines skipped: {packet_audit['invalid_json_lines']}")
    if packet_audit["orphan_tool_results"]:
        lines.append(f"- Orphan tool results: {packet_audit['orphan_tool_results']}")
    if packet_audit["unfinished_turns"]:
        lines.append(f"- Unfinished turns: {packet_audit['unfinished_turns']}")
    if packet_audit["compaction_events"]:
        lines.append(f"- Compaction events: {packet_audit['compaction_events']}")
    if packet_audit["error_events"]:
        lines.append(f"- Error-like system events: {packet_audit['error_events']}")
    lines.append("")
    if packet_audit["warnings"]:
        lines.extend(["### Audit Warnings", ""])
        for warning in packet_audit["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    lines.extend(["### Lossy Transforms", ""])
    for note in packet_audit["lossy_transforms"]:
        lines.append(f"- {note}")
    lines.append("")

    lines.extend(
        [
            "",
            "## Distillation Reminder",
            "",
            "- Read `~/.claude/skills/manhua/session-distill/references/distillation-rules.md` before promoting anything above the session note.",
            "- Read `~/.claude/skills/manhua/session-distill/references/output-layout.md` when you need the workspace files or status meanings.",
            "- `session-distill` core only prepares `manifest + packet + Packet Audit`; it does not export memory drafts or sync claude-mem.",
            "- Use `packet-memory-export` when you want structured draft memory entries from this packet.",
            "- Read `~/.claude/skills/manhua/session-distill/references/claude-mem-sync.md` only for the enhanced packet -> memory draft path.",
            "- Promote stable workflows, commands, file maps, and failure patterns.",
            "- Keep one-off context in the session note unless it clearly generalizes.",
            "- Treat claude-mem lookup as enhancement, not as a required dependency.",
            "- In standalone mode, use this packet for session notes / knowledge-base / promotion candidates.",
            "- If Packet Audit says `partial`, inspect the relevant raw transcript span before promoting memory entries or project rules.",
            "",
        ]
    )

    lines.extend(render_tracked_files(session_meta.get("tracked_files")))

    if not turns:
        lines.extend(
            [
                "## Content",
                "",
                "(No parseable content found in this session)",
                "",
            ]
        )
    else:
        for index, turn in enumerate(turns, start=1):
            lines.extend(
                [
                    f"## Turn {index}",
                    "",
                    f"- Turn id: `{turn['turn_id']}`",
                ]
            )
            if turn.get("timestamp"):
                lines.append(f"- Timestamp: `{turn['timestamp']}`")
            if turn.get("cwd"):
                lines.append(f"- Turn cwd: `{turn['cwd']}`")
            if turn.get("duration_ms"):
                lines.append(f"- Duration: `{turn['duration_ms']}ms`")
            if turn.get("message_count"):
                lines.append(f"- Message count: `{turn['message_count']}`")
            lines.append("")
            lines.extend(render_text_block("User Requests", turn["user_messages"]))
            lines.extend(render_text_block("Assistant Updates", turn["assistant_updates"]))
            lines.extend(render_text_block("Final Answers", turn["assistant_finals"]))
            lines.extend(render_commands(turn["commands"]))
            lines.extend(render_artifacts(turn["artifacts"]))
            lines.extend(render_system_events(turn["system_events"]))
            lines.extend(render_file_refs(turn["file_refs"]))

    lines.extend(
        [
            "---",
            "",
            "## Suggested Next Step",
            "",
            "1. Read this packet and inspect `Packet Audit` first",
            "2. If `Coverage: partial`, open the relevant raw transcript span before trusting the packet for promotion",
            "3. Choose mode: standalone distill or packet-memory-export",
            f"4. Standalone mode: write session note -> distilled/sessions/{session['session_id']}.md",
            "5. Standalone mode: append stable knowledge to knowledge-base.md when warranted",
            f"6. Enhanced mode: run `packet-memory-export export --session {session['session_id']}`",
            "7. Enhanced mode: review labels `new / refine / confirm / conflict / ephemeral` before any memory sync",
            "8. Use `references/distillation-rules.md` to choose the destination layer",
            f"9. Run: session-distill mark {session['session_id']} distilled",
            "",
        ]
    )

    packet_path.write_text("\n".join(lines), encoding="utf-8")


def cmd_status(project_path):
    """Show status"""
    print("==> Session Distiller Status")
    print("")

    if not MANIFEST_FILE.exists():
        print("No sessions recorded yet")
        return

    manifest = load_manifest()
    total = len(manifest["sessions"])
    new = sum(1 for s in manifest["sessions"] if s["status"] == "new")
    bundled = sum(1 for s in manifest["sessions"] if s["status"] == "bundled")
    distilled = sum(1 for s in manifest["sessions"] if s["status"] == "distilled")
    skipped = sum(1 for s in manifest["sessions"] if s["status"] == "skipped")

    print(f"Sessions: {total} total | new={new} | bundled={bundled} | distilled={distilled} | skipped={skipped}")
    print("")

    if bundled > 0:
        print("Pending packets:")
        for session in manifest["sessions"]:
            if session["status"] == "bundled":
                print(f"  - {session['session_id']}")
        print("")

    kb_lines = len(KNOWLEDGE_FILE.read_text(encoding="utf-8").splitlines()) if KNOWLEDGE_FILE.exists() else 0
    print(f"Knowledge base: {KNOWLEDGE_FILE} ({kb_lines} lines)")


def cmd_list(project_path, min_size=100):
    """List available sessions"""
    print("==> Available Sessions")
    print("")

    sessions = list_project_sessions(project_path, min_size)
    if not sessions:
        print(f"No sessions found larger than {min_size}KB")
        return

    print(f"{'Size':<8} {'Lines':<6} {'Modified':<12} Filename")
    print("-" * 60)
    for session in sessions:
        print(f"{session['size']:<8} {session['lines']:<6} {session['mtime']:<12} {session['name']}")


def cmd_mark(session_id, status):
    """Mark session status"""
    if not session_id or not status:
        print("Usage: session-distill mark SESSION-ID STATUS")
        return 1
    if status not in ALLOWED_STATUSES:
        print(f"Unsupported status: {status}")
        return 1

    print("==> Mark: Updating status")
    manifest = load_manifest()

    found = False
    for session in manifest["sessions"]:
        if session["session_id"] == session_id:
            session["status"] = status
            found = True
            break

    if not found:
        print(f"  ! Session not found: {session_id}")
        return 1

    manifest["updated_at"] = now_iso()
    save_manifest(manifest)
    print(f"  -> {session_id} -> {status}")
    print("==> Mark done")
    return 0


def cmd_run(project_path, next_count=1, force=False):
    """Run preparation phase"""
    print("==> Session Distiller: Preparation Phase")
    print("")
    print("This command runs: index + bundle")
    print("AI will handle distillation after")
    print("")

    ensure_dirs()
    cmd_index(project_path)
    cmd_bundle(project_path, next_count=next_count, force=force)

    print("")
    print("==> Preparation done")
    print("")
    print("Next steps:")
    print("  1. AI reads packets/ and inspects Packet Audit first")
    print("  2. AI opens the raw transcript when Packet Audit says partial")
    print("  3. Standalone path: write session notes -> distilled/sessions/")
    print("  4. Standalone path: append stable knowledge to knowledge-base.md")
    print("  5. Enhanced path: run packet-memory-export for structured memory drafts")
    print("  6. AI uses references/distillation-rules.md to choose the right layer")
    print("  7. Run: session-distill mark SESSION-ID distilled")
    print("")

    cmd_status(project_path)


def cmd_auto_run(project_path, next_count=3, force=False):
    """Auto-run: loop index + bundle until all sessions prepared"""
    print("==> Session Distiller: Auto-Run Mode")
    print("")
    print(f"Processing up to {next_count} sessions per batch")
    print("Script will auto-continue after each batch")
    print("Press Ctrl+C to stop")
    print("")

    ensure_dirs()
    total_bundled = 0
    batch_num = 0

    while True:
        # Refresh index
        cmd_index(project_path)
        manifest = load_manifest()

        # Separate new (need bundle) vs bundled (need AI process)
        new_sessions = [s for s in manifest["sessions"] if s["status"] == "new"]
        bundled_waiting = [s for s in manifest["sessions"] if s["status"] == "bundled"]

        # If no new sessions to bundle, we're done with preparation
        if not new_sessions:
            if bundled_waiting:
                print(f"==> {len(bundled_waiting)} session(s) bundled and waiting for AI processing")
                print("==> Run AI to process them, then re-run auto-run")
            else:
                print("==> All sessions processed")
            break

        batch_num += 1
        print("")
        print(f"--- Batch {batch_num} ---")
        print(f"New sessions to bundle: {len(new_sessions)}")

        # Bundle next batch
        cmd_bundle(project_path, next_count=next_count, force=force)

        # Check what was bundled this round
        manifest = load_manifest()
        bundled_now = [s for s in manifest["sessions"] if s["status"] == "bundled"]
        count_this_round = len(bundled_now)

        if count_this_round == 0:
            print("")
            print("==> No new sessions bundled")
            break

        total_bundled += count_this_round

        print("")
        print(f"==> Batch {batch_num} complete: {count_this_round} session(s) bundled")
        print("")
        print("AI processing steps:")
        print("  1. Read packets/ for new .md files and inspect Packet Audit")
        print("  2. Use standalone distill or packet-memory-export depending on the target flow")
        print("  3. Use references/distillation-rules.md before promoting anything")
        print("  4. Run: session-distill mark SESSION-ID distilled")
        print("  5. Run: session-distill auto-run --next", next_count)
        print("")

        # Auto-continue
        print("Auto-continuing...")

    print("")
    print(f"==> Auto-run complete: {total_bundled} session(s) bundled total")
    cmd_status(project_path)


def cmd_self_test():
    """Run synthetic self-tests for the core parser and packet generator."""
    import unittest

    print("==> Session Distiller Self-Test")
    test_dir = Path(__file__).resolve().parents[1] / "tests"
    suite = unittest.defaultTestLoader.discover(str(test_dir), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_auto_standalone(project_path, next_count=1, sync_claude_mem=False, force=False):
    """Auto-standalone distillation loop"""
    print("==> Session Distiller: Auto-Standalone Mode")
    print("")
    print(f"Processing up to {next_count} session(s)")
    if sync_claude_mem:
        print("Claude-mem sync: enabled")
    else:
        print("Claude-mem sync: disabled")
    print("")

    ensure_dirs()
    total_processed = 0
    total_knowledge = 0
    results = []

    for i in range(next_count):
        batch_num = i + 1
        print(f"--- Session {batch_num}/{next_count} ---")

        # 1. Bundle next session
        # Get list of bundled sessions before bundle
        manifest = load_manifest()
        bundled_before = {s["session_id"] for s in manifest["sessions"] if s["status"] == "bundled"}

        cmd_bundle(project_path, next_count=1, force=force)
        manifest = load_manifest()

        # Find newly bundled session (not in bundled_before)
        bundled_sessions = [s for s in manifest["sessions"] if s["status"] == "bundled"]
        if not bundled_sessions:
            print("  No more sessions to process")
            break

        # Find the session that was just bundled (not in bundled_before)
        newly_bundled = [s for s in bundled_sessions if s["session_id"] not in bundled_before]
        if newly_bundled:
            session = newly_bundled[0]
        else:
            # Fallback: use the first bundled session
            session = bundled_sessions[0]
        session_id = session["session_id"]
        print(f"  Session: {session_id}")

        # 2. Read packet
        packet_path = PACKETS_DIR / f"{session_id}.md"
        if not packet_path.exists():
            print(f"  Packet not found: {packet_path}")
            continue

        packet_content = packet_path.read_text(encoding="utf-8")

        # 3. Parse coverage
        coverage = "unknown"
        if "Coverage: `high`" in packet_content:
            coverage = "high"
        elif "Coverage: `partial`" in packet_content:
            coverage = "partial"
        print(f"  Coverage: {coverage}")

        # 4. AI will handle knowledge extraction
        # Script just prepares the packet, AI reads and extracts
        print(f"  Packet ready: {packet_path}")
        print(f"  AI should read packet and extract knowledge")

        # 5. Mark as ready for AI processing
        # AI will call mark distilled after processing
        results.append({
            "session_id": session_id,
            "coverage": coverage,
            "packet_path": str(packet_path),
            "status": "ready_for_ai"
        })

        total_processed += 1
        print(f"  Status: ready for AI processing")
        print("")

    # Summary
    print("==> Auto-Standalone Complete")
    print("")
    print(f"Processed: {total_processed} session(s)")
    print("")

    if results:
        print("Sessions ready for AI processing:")
        for r in results:
            print(f"  - {r['session_id']} (coverage: {r['coverage']})")
        print("")
        print("Next steps:")
        print("  1. AI reads each packet and extracts knowledge")
        print("  2. AI writes session note -> distilled/sessions/")
        print("  3. AI appends stable knowledge to knowledge-base.md")
        if sync_claude_mem:
            print("  4. AI exports to claude-mem")
        print(f"  {'5' if sync_claude_mem else '4'}. Run: session-distill mark <session-id> distilled")

    return 0


def main():
    commands = {"run", "status", "list", "mark", "auto-run", "auto-standalone", "self-test", "help"}
    argv = list(sys.argv[1:])
    command = "help"
    for index, token in enumerate(argv):
        if token in commands:
            command = token
            del argv[index]
            break

    parser = argparse.ArgumentParser(description="Claude Code Session Distiller")
    parser.add_argument("--project", help="Project name")
    parser.add_argument("--next", type=int, default=1, help="How many sessions to prepare in run")
    parser.add_argument("--size", type=int, default=100, help="Minimum size in KB for list")
    parser.add_argument("--force", action="store_true", help="Force regeneration")
    parser.add_argument("--sync-claude-mem", action="store_true", help="Sync to claude-mem (for auto-standalone)")
    parser.add_argument("args", nargs="*", help="Additional arguments")

    args = parser.parse_args(argv)

    if command == "help":
        parser.print_help()
        return 0

    if command == "mark":
        if len(args.args) < 2:
            print("Usage: session-distill mark SESSION-ID STATUS")
            return 1
        return cmd_mark(args.args[0], args.args[1])
    if command == "self-test":
        return cmd_self_test()

    # Find project path
    project_path = None
    if args.project:
        project_path = find_project_path(args.project)
    else:
        project_path = find_project_path()

    if not project_path and command != "mark":
        print("Error: Cannot find project directory")
        print("Use --project to specify, or run from project directory")
        return 1

    ensure_dirs()

    if command == "run":
        cmd_run(project_path, next_count=args.next, force=args.force)
    elif command == "auto-run":
        cmd_auto_run(project_path, next_count=args.next, force=args.force)
    elif command == "auto-standalone":
        cmd_auto_standalone(project_path, next_count=args.next, sync_claude_mem=args.sync_claude_mem, force=args.force)
    elif command == "status":
        cmd_status(project_path)
    elif command == "list":
        cmd_list(project_path, args.size)

    return 0


if __name__ == "__main__":
    sys.exit(main())
