"""Read-only file-context helper for v2.5.2."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from harness_mem.commands.support import chars_to_tokens, disclosure_level, resolve_project_name
from harness_mem.core.schemas.context_assembly_plan import DrilldownPointer
from harness_mem.core.schemas.file_context import (
    CodeEvidence,
    CodeSymbol,
    CostHint,
    FileFingerprint,
    FileContextItem,
    FileContextResult,
    StaleFileSignal,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.read_api import regex_search_observations
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

_MAX_OBSERVATION_MATCHES = 25
_MAX_HANDOFF_MATCHES = 50
_MAX_CODE_SYMBOLS = 20
_PATH_SEPARATOR = "/"
_MULTI_SLASH = re.compile(r"/+")


@dataclass(frozen=True)
class _PathQuery:
    raw: str
    normalized: str
    basename: str
    exact_needles: tuple[str, ...]


@dataclass
class _CollectedContext:
    items: list[FileContextItem] = field(default_factory=list)
    code_evidence: list[CodeEvidence] = field(default_factory=list)
    key_file_match: bool = False
    stale_code_reference: bool = False
    current_truth_timestamps: list[datetime] = field(default_factory=list)
    recent_edit_timestamps: list[datetime] = field(default_factory=list)

    def extend(self, other: "_CollectedContext") -> None:
        self.items.extend(other.items)
        self.code_evidence.extend(other.code_evidence)
        self.key_file_match = self.key_file_match or other.key_file_match
        self.stale_code_reference = (
            self.stale_code_reference or other.stale_code_reference
        )
        self.current_truth_timestamps.extend(other.current_truth_timestamps)
        self.recent_edit_timestamps.extend(other.recent_edit_timestamps)


@dataclass(frozen=True)
class _CodeContext:
    fingerprint: FileFingerprint | None = None
    symbols: tuple[CodeSymbol, ...] = ()
    evidence: tuple[CodeEvidence, ...] = ()
    items: tuple[FileContextItem, ...] = ()


async def build_file_context(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    path: str,
    project_root: str | None = None,
) -> FileContextResult:
    """Return a compact, source-attributed memory view for a file path."""
    resolved_project = resolve_project_name(
        project_name,
        required=False,
        action_label="file-context",
    )
    raw_path = path.strip()
    normalized_path = _normalize_path(raw_path)
    if not normalized_path:
        return FileContextResult(
            project_name=resolved_project,
            path=raw_path,
            normalized_path="",
            path_provided=False,
            notice="no path provided",
            items=[],
            cost_hint=CostHint(estimated_tokens=0, disclosure_level="L0"),
            stale_file_signal=StaleFileSignal(
                state="none",
                reason="no staleness detected",
            ),
        )
    if not resolved_project:
        raise ValueError(
            "project_name is required when no active project is set "
            "(pass project_name, set HARNESS_MEM_PROJECT, or set an active project)"
        )

    profile = await LocalProjectProfileStore(backend.data_dir).get(resolved_project)
    query = _prepare_query(raw_path, normalized_path, profile)
    code_context = _collect_code_context(
        raw_path,
        query.normalized,
        project_root=project_root,
    )
    collected = _CollectedContext()
    collected.items.extend(code_context.items)
    collected.extend(_collect_profile_key_file_matches(profile, query))
    collected.extend(await _collect_knowledge_matches(backend, resolved_project, query))
    collected.extend(await _collect_recent_handoff_matches(backend, resolved_project, query))
    collected.extend(await _collect_observation_matches(backend, resolved_project, query))

    return FileContextResult(
        project_name=resolved_project,
        path=raw_path,
        normalized_path=query.normalized,
        items=collected.items,
        file_fingerprint=code_context.fingerprint,
        code_symbols=list(code_context.symbols),
        code_evidence=[*code_context.evidence, *collected.code_evidence],
        cost_hint=_compute_cost_hint(collected.items),
        stale_file_signal=_compute_stale_signal(
            profile=profile,
            key_file_match=collected.key_file_match,
            stale_code_reference=collected.stale_code_reference,
            items=collected.items,
            current_truth_timestamps=collected.current_truth_timestamps,
            recent_edit_timestamps=collected.recent_edit_timestamps,
        ),
    )


def _normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", _PATH_SEPARATOR)
    normalized = _MULTI_SLASH.sub(_PATH_SEPARATOR, normalized)
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip(_PATH_SEPARATOR)


def _prepare_query(
    raw_path: str,
    normalized_path: str,
    profile: ProjectProfile | None,
) -> _PathQuery:
    exact_needles = {
        raw_path,
        normalized_path,
        normalized_path.replace(_PATH_SEPARATOR, "\\"),
    }
    normalized_query = normalized_path.lower()
    for key_file in profile.key_files if profile else []:
        normalized_key_file = _normalize_path(key_file)
        if not normalized_key_file:
            continue
        lowered = normalized_key_file.lower()
        if _same_path(normalized_query, lowered):
            exact_needles.add(normalized_key_file)
            exact_needles.add(normalized_key_file.replace(_PATH_SEPARATOR, "\\"))
    basename = normalized_path.split(_PATH_SEPARATOR)[-1]
    ordered_needles = tuple(
        sorted(
            {needle for needle in exact_needles if needle},
            key=len,
            reverse=True,
        )
    )
    return _PathQuery(
        raw=raw_path,
        normalized=normalized_path,
        basename=basename,
        exact_needles=ordered_needles,
    )


def _same_path(left: str, right: str) -> bool:
    return left == right or left.endswith(f"/{right}") or right.endswith(f"/{left}")


def _text_matches(text: str, query: _PathQuery) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in query.exact_needles)


def _truncate_summary(text: str, *, max_chars: int = 200) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1].rstrip() + "\u2026"


def _collect_code_context(
    raw_path: str,
    normalized_path: str,
    *,
    project_root: str | None,
) -> _CodeContext:
    file_path = _resolve_existing_file(
        raw_path,
        normalized_path,
        project_root=project_root,
    )
    if file_path is None:
        return _CodeContext()

    try:
        data = file_path.read_bytes()
        stat = file_path.stat()
    except OSError:
        return _CodeContext()

    digest = hashlib.sha256(data).hexdigest()
    source_id = _code_file_source_id(normalized_path, digest)
    fingerprint = FileFingerprint(
        source_id=source_id,
        path=normalized_path,
        sha256=digest,
        size_bytes=len(data),
        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
    )
    text = _decode_text(data)
    symbols = _extract_code_symbols(text, digest, file_path.suffix)
    evidence = [
        CodeEvidence(
            source_id=source_id,
            path=normalized_path,
            fingerprint=digest,
            kind="file",
            current_fingerprint=digest,
        ),
        *[
            CodeEvidence(
                source_id=symbol.source_id,
                path=normalized_path,
                fingerprint=digest,
                line_range=(symbol.line_start, symbol.line_end),
                symbol=symbol.name,
                kind=symbol.kind,
                current_fingerprint=digest,
                line_range_status="valid",
            )
            for symbol in symbols
        ],
    ]
    items = [
        FileContextItem(
            kind="code_fingerprint",
            source_ids=[source_id],
            why_included="current_code:file_fingerprint",
            summary=_truncate_summary(
                f"current file sha256={digest[:16]} size={len(data)} bytes"
            ),
            truth_status="reference",
        ),
        *[
            FileContextItem(
                kind="module_dependency" if symbol.kind == "import" else "code_symbol",
                source_ids=[symbol.source_id],
                why_included="current_code:code_symbol",
                summary=_truncate_summary(
                    f"{symbol.kind} {symbol.name} lines {symbol.line_start}-{symbol.line_end}"
                ),
                truth_status="reference",
            )
            for symbol in symbols[:_MAX_CODE_SYMBOLS]
        ],
    ]
    return _CodeContext(
        fingerprint=fingerprint,
        symbols=tuple(symbols),
        evidence=tuple(evidence),
        items=tuple(items),
    )


def _resolve_existing_file(
    raw_path: str,
    normalized_path: str,
    *,
    project_root: str | None,
) -> Path | None:
    raw = Path(raw_path)
    candidates = [raw] if raw.is_absolute() else []
    root = Path(project_root).expanduser() if project_root else None
    if root is not None and not raw.is_absolute():
        candidates.extend([root / raw_path, root / normalized_path])
    if not raw.is_absolute():
        candidates.extend([Path.cwd() / raw_path, Path.cwd() / normalized_path])
    normalized = Path(normalized_path)
    if normalized.is_absolute():
        candidates.append(normalized)

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_code_symbols(
    text: str,
    file_digest: str,
    suffix: str,
) -> tuple[CodeSymbol, ...]:
    if suffix != ".py":
        return ()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()

    symbols: list[CodeSymbol] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append(_symbol_from_node(node.name, "class", node, file_digest))
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append(
                _symbol_from_node(node.name, "async_function", node, file_digest)
            )
        elif isinstance(node, ast.FunctionDef):
            symbols.append(_symbol_from_node(node.name, "function", node, file_digest))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                symbols.append(
                    _symbol_from_node(alias.name, "import", node, file_digest)
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            symbols.append(_symbol_from_node(node.module, "import", node, file_digest))
    symbols.sort(key=lambda item: (item.line_start, item.kind, item.name))
    return tuple(symbols[:_MAX_CODE_SYMBOLS])


def _symbol_from_node(
    name: str,
    kind: str,
    node: ast.AST,
    file_digest: str,
) -> CodeSymbol:
    line_start = int(getattr(node, "lineno", 1) or 1)
    line_end = int(getattr(node, "end_lineno", line_start) or line_start)
    return CodeSymbol(
        source_id=_code_symbol_source_id(file_digest, kind, name, line_start),
        name=name,
        kind=kind,  # type: ignore[arg-type]
        line_start=line_start,
        line_end=max(line_start, line_end),
    )


def _code_file_source_id(normalized_path: str, file_digest: str) -> str:
    path_digest = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:8]
    return f"code-file:{path_digest}:{file_digest[:12]}"


def _code_symbol_source_id(
    file_digest: str,
    kind: str,
    name: str,
    line_start: int,
) -> str:
    raw = f"{file_digest}:{kind}:{name}:{line_start}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"code-symbol:{digest}"


def _collect_profile_key_file_matches(
    profile: ProjectProfile | None,
    query: _PathQuery,
) -> _CollectedContext:
    if profile is None or not profile.id:
        return _CollectedContext()

    items: list[FileContextItem] = []
    matched = False
    lowered_query = query.normalized.lower()
    for key_file in profile.key_files:
        normalized_key_file = _normalize_path(key_file)
        if not normalized_key_file or not _same_path(lowered_query, normalized_key_file.lower()):
            continue
        matched = True
        items.append(
            FileContextItem(
                kind="project_profile_key_file",
                source_ids=[profile.id],
                why_included="path_association:project_profile_key_file",
                summary=_truncate_summary(f"key file: {normalized_key_file}"),
                truth_status="reference",
            )
        )
    return _CollectedContext(items=items, key_file_match=matched)


async def _collect_observation_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    matches_by_id: dict[str, FileContextItem] = {}
    timestamps: list[datetime] = []
    for needle in query.exact_needles:
        matches = await regex_search_observations(
            backend,
            project_name=project_name,
            pattern=f"(?i){re.escape(needle)}",
            limit=_MAX_OBSERVATION_MATCHES,
        )
        for match in matches:
            observation = match.observation
            if not observation.id or observation.id in matches_by_id:
                continue
            timestamps.append(observation.timestamp)
            matches_by_id[observation.id] = FileContextItem(
                kind="observation",
                source_ids=[observation.id],
                why_included="recent_edit:observation",
                summary=_truncate_summary(match.snippet),
                truth_status="reference",
                drilldown=DrilldownPointer(
                    source_id=observation.id,
                    read_surface="read_api.get_observations",
                    locator={
                        "project_name": project_name,
                        "session_id": observation.session_id,
                    },
                ),
            )
    items = sorted(matches_by_id.values(), key=lambda item: item.source_ids[0])
    return _CollectedContext(items=items, recent_edit_timestamps=timestamps)


async def _collect_knowledge_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    entries = await backend.structured_store.knowledge_store.list_entries(project_name)
    items: list[FileContextItem] = []
    timestamps: list[datetime] = []
    seen_ids: set[str] = set()
    for entry in entries:
        haystack = " ".join([entry.title, entry.statement, *entry.module_path])
        if not entry.id or entry.id in seen_ids or not _text_matches(haystack, query):
            continue
        seen_ids.add(entry.id)
        timestamps.append(entry.updated_at)
        items.append(
            FileContextItem(
                kind="knowledge_entry",
                source_ids=[entry.id],
                why_included="path_association:current_knowledge",
                summary=_truncate_summary(entry.statement),
                truth_status="confirmed_current",
                drilldown=DrilldownPointer(
                    source_id=entry.id,
                    read_surface="mcp.search_memory",
                    locator={
                        "project_name": project_name,
                        "query": query.basename or query.normalized,
                    },
                ),
            )
        )
    return _CollectedContext(
        items=items,
        current_truth_timestamps=timestamps,
    )


async def _collect_recent_handoff_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    handoffs: list[TaskHandoff] = await backend.structured_store.get_latest_handoffs(
        project_name,
        limit=_MAX_HANDOFF_MATCHES,
    )
    items: list[FileContextItem] = []
    timestamps: list[datetime] = []
    for handoff in handoffs:
        if not handoff.id:
            continue
        haystack = " ".join(
            [
                handoff.summary,
                " ".join(handoff.next_steps),
                " ".join(handoff.blockers),
                json.dumps(handoff.context, default=str, ensure_ascii=False),
            ]
        )
        if not _text_matches(haystack, query):
            continue
        timestamps.append(handoff.last_activity)
        items.append(
            FileContextItem(
                kind="task_handoff",
                source_ids=[handoff.id],
                why_included="recent_edit:task_handoff",
                summary=_truncate_summary(handoff.summary),
                truth_status="reference",
                drilldown=DrilldownPointer(
                    source_id=handoff.id,
                    read_surface="mcp.get_task_handoffs",
                    locator={"project_name": project_name},
                ),
            )
        )
    return _CollectedContext(items=items, recent_edit_timestamps=timestamps)


def _compute_cost_hint(items: list[FileContextItem]) -> CostHint:
    chars = sum(len(item.summary) for item in items)
    estimated_tokens = chars_to_tokens(chars)
    return CostHint(
        estimated_tokens=estimated_tokens,
        disclosure_level=disclosure_level(estimated_tokens),
    )


def _compute_stale_signal(
    *,
    profile: ProjectProfile | None,
    key_file_match: bool,
    stale_code_reference: bool,
    items: list[FileContextItem],
    current_truth_timestamps: list[datetime],
    recent_edit_timestamps: list[datetime],
) -> StaleFileSignal:
    if stale_code_reference:
        return StaleFileSignal(
            state="possibly_stale",
            reason=(
                "memory code evidence is stale, incomplete, or cannot be "
                "checked against the current local file"
            ),
        )
    has_confirmed_current = any(item.truth_status == "confirmed_current" for item in items)
    if (
        profile is not None
        and profile.key_files
        and not key_file_match
        and items
        and not has_confirmed_current
    ):
        return StaleFileSignal(
            state="historical_path_match",
            reason=(
                "current project key_files do not include this path, but older "
                "memory references were found"
            ),
        )
    if current_truth_timestamps and recent_edit_timestamps:
        newest_truth = max(current_truth_timestamps)
        newest_edit = max(recent_edit_timestamps)
        if newest_truth < newest_edit:
            return StaleFileSignal(
                state="newer_activity_exists",
                reason="newer path-associated activity exists after the stored truth",
            )
    return StaleFileSignal(
        state="none",
        reason="no staleness detected",
    )

    # Keep this module's final line non-empty for diff whitespace checks.
