"""Read-only Cursor cursorDiskKV intake; callers explicitly select databases.

Recognized contract: composerData:<id> JSON with composerId and
fullConversationHeadersOnly [{bubbleId}], plus bubbleId:<composer>:<bubble>
JSON objects. Other layouts are unsupported, never inferred from text.
The deterministic envelope retains every selected key/value (including JSON
whitespace and unknown fields). It is a session serialization, not a DB backup.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from typing import Any, Iterator

from harness_mem.adapters.protocol import Issue, SessionRecord
from harness_mem.adapters.source_metadata import metadata_record

PREFIX_SQL = (
    'SELECT key, value FROM cursorDiskKV '
    'WHERE key COLLATE BINARY >= ? AND key COLLATE BINARY < ? '
    'ORDER BY key COLLATE BINARY'
)


class CursorHistoryError(ValueError):
    """Explicit unsupported, unreadable, or incomplete native source."""


def cursor_export_messages(raw: bytes, session_id: str) -> list[dict[str, str]]:
    """Decode one pinned export with header order and explicit native authors.

    Unlisted bubbles are retained. Missing/unknown authors are never inferred
    from prose; conflicting native author fields fail closed.
    """
    from harness_mem.adapters.parser import _render_cursor_content_items

    document = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(document, dict) or document.get("format") != "cursorDiskKV-v1":
        raise CursorHistoryError("cursor_sqlite_unsupported_export")
    records = document.get("records")
    if not isinstance(records, list):
        raise CursorHistoryError("cursor_sqlite_unsupported_export")
    values: dict[str, dict] = {}
    for record in records:
        if (not isinstance(record, list) or len(record) != 2
                or not isinstance(record[0], str) or not isinstance(record[1], str)
                or record[0] in values):
            raise CursorHistoryError("cursor_sqlite_unsupported_export")
        values[record[0]] = _object(record[1])
    composer = values.pop(f"composerData:{session_id}", None)
    if not isinstance(composer, dict) or composer.get("composerId") != session_id:
        raise CursorHistoryError("cursor_sqlite_bubble_identity_mismatch")
    headers = composer.get("fullConversationHeadersOnly")
    if not isinstance(headers, list):
        raise CursorHistoryError("cursor_sqlite_unsupported_headers")
    order = [row.get("bubbleId") if isinstance(row, dict) else None for row in headers]
    if (any(not isinstance(value, str) or not value or ":" in value for value in order)
            or len(set(order)) != len(order)):
        raise CursorHistoryError("cursor_sqlite_unsupported_headers")
    prefix = f"bubbleId:{session_id}:"
    if any(not key.startswith(prefix) for key in values):
        raise CursorHistoryError("cursor_sqlite_bubble_identity_mismatch")
    keys = [prefix + str(value) for value in order]
    if not set(keys).issubset(values):
        raise CursorHistoryError("cursor_sqlite_incomplete_bubbles")
    keys.extend(sorted(set(values) - set(keys)))
    messages = []
    for key in keys:
        bubble = values[key]
        if bubble.get("bubbleId") != key[len(prefix):]:
            raise CursorHistoryError("cursor_sqlite_bubble_identity_mismatch")
        native_type, role = bubble.get("type"), bubble.get("role")
        native_role = {1: "user", 2: "assistant"}.get(native_type) if type(native_type) is int else None
        if (role is not None and role not in {"user", "assistant", "tool", "system"}
                or native_role and role is not None and role != native_role
                or role is not None and native_type is not None and native_role is None):
            raise CursorHistoryError("cursor_sqlite_author_conflict")
        text = bubble.get("text", bubble.get("content", ""))
        if not isinstance(text, str):
            text = _render_cursor_content_items(text)
        if text.strip():
            messages.append({"role": native_role or role or "unknown", "content": text.strip()})
    return messages


def cursor_user_root() -> Path:
    """Known stable desktop root; does not access files."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "Cursor/User"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Cursor/User"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Cursor/User"


def discover_sqlite_databases(user_root: Path | None = None) -> tuple[Path, ...]:
    """Discover only known native filenames, with a fully isolated root override."""
    root = user_root if user_root is not None else cursor_user_root()
    roots = [root, *sorted(path for path in (root / "profiles").glob("*") if path.is_dir())]
    candidates: list[Path] = []
    for profile in roots:
        candidates.append(profile / "globalStorage/state.vscdb")
        candidates.extend(sorted((profile / "workspaceStorage").glob("*/state.vscdb")))
    return tuple(p.absolute() for p in candidates if p.is_file())


