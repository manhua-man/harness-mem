"""Fail-closed cleanup of native, file-per-session transcript sources.

This module deliberately does not delete shared SQLite databases or shared
JSONL history files.  Adapters that expose one logical session through a
shared container return ``unsupported`` until a transactional, host-specific
row/record cleanup exists.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import importlib
import os
import re
import sqlite3
import stat
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence
from urllib.parse import urlsplit
from urllib.request import url2pathname

from harness_mem.core.schemas.transcript import TranscriptSource

CleanupActionKind = Literal["file", "directory"]
CleanupStatus = Literal["deleted", "retained", "partial_failure", "unsupported"]
ManifestEntryKind = Literal["file", "directory"]

_SHARED_SOURCE_KINDS = {
    "sqlite-session-export",
    "antigravity-cli-session-export",
}
_FILE_CLIENTS = {
    "claude-code",
    "codex",
    "codex-archive",
    "cursor",
    "grok",
    "hermes",
    "antigravity",
}


@dataclass(frozen=True)
class NativeCleanupManifestEntry:
    """One relative, content-addressed entry captured during preview."""

    relative_path: str
    kind: ManifestEntryKind
    size_bytes: int
    mtime_ns: int
    sha256: str | None = None


@dataclass(frozen=True)
class NativeCleanupAction:
    """One bounded filesystem action held only in the in-memory plan."""

    kind: CleanupActionKind
    target: Path
    allowed_root: Path
    expected_manifest: tuple[NativeCleanupManifestEntry, ...] | None = None

    @property
    def locator_sha256(self) -> str:
        return _locator_digest(self.target)


@dataclass(frozen=True)
class NativeCleanupPlan:
    """Validated preview for one native source cleanup."""

    source_id: str
    client: str
    source_revision: str
    locator_sha256: str
    actions: tuple[NativeCleanupAction, ...] = ()
    verification_path: Path | None = None
    expected_native_sha256: str | None = None
    expected_mtime_ns: int | None = None
    activity_lock_path: Path | None = None
    task_state_db_path: Path | None = None
    activity_session_id: str | None = None
    quiet_seconds: int = 60
    supported: bool = True
    retained: bool = False
    reason_codes: tuple[str, ...] = ()

    def to_preview(self) -> dict:
        """Return a content- and path-free preview suitable for an MCP result."""

        return {
            "supported": self.supported,
            "retained": self.retained,
            "reason_codes": list(self.reason_codes),
            "counts": {"planned": len(self.actions)},
            "locator_sha256": self.locator_sha256,
        }


def plan_native_source_cleanup(
    source: TranscriptSource,
    *,
    quiet_seconds: int = 60,
    now: datetime | None = None,
) -> NativeCleanupPlan:
    """Build a bounded cleanup plan without changing native host state."""

    quiet_seconds = max(0, int(quiet_seconds))
    locator_uri = str(source.metadata.get("native_source_uri") or source.source_uri)
    locator_sha256 = hashlib.sha256(locator_uri.encode("utf-8")).hexdigest()
    if source.source_kind in _SHARED_SOURCE_KINDS:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            "shared_source_requires_transactional_cleanup",
        )
    if source.client not in _FILE_CLIENTS:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            "native_source_cleanup_unsupported_client",
        )

    try:
        source_path = _path_from_file_uri(locator_uri, allow_fragment=False)
    except ValueError as exc:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            str(exc),
        )

    roots = _allowed_roots(source)
    root = _containing_root(source_path, roots)
    if root is None:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            "native_source_outside_allowed_roots",
        )

    activity_lock_path = _codex_activity_lock_path(source, roots)
    activity_state = _probe_activity_lock(activity_lock_path)
    if activity_state == "active":
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            activity_lock_path=activity_lock_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_active_writer",),
        )
    if activity_state == "unknown":
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            activity_lock_path=activity_lock_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_liveness_unknown",),
        )
    task_state_db_path = _codex_task_state_db_path(source, roots)
    task_state = _probe_codex_task_activity(task_state_db_path, source.session_id)
    if task_state == "active":
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_active_task",),
        )
    if task_state == "unknown":
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_liveness_unknown",),
        )

    shape_reason = _validate_source_shape(source, source_path, root)
    if shape_reason is not None:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            shape_reason,
        )

    # Reject the locator itself before building manifests.  On platforms that
    # support symlinks, manifest construction deliberately raises for a link;
    # treating that as a generic preview race would incorrectly report the
    # source as merely retained instead of fail-closing the cleanup request.
    # This check is unconditional so broken links are rejected as well.
    if _is_link_or_reparse(source_path):
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            "native_source_not_regular_file",
        )

    actions = _actions_for_source(source, source_path, roots)
    if not actions:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            "native_source_shape_unsupported",
        )
    try:
        actions = _actions_with_manifests(actions)
    except OSError:
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            actions=tuple(actions),
            verification_path=source_path,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_action_changed_during_preview",),
        )

    if not source_path.exists():
        expected_digest = _expected_native_digest(source)
        resume_plan = NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            actions=tuple(actions),
            verification_path=source_path,
            expected_native_sha256=expected_digest,
            expected_mtime_ns=source.mtime_ns,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
        )
        primary_index = _primary_action_index(actions, source_path)
        primary_claim_exists = bool(
            primary_index is not None
            and _claim_path(resume_plan, actions[primary_index]).exists()
        )
        if primary_claim_exists and expected_digest is not None:
            unsafe_reason = _preflight_actions_and_claims(resume_plan)
            if unsafe_reason is not None:
                return _unsupported_plan(
                    source,
                    locator_sha256,
                    quiet_seconds,
                    unsafe_reason,
                )
            return resume_plan
        if any(action.target.exists() for action in actions):
            return NativeCleanupPlan(
                source_id=source.id,
                client=source.client,
                source_revision=source.source_revision,
                locator_sha256=locator_sha256,
                actions=tuple(actions),
                verification_path=source_path,
                activity_lock_path=activity_lock_path,
                task_state_db_path=task_state_db_path,
                activity_session_id=source.session_id,
                quiet_seconds=quiet_seconds,
                retained=True,
                reason_codes=("native_source_missing_with_residual_artifacts",),
            )
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            actions=tuple(actions),
            verification_path=source_path,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            reason_codes=("native_source_already_absent",),
        )
    if not source_path.is_file() or _is_link_or_reparse(source_path):
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            "native_source_not_regular_file",
        )

    stat_result = source_path.stat()
    current_time = now or datetime.now(timezone.utc)
    if current_time.timestamp() - stat_result.st_mtime < quiet_seconds:
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            actions=tuple(actions),
            verification_path=source_path,
            expected_mtime_ns=stat_result.st_mtime_ns,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_not_quiet",),
        )

    expected_digest = _expected_native_digest(source)
    if expected_digest is None:
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            actions=tuple(actions),
            verification_path=source_path,
            expected_mtime_ns=stat_result.st_mtime_ns,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_digest_unavailable",),
        )
    if _sha256_file(source_path) != expected_digest:
        return NativeCleanupPlan(
            source_id=source.id,
            client=source.client,
            source_revision=source.source_revision,
            locator_sha256=locator_sha256,
            actions=tuple(actions),
            verification_path=source_path,
            expected_native_sha256=expected_digest,
            expected_mtime_ns=stat_result.st_mtime_ns,
            activity_lock_path=activity_lock_path,
            task_state_db_path=task_state_db_path,
            activity_session_id=source.session_id,
            quiet_seconds=quiet_seconds,
            retained=True,
            reason_codes=("native_source_changed",),
        )

    unsafe_reason = _preflight_actions(actions)
    if unsafe_reason is not None:
        return _unsupported_plan(
            source,
            locator_sha256,
            quiet_seconds,
            unsafe_reason,
        )
    return NativeCleanupPlan(
        source_id=source.id,
        client=source.client,
        source_revision=source.source_revision,
        locator_sha256=locator_sha256,
        actions=tuple(actions),
        verification_path=source_path,
        expected_native_sha256=expected_digest,
        expected_mtime_ns=stat_result.st_mtime_ns,
        activity_lock_path=activity_lock_path,
        task_state_db_path=task_state_db_path,
        activity_session_id=source.session_id,
        quiet_seconds=quiet_seconds,
    )


def apply_native_source_cleanup(plan: NativeCleanupPlan) -> dict:
    """Atomically claim, verify, and remove one native source revision.

    Every target is first renamed within its existing parent directory.  The
    digest is checked on that claimed filesystem object, so a host reopening
    the original locator creates a new object that this cleanup never removes.
    A failed verification restores all claims when their original names remain
    free; otherwise the claimed bytes are retained for a later safe recovery.
    """

    if not plan.supported:
        return _result(plan, "unsupported", reason_codes=plan.reason_codes)
    if plan.retained:
        return _result(plan, "retained", reason_codes=plan.reason_codes)
    activity_state = _probe_activity_lock(plan.activity_lock_path)
    if activity_state == "active":
        return _result(
            plan,
            "retained",
            reason_codes=("native_source_reactivated_before_claim",),
        )
    if activity_state == "unknown":
        return _result(
            plan,
            "retained",
            reason_codes=("native_source_liveness_unknown",),
        )
    session_id = str(plan.activity_session_id or "")
    task_state = _probe_codex_task_activity(plan.task_state_db_path, session_id)
    if task_state == "active":
        return _result(
            plan,
            "retained",
            reason_codes=("native_source_reactivated_before_claim",),
        )
    if task_state == "unknown":
        return _result(
            plan,
            "retained",
            reason_codes=("native_source_liveness_unknown",),
        )
    verification_path = plan.verification_path
    if verification_path is None:
        return _result(plan, "partial_failure", reason_codes=("invalid_cleanup_plan",))
    primary_index = _primary_action_index(plan.actions, verification_path)
    if primary_index is None:
        return _result(
            plan,
            "partial_failure",
            reason_codes=("native_source_action_missing",),
        )
    unsafe_reason = _preflight_actions_and_claims(plan)
    if unsafe_reason is not None:
        return _result(
            plan,
            "partial_failure",
            reason_codes=(unsafe_reason,),
        )

    primary_action = plan.actions[primary_index]
    companions = [
        action for index, action in enumerate(plan.actions) if index != primary_index
    ]
    claims: list[tuple[NativeCleanupAction, Path]] = []
    skipped_actions: list[NativeCleanupAction] = []
    try:
        primary_claim = _claim_action(plan, primary_action)
        if primary_claim is None:
            if all(
                not action.target.exists() and not _claim_path(plan, action).exists()
                for action in plan.actions
            ):
                # A vanished locator is not proof that this cleanup deleted it.
                # Successful replays are answered from the persisted completion
                # receipt before reaching this function; an unclaimed plan must
                # fail closed when the host moved or removed the source.
                return _result(
                    plan,
                    "partial_failure",
                    reason_codes=("native_source_missing_before_claim",),
                    skipped=len(plan.actions),
                )
            return _result(
                plan,
                "retained",
                reason_codes=("native_source_missing_with_residual_artifacts",),
            )
        claims.append((primary_action, primary_claim))
        claimed_verification = _claimed_verification_path(
            primary_action,
            primary_claim,
            verification_path,
        )
        mismatch = _claimed_source_mismatch(plan, claimed_verification)
        if mismatch is None:
            mismatch = _claimed_action_mismatch(primary_action, primary_claim)
        if mismatch is not None:
            restore_failed = _restore_claims(claims)
            return _result(
                plan,
                "partial_failure" if restore_failed else "retained",
                reason_codes=(
                    "native_claim_restore_conflict" if restore_failed else mismatch,
                ),
            )

        for action in companions:
            claim = _claim_action(plan, action)
            if claim is None:
                skipped_actions.append(action)
                continue
            claims.append((action, claim))
    except OSError:
        restore_failed = _restore_claims(claims)
        return _result(
            plan,
            "partial_failure",
            reason_codes=(
                "native_claim_restore_conflict"
                if restore_failed
                else "native_source_claim_failed",
            ),
        )

    claimed_verification = _claimed_verification_path(
        primary_action,
        primary_claim,
        verification_path,
    )
    mismatch = _claimed_source_mismatch(plan, claimed_verification)
    if mismatch is None:
        mismatch = _claimed_actions_mismatch(claims)
    if mismatch is not None:
        restore_failed = _restore_claims(claims)
        return _result(
            plan,
            "partial_failure" if restore_failed else "retained",
            reason_codes=(
                "native_claim_restore_conflict" if restore_failed else mismatch,
            ),
        )

    deleted = 0
    failures: list[str] = []
    action_receipts: list[dict] = []
    # Remove companions first and the CAS-bearing primary claim last. If a
    # companion cannot be removed, retaining the primary claim makes the saga
    # resumable without losing the only bytes that prove the source revision.
    deletion_order = [*claims[1:], claims[0]]
    for action, claim in deletion_order:
        action_status = "deleted"
        reason_code: str | None = None
        if action is primary_action and failures:
            action_status = "failed"
            reason_code = "native_primary_delete_deferred"
            failures.append(reason_code)
            action_receipts.append(
                {
                    "kind": action.kind,
                    "locator_sha256": action.locator_sha256,
                    "status": action_status,
                    "reason_code": reason_code,
                }
            )
            continue
        try:
            if action.kind == "file":
                claim.unlink()
                deleted += 1
            else:
                _remove_directory_tree(claim)
                deleted += 1
        except OSError:
            action_status = "failed"
            reason_code = "native_source_delete_failed"
            failures.append(reason_code)
        action_receipt = {
            "kind": action.kind,
            "locator_sha256": action.locator_sha256,
            "status": action_status,
        }
        if reason_code is not None:
            action_receipt["reason_code"] = reason_code
        action_receipts.append(action_receipt)

    for action in skipped_actions:
        action_receipts.append(
            {
                "kind": action.kind,
                "locator_sha256": action.locator_sha256,
                "status": "skipped",
                "reason_code": "already_absent",
            }
        )

    residual = [claim for _action, claim in claims if claim.exists()]
    if residual:
        failures.append("native_source_residual_artifacts")
    status: CleanupStatus = "partial_failure" if failures else "deleted"
    return _result(
        plan,
        status,
        deleted=deleted,
        skipped=len(skipped_actions),
        reason_codes=tuple(dict.fromkeys(failures)),
        action_receipts=action_receipts,
    )


def _codex_activity_lock_path(
    source: TranscriptSource,
    roots: Sequence[Path],
) -> Path | None:
    """Return the Codex writer lock that authoritatively marks a live task.

    Explicit metadata supports isolated fixtures.  Automatic discovery is
    intentionally limited to the native ``~/.codex`` layout so unrelated
    directories named ``sessions`` do not acquire host-specific semantics.
    """

    if source.client not in {"codex", "codex-archive"}:
        return None
    configured = str(source.metadata.get("codex_writer_lock_root_uri") or "").strip()
    if configured:
        try:
            lock_root = _path_from_file_uri(configured, allow_fragment=False)
        except ValueError:
            return Path("")
        return lock_root / f"{source.session_id}.lock"
    for root in roots:
        if root.name in {"sessions", "archived_sessions"} and root.parent.name == ".codex":
            return root.parent / "thread-writer-locks" / f"{source.session_id}.lock"
    return None


def _probe_activity_lock(lock_path: Path | None) -> Literal["active", "inactive", "unknown"]:
    """Probe whether Codex currently holds its per-task writer lock.

    The check tests the OS lock/share state rather than mere file existence, so
    a crash-left, unlocked lock file does not retain a completed task forever.
    """

    if lock_path is None:
        return "inactive"
    if lock_path == Path():
        return "unknown"
    if not lock_path.exists():
        return "inactive"
    if os.name == "nt":
        return _probe_windows_activity_lock(lock_path)
    return _probe_posix_activity_lock(lock_path)


def _codex_task_state_db_path(
    source: TranscriptSource,
    roots: Sequence[Path],
) -> Path | None:
    if source.client not in {"codex", "codex-archive"}:
        return None
    configured = str(source.metadata.get("codex_task_state_db_uri") or "").strip()
    if configured:
        try:
            return _path_from_file_uri(configured, allow_fragment=False)
        except ValueError:
            return Path()
    codex_home = Path.home() / ".codex"
    if any(root.parent == codex_home for root in roots):
        return codex_home / "state_5.sqlite"
    return None


def _probe_codex_task_activity(
    state_db_path: Path | None,
    session_id: str,
) -> Literal["active", "inactive", "unknown"]:
    """Read the durable Codex task state as a second liveness signal.

    An open subagent edge is explicit activity.  User-owned tasks have no
    equivalent status column today, so their durable row is accepted only
    after the writer-lock probe already reported inactive.
    """

    if state_db_path is None:
        return "inactive"
    if state_db_path == Path() or not session_id or not state_db_path.is_file():
        return "unknown"
    try:
        uri = f"file:{state_db_path.as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as connection:
            row = connection.execute(
                "SELECT archived FROM threads WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return "unknown"
            edge = connection.execute(
                "SELECT status FROM thread_spawn_edges WHERE child_thread_id = ?",
                (session_id,),
            ).fetchone()
    except (OSError, sqlite3.Error):
        return "unknown"
    if edge is not None and str(edge[0]).lower() == "open":
        return "active"
    return "inactive"


def _probe_windows_activity_lock(lock_path: Path) -> Literal["active", "inactive", "unknown"]:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(lock_path), 0x80000000, 0, None, 3, 0, None)
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            error = ctypes.get_last_error()
            if error in {32, 33}:  # sharing or lock violation
                return "active"
            if error in {2, 3}:  # raced with normal lock removal
                return "inactive"
            return "unknown"
        kernel32.CloseHandle(handle)
        return "inactive"
    except (AttributeError, OSError, ValueError):
        return "unknown"


def _probe_posix_activity_lock(lock_path: Path) -> Literal["active", "inactive", "unknown"]:
    try:
        fcntl = importlib.import_module("fcntl")

        with lock_path.open("rb") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "active"
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        return "inactive"
    except FileNotFoundError:
        return "inactive"
    except (ImportError, OSError):
        return "unknown"


def _primary_action_index(
    actions: Sequence[NativeCleanupAction],
    verification_path: Path,
) -> int | None:
    for index, action in enumerate(actions):
        if action.target == verification_path:
            return index
        if action.kind == "directory" and _is_relative_to(
            verification_path.resolve(strict=False),
            action.target.resolve(strict=False),
        ):
            return index
    return None


def _claim_path(plan: NativeCleanupPlan, action: NativeCleanupAction) -> Path:
    token_input = (
        f"{plan.source_id}\x1f{plan.source_revision}\x1f{action.locator_sha256}"
    )
    token = hashlib.sha256(token_input.encode("utf-8")).hexdigest()[:24]
    return action.target.parent / f".harness-mem-claim-{token}"


def _claim_action(
    plan: NativeCleanupPlan,
    action: NativeCleanupAction,
) -> Path | None:
    claim = _claim_path(plan, action)
    if claim.exists():
        if action.target.exists():
            raise OSError("claim and original both exist")
        return claim
    if not action.target.exists():
        return None
    os.rename(action.target, claim)
    return claim


def _claimed_verification_path(
    action: NativeCleanupAction,
    claim: Path,
    verification_path: Path,
) -> Path:
    if action.kind == "file":
        return claim
    relative = verification_path.relative_to(action.target)
    return claim / relative


def _claimed_source_mismatch(
    plan: NativeCleanupPlan,
    claimed_verification: Path,
) -> str | None:
    try:
        if not claimed_verification.is_file() or _is_link_or_reparse(
            claimed_verification
        ):
            return "native_source_not_regular_file"
        stat_result = claimed_verification.stat()
        if (
            plan.expected_mtime_ns is None
            or stat_result.st_mtime_ns != plan.expected_mtime_ns
            or plan.expected_native_sha256 is None
            or _sha256_file(claimed_verification) != plan.expected_native_sha256
        ):
            return "native_source_changed_after_claim"
    except OSError:
        return "native_source_verification_failed"
    return None


def _actions_with_manifests(
    actions: Sequence[NativeCleanupAction],
) -> list[NativeCleanupAction]:
    return [
        replace(
            action,
            expected_manifest=(
                _action_manifest(action.target, action.kind)
                if action.target.exists()
                else None
            ),
        )
        for action in actions
    ]


def _claimed_action_mismatch(
    action: NativeCleanupAction,
    claim: Path,
) -> str | None:
    if action.expected_manifest is None:
        return "native_action_manifest_unavailable"
    try:
        current = _action_manifest(claim, action.kind)
    except OSError:
        return "native_action_manifest_verification_failed"
    if current != action.expected_manifest:
        return "native_action_changed_after_preview"
    return None


def _claimed_actions_mismatch(
    claims: Sequence[tuple[NativeCleanupAction, Path]],
) -> str | None:
    for action, claim in claims:
        mismatch = _claimed_action_mismatch(action, claim)
        if mismatch is not None:
            return mismatch
    return None


def _action_manifest(
    root: Path,
    expected_kind: CleanupActionKind,
) -> tuple[NativeCleanupManifestEntry, ...]:
    if _is_link_or_reparse(root):
        raise OSError("links and reparse points are not manifestable")
    if expected_kind == "file":
        if not root.is_file():
            raise OSError("manifest target type changed")
        return (_manifest_entry(root, "."),)
    if not root.is_dir():
        raise OSError("manifest target type changed")

    before = root.stat()
    descendants = sorted(
        root.rglob("*"),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    entries = [_manifest_entry(root, ".")]
    for path in descendants:
        entries.append(_manifest_entry(path, path.relative_to(root).as_posix()))
    after_paths = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    after = root.stat()
    if (
        after_paths != [path.relative_to(root).as_posix() for path in descendants]
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_size != after.st_size
    ):
        raise OSError("directory changed while manifest was built")
    return tuple(entries)


def _manifest_entry(path: Path, relative_path: str) -> NativeCleanupManifestEntry:
    if _is_link_or_reparse(path):
        raise OSError("links and reparse points are not manifestable")
    before = path.stat()
    if path.is_file():
        digest = _sha256_file(path)
        kind: ManifestEntryKind = "file"
    elif path.is_dir():
        digest = None
        kind = "directory"
    else:
        raise OSError("unsupported manifest entry type")
    after = path.stat()
    if (
        before.st_mtime_ns != after.st_mtime_ns
        or before.st_size != after.st_size
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
    ):
        raise OSError("entry changed while manifest was built")
    return NativeCleanupManifestEntry(
        relative_path=relative_path,
        kind=kind,
        size_bytes=after.st_size,
        mtime_ns=after.st_mtime_ns,
        sha256=digest,
    )


def _restore_claims(claims: Sequence[tuple[NativeCleanupAction, Path]]) -> bool:
    failed = False
    for action, claim in reversed(claims):
        if not claim.exists():
            continue
        if action.target.exists():
            failed = True
            continue
        try:
            os.rename(claim, action.target)
        except OSError:
            failed = True
    return failed


def _preflight_actions_and_claims(plan: NativeCleanupPlan) -> str | None:
    reason = _preflight_actions(plan.actions)
    if reason is not None:
        return reason
    for action in plan.actions:
        claim = _claim_path(plan, action)
        if not claim.exists():
            continue
        if action.target.exists():
            return "native_cleanup_claim_conflict"
        if _is_link_or_reparse(claim):
            return "native_cleanup_link_or_reparse_rejected"
        if not _is_relative_to(
            claim.resolve(strict=False),
            action.allowed_root.resolve(strict=False),
        ):
            return "native_cleanup_target_outside_allowed_root"
        if action.kind == "file" and not claim.is_file():
            return "native_cleanup_target_type_mismatch"
        if action.kind == "directory" and not claim.is_dir():
            return "native_cleanup_target_type_mismatch"
        if action.kind == "directory":
            for child in claim.rglob("*"):
                if _is_link_or_reparse(child):
                    return "native_cleanup_link_or_reparse_rejected"
    return None


def cleanup_native_source(
    source: TranscriptSource,
    *,
    quiet_seconds: int = 60,
) -> dict:
    """Preview and apply one native cleanup without exposing its locator."""

    plan = plan_native_source_cleanup(source, quiet_seconds=quiet_seconds)
    return apply_native_source_cleanup(plan)


def path_from_local_file_uri(uri: str, *, allow_fragment: bool = False) -> Path:
    """Decode one absolute local ``file:`` URI without relaxing safety checks."""

    return _path_from_file_uri(uri, allow_fragment=allow_fragment)


def build_native_cleanup_descriptor(
    *,
    client: str,
    source_kind: str,
    source_uri: str,
) -> dict[str, object] | None:
    """Derive the adapter-owned root at capture time for later safe cleanup."""

    if source_kind in _SHARED_SOURCE_KINDS or urlsplit(source_uri).fragment:
        return None
    try:
        path = _path_from_file_uri(source_uri, allow_fragment=False)
    except ValueError:
        return None
    roots: list[Path] = []
    try:
        if client == "claude-code":
            projects_root = path.parents[1]
            if projects_root.name != "projects":
                return None
            roots.extend([projects_root, projects_root.parent / "file-history"])
        elif client == "codex":
            if path.parents[3].name == "sessions":
                roots.append(path.parents[3])
            elif path.parent.name == "archived_sessions":
                roots.append(path.parent)
            else:
                return None
        elif client == "codex-archive":
            if path.parent.name != "archived_sessions":
                return None
            roots.append(path.parent)
        elif client == "cursor":
            if path.parent.parent.name != "agent-transcripts":
                return None
            roots.append(path.parents[3])
        elif client == "grok":
            if path.name != "chat_history.jsonl":
                return None
            roots.append(path.parents[2])
        elif client == "hermes":
            if source_kind != "json":
                return None
            roots.append(path.parent)
        elif client == "antigravity":
            if path.parent.name != "logs":
                return None
            roots.append(path.parents[4])
        else:
            return None
    except IndexError:
        return None
    return {
        "version": 1,
        "allowed_root_uris": [root.absolute().as_uri() for root in roots],
    }


def _actions_for_source(
    source: TranscriptSource,
    path: Path,
    roots: Sequence[Path],
) -> list[NativeCleanupAction]:
    root = _containing_root(path, roots)
    if root is None:
        return []
    actions: list[NativeCleanupAction] = []
    if source.client == "cursor":
        actions.append(NativeCleanupAction("directory", path.parent, root))
    elif source.client == "grok":
        actions.append(NativeCleanupAction("directory", path.parent, root))
    elif source.client == "antigravity":
        bundle = path.parents[2]
        actions.append(NativeCleanupAction("directory", bundle, root))
        host_root = bundle.parent.parent
        for companion in (
            host_root / "annotations" / f"{source.session_id}.pbtxt",
            host_root / "conversations" / f"{source.session_id}.pb",
            host_root / "conversations" / f"{source.session_id}.db",
            host_root / "conversations" / f"{source.session_id}.db-wal",
            host_root / "conversations" / f"{source.session_id}.db-shm",
        ):
            companion_root = _containing_root(companion, roots)
            if companion_root is not None and companion.exists():
                actions.append(NativeCleanupAction("file", companion, companion_root))
    else:
        actions.append(NativeCleanupAction("file", path, root))

    if source.client == "claude-code":
        artifact_dir = path.with_suffix("")
        artifact_root = _containing_root(artifact_dir, roots)
        if artifact_root is not None and artifact_dir.is_dir():
            actions.insert(
                0, NativeCleanupAction("directory", artifact_dir, artifact_root)
            )
        for candidate_root in roots:
            if candidate_root.name != "file-history":
                continue
            file_history = candidate_root / source.session_id
            if file_history.is_dir():
                actions.insert(
                    0,
                    NativeCleanupAction("directory", file_history, candidate_root),
                )
    if source.client == "hermes" and source.source_kind == "json":
        session_tail = source.session_id.removeprefix("session_")
        for companion in path.parent.glob(f"request_dump_{session_tail}_*.json"):
            companion_root = _containing_root(companion, roots)
            if companion_root is not None and companion.is_file():
                actions.insert(
                    0, NativeCleanupAction("file", companion, companion_root)
                )
    return _dedupe_actions(actions)


def _validate_source_shape(
    source: TranscriptSource,
    path: Path,
    root: Path,
) -> str | None:
    del root
    if source.client == "claude-code":
        if path.suffix.lower() != ".jsonl" or path.stem != source.session_id:
            return "native_source_shape_mismatch"
    elif source.client in {"codex", "codex-archive"}:
        if path.suffix.lower() != ".jsonl" or not path.name.startswith("rollout-"):
            return "native_source_shape_mismatch"
        if source.session_id not in path.stem:
            return "native_source_session_mismatch"
    elif source.client == "cursor":
        if (
            path.suffix.lower() != ".jsonl"
            or path.parent.name != source.session_id
            or path.parent.parent.name != "agent-transcripts"
        ):
            return "native_source_shape_mismatch"
    elif source.client == "grok":
        if path.name != "chat_history.jsonl" or path.parent.name != source.session_id:
            return "native_source_shape_mismatch"
    elif source.client == "hermes":
        if source.source_kind != "json" or path.suffix.lower() != ".json":
            return "native_source_shape_mismatch"
        if path.stem != source.session_id:
            return "native_source_session_mismatch"
    elif source.client == "antigravity":
        if source.source_kind not in {"brain-jsonl", "antigravity-cli-transcript"}:
            return "native_source_shape_mismatch"
        if (
            path.suffix.lower() != ".jsonl"
            or path.parent.name != "logs"
            or path.parent.parent.name != ".system_generated"
            or path.parents[2].name != source.session_id
            or not path.name.startswith("transcript")
        ):
            return "native_source_shape_mismatch"
    return None


def _allowed_roots(source: TranscriptSource) -> tuple[Path, ...]:
    descriptor = source.metadata.get("native_cleanup_descriptor")
    configured: list[Path] = []
    if isinstance(descriptor, dict):
        values = descriptor.get("allowed_root_uris") or descriptor.get("allowed_roots")
        if isinstance(values, list):
            for value in values:
                try:
                    if isinstance(value, str) and value.startswith("file:"):
                        configured.append(
                            _path_from_file_uri(value, allow_fragment=False)
                        )
                    elif isinstance(value, str):
                        configured.append(Path(value).expanduser().absolute())
                except ValueError:
                    continue
    if configured:
        return tuple(_normalized_path(path) for path in configured)

    home = Path.home()
    defaults: dict[str, tuple[Path, ...]] = {
        "claude-code": (
            home / ".claude" / "projects",
            home / ".claude" / "file-history",
        ),
        "cursor": (home / ".cursor" / "projects",),
        "codex": (home / ".codex" / "sessions", home / ".codex" / "archived_sessions"),
        "codex-archive": (home / ".codex" / "archived_sessions",),
        "grok": (home / ".grok" / "sessions",),
        "hermes": (home / ".hermes" / "sessions",),
        "antigravity": (home / ".gemini" / "antigravity",),
    }
    return tuple(_normalized_path(path) for path in defaults.get(source.client, ()))


def _expected_native_digest(source: TranscriptSource) -> str | None:
    digest = source.metadata.get("native_input_sha256")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        return digest.lower()
    if int(source.metadata.get("capture_private_spans_removed") or 0) == 0:
        if re.fullmatch(r"[0-9a-fA-F]{64}", source.raw_sha256):
            return source.raw_sha256.lower()
    return None


def _path_from_file_uri(uri: str, *, allow_fragment: bool) -> Path:
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "file":
        raise ValueError("native_source_uri_not_file")
    if parsed.netloc not in {"", "localhost"}:
        raise ValueError("native_source_remote_file_uri")
    if parsed.query or (parsed.fragment and not allow_fragment):
        raise ValueError("native_source_uri_has_unsupported_components")
    # ``url2pathname`` performs percent-decoding on Windows. Decoding before
    # calling it would turn a literal ``%2F`` filename into a path separator.
    decoded = url2pathname(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:[\\/]", decoded):
        decoded = decoded[1:]
    path = Path(decoded).expanduser()
    if not path.is_absolute():
        raise ValueError("native_source_uri_not_absolute")
    return _normalized_path(path)


def _containing_root(path: Path, roots: Sequence[Path]) -> Path | None:
    resolved_path = path.expanduser().resolve(strict=False)
    resolved_roots = [root.expanduser().resolve(strict=False) for root in roots]
    matches = [root for root in resolved_roots if _is_relative_to(resolved_path, root)]
    if not matches:
        return None
    return max(matches, key=lambda item: len(str(item)))


def _normalized_path(path: Path) -> Path:
    # Preserve the final lexical component so link/reparse checks inspect the
    # locator itself instead of silently replacing it with its target.
    return path.expanduser().absolute()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return path != root
    except ValueError:
        return False


def _preflight_actions(actions: Sequence[NativeCleanupAction]) -> str | None:
    for action in actions:
        if not action.target.exists():
            continue
        if _is_link_or_reparse(action.target):
            return "native_cleanup_link_or_reparse_rejected"
        if not _is_relative_to(
            action.target.resolve(strict=False),
            action.allowed_root.resolve(strict=False),
        ):
            return "native_cleanup_target_outside_allowed_root"
        if action.kind == "file" and not action.target.is_file():
            return "native_cleanup_target_type_mismatch"
        if action.kind == "directory":
            if not action.target.is_dir():
                return "native_cleanup_target_type_mismatch"
            for child in action.target.rglob("*"):
                if _is_link_or_reparse(child):
                    return "native_cleanup_link_or_reparse_rejected"
    return None


def _is_link_or_reparse(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return True
    reparse_flag = getattr(stat_result, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag & reparse_point)


def _remove_directory_tree(path: Path) -> None:
    if _is_link_or_reparse(path):
        raise OSError("link or reparse point appeared after preflight")
    children = sorted(
        path.iterdir(), key=lambda item: (item.is_dir(), str(item)), reverse=True
    )
    for child in children:
        if _is_link_or_reparse(child):
            raise OSError("link or reparse point appeared after preflight")
        if child.is_dir():
            _remove_directory_tree(child)
        else:
            child.unlink()
    path.rmdir()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _locator_digest(path: Path) -> str:
    normalized = os.path.normcase(str(path.expanduser().absolute()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dedupe_actions(
    actions: Sequence[NativeCleanupAction],
) -> list[NativeCleanupAction]:
    seen: set[tuple[str, str]] = set()
    result: list[NativeCleanupAction] = []
    for action in actions:
        key = (action.kind, os.path.normcase(str(action.target)))
        if key not in seen:
            result.append(action)
            seen.add(key)
    return result


def _unsupported_plan(
    source: TranscriptSource,
    locator_sha256: str,
    quiet_seconds: int,
    reason_code: str,
) -> NativeCleanupPlan:
    return NativeCleanupPlan(
        source_id=source.id,
        client=source.client,
        source_revision=source.source_revision,
        locator_sha256=locator_sha256,
        quiet_seconds=quiet_seconds,
        supported=False,
        reason_codes=(reason_code,),
    )


def _result(
    plan: NativeCleanupPlan,
    status: CleanupStatus,
    *,
    deleted: int = 0,
    skipped: int = 0,
    reason_codes: Sequence[str] = (),
    action_receipts: Sequence[dict] = (),
) -> dict:
    return {
        "success": status in {"deleted", "retained"},
        "status": status,
        "reason_codes": list(reason_codes),
        "counts": {
            "planned": len(plan.actions),
            "deleted": deleted,
            "skipped": skipped,
            "failed": sum(
                1 for item in action_receipts if item.get("status") == "failed"
            ),
        },
        "locator_sha256": plan.locator_sha256,
        "actions": list(action_receipts),
    }


__all__ = [
    "NativeCleanupAction",
    "NativeCleanupManifestEntry",
    "NativeCleanupPlan",
    "apply_native_source_cleanup",
    "build_native_cleanup_descriptor",
    "path_from_local_file_uri",
    "cleanup_native_source",
    "plan_native_source_cleanup",
]