@contextmanager
def _read_db(database: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database.absolute().as_uri() + "?mode=ro", uri=True, timeout=0.1)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        connection.close()


def inspect_sqlite_schema(database: Path) -> dict[str, Any]:
    """Public read-only diagnostic: columns and namespace counts, never values."""
    report: dict[str, Any] = {"path": str(database), "status": "readable", "tables": {}}
    try:
        with _read_db(database) as db:
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                quoted = name.replace('"', '""')
                columns = [r[1] for r in db.execute(f'PRAGMA table_info("{quoted}")')]
                detail: dict[str, Any] = {"columns": columns}
                if name in {"cursorDiskKV", "ItemTable"} and "key" in columns:
                    detail["key_prefixes"] = dict(db.execute(
                        f'SELECT CASE WHEN instr(key, char(58)) > 0 '
                        f'THEN substr(key, 1, instr(key, char(58))) ELSE key END, count(*) '
                        f'FROM "{quoted}" WHERE typeof(key)=\'text\' GROUP BY 1'
                    ))
                report["tables"][name] = detail
    except (sqlite3.Error, OSError, UnicodeError):
        report.update(status="unreadable", tables={})
    return report


def workspace_memberships(databases: tuple[Path, ...]) -> dict[Path, dict[str, Path | None]]:
    """Exact per-User composer membership, with ambiguity retained as None.

    Supported metadata is evidenced in upstream cursor-session-distill.py:
    composerHeaders(composerId, workspaceId) and ItemTable's
    composer.composerHeaders/allComposers. Never infer from names or text.
    Only explicitly supplied databases are opened, even with fixture overrides.
    """
    groups: dict[Path, list[Path]] = {}
    for database in databases:
        if database.parent.name == "globalStorage":
            groups.setdefault(database.parent.parent, []).append(database)
        elif database.parent.parent.name == "workspaceStorage":
            groups.setdefault(database.parent.parent.parent, []).append(database)
    result: dict[Path, dict[str, Path | None]] = {}
    for root, paths in groups.items():
        owners = {p.parent.name: workspace_owner(p.parent / "workspace.json")
                  for p in paths if p.parent.parent.name == "workspaceStorage"}
        claims: dict[str, set[Path | None]] = {}
        for path in paths:
            try:
                with _read_db(path) as db:
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    views = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='view'")}
                    if views & {"composerHeaders", "ItemTable"}:
                        raise CursorHistoryError("cursor_sqlite_unsupported_metadata_schema")
                    if "composerHeaders" in tables:
                        for cid, wid in db.execute("SELECT composerId, workspaceId FROM composerHeaders"):
                            if isinstance(cid, str) and cid:
                                claims.setdefault(cid, set()).add(owners.get(wid))
                    if "ItemTable" in tables and path.parent.parent.name == "workspaceStorage":
                        rows = db.execute("SELECT value FROM ItemTable WHERE key='composer.composerHeaders'").fetchall()
                        for (value,) in rows:
                            headers = _object(value).get("allComposers")
                            if not isinstance(headers, list):
                                continue
                            for header in headers:
                                cid = header.get("composerId") if isinstance(header, dict) else None
                                if isinstance(cid, str) and cid:
                                    claims.setdefault(cid, set()).add(owners[path.parent.name])
            except (sqlite3.Error, OSError, ValueError, TypeError):
                # Incomplete evidence must not certify another DB's ownership.
                result[root] = {}
                break
        else:
            if any(workspace_owner(p.parent / "workspace.json") != owners[p.parent.name]
                   for p in paths if p.parent.parent.name == "workspaceStorage"):
                result[root] = {}
            else:
                result[root] = {cid: next(iter(values)) if len(values) == 1 else None
                                for cid, values in claims.items()}
    return result


def prefix_rows(connection: sqlite3.Connection, prefix: str) -> list[tuple]:
    """Indexed, case-sensitive literal prefix lookup (no LIKE wildcards)."""
    if not prefix or ord(prefix[-1]) >= 0x10FFFF:
        raise ValueError("prefix must have a Unicode successor")
    return connection.execute(
        PREFIX_SQL, (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1))
    ).fetchall()


def workspace_owner(workspace_json: Path) -> Path | None:
    """Accept exactly one local folder URI; remote/multi-root stays unknown."""
    try:
        data = json.loads(workspace_json.read_text(encoding="utf-8-sig"))
        if (not isinstance(data, dict) or set(data) != {"folder"}
                or not isinstance(data["folder"], str)):
            return None
        uri = urlsplit(data["folder"])
        if uri.scheme != "file" or uri.netloc or uri.query or uri.fragment:
            return None
        path = unquote(uri.path, errors="strict")
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        owner = Path(path)
        return owner.resolve() if owner.is_absolute() else None
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def metadata_dependency_paths(database: Path, databases: tuple[Path, ...] = ()) -> list[Path]:
    """Cache dependencies for this container's native owner and SQLite snapshot.

    Global membership is scoped to one User/profile. WAL commits need their
    own stamp; directories track appearance of currently absent sidecars.
    """
    database = database.absolute()
    paths = [database]
    dependencies: list[Path] = []
    if database.parent.name == "globalStorage":
        root = database.parent.parent
        paths.extend(path for path in databases if (
            path.parent.name == "globalStorage" and path.parent.parent == root
        ) or (
            path.parent.parent.name == "workspaceStorage" and path.parent.parent.parent == root
        ))
        storage = root / "workspaceStorage"
        dependencies.append(storage if storage.is_dir() else root)
    for path in dict.fromkeys(paths):
        dependencies.append(path)
        for sidecar in (path.parent / "workspace.json", Path(str(path) + "-wal")):
            dependencies.append(sidecar if sidecar.is_file() else path.parent)
    return list(dict.fromkeys(dependencies))


@dataclass(frozen=True)
class CursorSQLiteSource:
    database: Path
    session_id: str
    owner: Path | None
    raw_bytes: bytes
    mtime_ns: int
    record_count: int
    readability: str = "readable"

    @property
    def source_uri(self) -> str:
        # Deliberately not file://: native cleanup cannot unlink this container.
        return "cursor-sqlite:" + self.database.as_uri() + "#" + quote(self.session_id, safe="")


def read_pinned_source(source: CursorSQLiteSource) -> bytes:
    """Read immutable enumerated bytes without reopening a changing database."""
    return source.raw_bytes


def _object(value: object) -> dict:
    if not isinstance(value, str):
        raise CursorHistoryError("unsupported_value_encoding")
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise CursorHistoryError("corrupt_json") from exc
    if not isinstance(parsed, dict):
        raise CursorHistoryError("unsupported_record_schema")
    return parsed


def _validate_disk_schema(connection: sqlite3.Connection) -> None:
    columns = connection.execute('PRAGMA table_info("cursorDiskKV")').fetchall()
    table = connection.execute(
        "SELECT type FROM sqlite_master WHERE name='cursorDiskKV'"
    ).fetchone()
    if table != ("table",) or {row[1] for row in columns} != {"key", "value"}:
        raise CursorHistoryError("cursor_sqlite_unsupported_schema")
    # Unknown layouts must not silently turn indexed lookups into body scans.
    for index in connection.execute('PRAGMA index_list("cursorDiskKV")'):
        if not index[2] or index[4]:
            continue
        quoted = index[1].replace('"', '""')
        fields = [row for row in connection.execute(
            f'PRAGMA index_xinfo("{quoted}")'
        ) if row[5]]
        if len(fields) == 1 and fields[0][2] == "key" and fields[0][4] == "BINARY":
            return
    raise CursorHistoryError("cursor_sqlite_unsupported_key_index")


def enumerate_session_metadata(
    database: Path, *, memberships: dict[str, Path | None] | None = None,
    issues: list[Issue] | None = None,
) -> list[SessionRecord]:
    """Discover composer keys and exact native owners, never composer values.

    Size/mtime describe the session container, not a rendered conversation.
    Membership conflicts stay unknown and never fall back to adjacent metadata.
    """
    database = database.absolute()
    owner = workspace_owner(database.parent / "workspace.json")
    if database.parent.name == "globalStorage" and memberships is None:
        memberships = {}
    records: list[SessionRecord] = []
    try:
        with _read_db(database) as db:
            _validate_disk_schema(db)
            keys = db.execute(
                "SELECT key FROM cursorDiskKV WHERE key COLLATE BINARY >= ? "
                "AND key COLLATE BINARY < ? ORDER BY key COLLATE BINARY",
                ("composerData:", "composerData;"),
            )
            for (key,) in keys:
                session_id = key[len("composerData:"):]
                if not session_id or ":" in session_id:
                    continue
                session_owner = owner if memberships is None else memberships.get(session_id)
                records.append(metadata_record(
                    database, session_id,
                    project_roots=[str(session_owner)] if session_owner is not None else [],
                    source_kind="cursor_sqlite",
                    metadata_paths=metadata_dependency_paths(database),
                ))
            if workspace_owner(database.parent / "workspace.json") != owner:
                raise CursorHistoryError("cursor_sqlite_ownership_changed")
        return records
    except (sqlite3.Error, OSError, UnicodeError, CursorHistoryError) as exc:
        code = str(exc) if isinstance(exc, CursorHistoryError) else "cursor_sqlite_unreadable"
        if issues is not None:
            issues.append({"level": "warning", "code": code, "message": code,
                           "path": str(database)})
        return []


def enumerate_source_records(
    database: Path, *, project_root: Path | None = None,
    issues: list[Issue] | None = None,
    memberships: dict[str, Path | None] | None = None,
    session_id: str | None = None,
) -> list[CursorSQLiteSource]:
    """Pin supported sessions in one read transaction, without DB writes.

    With session_id, fetch only that exact composer and its complete bubbles.
    Ownership requires adjacent workspace.json. Global stores without such
    evidence remain unknown (enumerable only without a project filter).
    A bad session does not hide other valid sessions.
    No connections or cursors escape this call; locks have a bounded timeout.
    """
    database = database.absolute()

    def issue(code: str, session_id: str = "") -> None:
        if issues is not None:
            issues.append({"level": "warning", "code": code, "message": code,
                           "path": str(database), "session_id": session_id})

    owner = workspace_owner(database.parent / "workspace.json")
    if owner is None:
        issue("cursor_sqlite_ownership_unknown")
    if project_root is not None and owner != project_root.resolve() and memberships is None:
        issue("cursor_sqlite_project_mismatch")
        return []
    connection = None
    sources = []
    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.1)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        _validate_disk_schema(connection)
        if session_id is None:
            composers = prefix_rows(connection, "composerData:")
        else:
            if not session_id or ":" in session_id:
                raise CursorHistoryError("cursor_sqlite_unsupported_composer")
            composers = connection.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key COLLATE BINARY = ?",
                (f"composerData:{session_id}",),
            ).fetchall()
        if not composers:
            issue("cursor_sqlite_unsupported_or_empty")
        mtime_ns = database.stat().st_mtime_ns
        for key, value in composers:
            session_id = key[len("composerData:"):]
            session_owner = owner
            if memberships is not None:
                session_owner = memberships.get(session_id)
            if project_root is not None and session_owner != project_root.resolve():
                issue("cursor_sqlite_project_mismatch", session_id)
                continue
            try:
                composer = _object(value)
                headers = composer.get("fullConversationHeadersOnly")
                if (not session_id or ":" in session_id
                        or composer.get("composerId") != session_id
                        or not isinstance(headers, list)):
                    raise CursorHistoryError("cursor_sqlite_unsupported_composer")
                ids = [h.get("bubbleId") if isinstance(h, dict) else None for h in headers]
                if any(not isinstance(i, str) or not i or ":" in i for i in ids):
                    raise CursorHistoryError("cursor_sqlite_unsupported_headers")
                if len(set(ids)) != len(ids):
                    raise CursorHistoryError("cursor_sqlite_duplicate_bubble")
                bubbles = prefix_rows(connection, f"bubbleId:{session_id}:")
                found = {k.rsplit(":", 1)[1] for k, _ in bubbles}
                if not set(ids).issubset(found) or len(found) != len(bubbles):
                    raise CursorHistoryError("cursor_sqlite_incomplete_bubbles")
                # Include unlisted bubbles too; never truncate to visible headers.
                for bubble_key, bubble_value in bubbles:
                    bubble = _object(bubble_value)
                    if bubble.get("bubbleId") != bubble_key.rsplit(":", 1)[1]:
                        raise CursorHistoryError("cursor_sqlite_bubble_identity_mismatch")
                raw = json.dumps(
                    {"format": "cursorDiskKV-v1", "records": [(key, value), *bubbles]},
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
                sources.append(CursorSQLiteSource(database, session_id, session_owner, raw,
                                                   mtime_ns, 1 + len(bubbles),
                                                   "empty_draft" if not headers and not bubbles else "readable"))
            except CursorHistoryError as exc:
                issue(str(exc), session_id)
        if workspace_owner(database.parent / "workspace.json") != owner:
            raise CursorHistoryError("cursor_sqlite_ownership_changed")
        return sources
    except CursorHistoryError as exc:
        issue(str(exc))
    except (sqlite3.Error, OSError, UnicodeError):
        issue("cursor_sqlite_unreadable")
    finally:
        if connection is not None:
            connection.close()
    return []
