"""Recoverable per-archive cleanup of Cursor's two independent WAL stores."""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from typing import Callable, Iterator

from harness_mem.adapters.cursor.search_cleanup import (
    SearchCleanupBlocked, SearchRows, delete_search_rows, restore_search_rows,
    search_rows_absent, search_rows_sha256, select_search_rows,
)
from harness_mem.adapters.cursor.sqlite_cleanup import (
    CursorCleanupBlocked, CursorCleanupPlan, _backup_path, _backup_progress,
    _verified_rows, _verify_no_companions, cursor_cleanup_target, delete_primary_rows,
    primary_absent, primary_witness,
)
from harness_mem.adapters.cursor.sqlite_history import _read_db
from harness_mem.core.schemas.transcript import TranscriptSource


def _backup_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_store(source: Path, target: Path) -> str:
    target.parent.mkdir(exist_ok=True)
    with target.open("xb"):
        pass
    with _read_db(source) as live, closing(sqlite3.connect(target)) as backup:
        live.backup(backup, pages=256, progress=_backup_progress)
    with target.open("r+b") as durable:
        os.fsync(durable.fileno())
    return _backup_digest(target)


def _read_preimages(
    plan: CursorCleanupPlan, data_dir: Path, receipt_id: str, witness: dict,
) -> tuple[CursorCleanupPlan, SearchRows]:
    if (witness.get("version") != 1
            or witness.get("phase") not in ("prepared", "search_committed", "restoring_search", "verified")
            or witness.get("locator_sha256") != plan.locator_sha256
            or not plan.primary_sha256 or witness.get("primary_sha256") != plan.primary_sha256
            or not plan.search_sha256 or witness.get("search_sha256") != plan.search_sha256):
        raise CursorCleanupBlocked("cursor_cross_store_receipt_unverified")
    assert plan.database is not None and plan.search_database is not None
    main = _backup_path(data_dir, receipt_id, kind=".primary")
    search = _backup_path(data_dir, receipt_id, kind=".search")
    if (_backup_digest(main) != witness.get("primary_backup_sha256")
            or _backup_digest(search) != witness.get("search_backup_sha256")):
        raise CursorCleanupBlocked("cursor_cross_store_backup_changed")
    with _read_db(main) as db:
        workspace, keys = _verified_rows(db, plan)
        if primary_witness(db, plan) != witness.get("primary_sha256"):
            raise CursorCleanupBlocked("cursor_cross_store_backup_unverified")
    with _read_db(search) as db:
        rows = select_search_rows(db, plan.session_id)
        if (rows is None or search_rows_sha256(rows) != witness.get("search_sha256")
                or rows.fts_rowid != witness.get("search_rowid")):
            raise CursorCleanupBlocked("cursor_cross_store_backup_unverified")
    return replace(plan, workspace_id=workspace, keys=keys, search_sha256=witness["search_sha256"]), rows


def _state(
    primary: sqlite3.Connection, search: sqlite3.Connection, plan: CursorCleanupPlan,
    rows: SearchRows, witness: dict,
) -> tuple[bool, bool]:
    primary_gone = primary_absent(primary, plan)
    search_gone = search_rows_absent(search, rows)
    if not primary_gone and primary_witness(primary, plan) != witness.get("primary_sha256"):
        raise CursorCleanupBlocked("cursor_cross_store_primary_changed")
    if not search_gone:
        current = select_search_rows(search, plan.session_id)
        if current is None or search_rows_sha256(current) != search_rows_sha256(rows):
            raise CursorCleanupBlocked("cursor_cross_store_search_changed")
    if (primary_gone and witness["phase"] != "verified"
            or search_gone and witness["phase"] in {"prepared", "restoring_search"}
            or witness["phase"] == "verified" and not (primary_gone and search_gone)):
        raise CursorCleanupBlocked("cursor_cross_store_commit_unverified")
    return primary_gone, search_gone


def plan_cursor_cross_recovery(
    source: TranscriptSource, *, data_dir: Path, receipt_id: str, witness: dict,
) -> CursorCleanupPlan:
    """Read-only preview of resuming the exact witnessed cross-store operation."""
    plan = cursor_cleanup_target(source)
    primary_path = plan.database
    assert primary_path is not None
    search_path = primary_path.with_name("conversation-search.db")
    if search_path.resolve() != search_path:
        raise CursorCleanupBlocked("cursor_cross_store_locator_changed")
    plan, rows = _read_preimages(replace(plan, search_database=search_path), data_dir, receipt_id, witness)
    _verify_no_companions(plan, allow_selected_search=True)
    with _read_db(primary_path) as primary, _read_db(search_path) as search:
        _state(primary, search, plan, rows, witness)
    return plan


@contextmanager
def _writer(path: Path) -> Iterator[sqlite3.Connection]:
    if path.resolve() != path:
        raise CursorCleanupBlocked("cursor_cross_store_locator_changed")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.1)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        yield db


def _restore_search_after_failure(
    primary: sqlite3.Connection, search: sqlite3.Connection, plan: CursorCleanupPlan,
    rows: SearchRows, witness: dict,
) -> bool:
    """Restore only the target index when the primary still equals its pre-image."""
    try:
        primary.rollback()
        primary.execute("BEGIN IMMEDIATE")
        if primary_witness(primary, plan) != witness["primary_sha256"]:
            return False
        search.rollback()
        search.execute("BEGIN IMMEDIATE")
        restore_search_rows(search, rows)
        search.commit()
        return True
    except (OSError, ValueError, sqlite3.Error):
        return False


def apply_cursor_cross_cleanup(
    plan: CursorCleanupPlan, *, data_dir: Path, receipt_id: str,
    record_witness: Callable[[dict], None], witness: dict | None = None,
) -> dict:
    """Search commits first. A durable pre-image lets a retry finish or retain safely."""
    primary_path, search_path = plan.database, plan.search_database
    if primary_path is None or search_path is None or plan.retained or not plan.keys:
        return {"status": "retained", "reason_codes": ["cursor_cross_store_invalid_plan"]}
    committed_or_prepared = witness is not None
    try:
        _verify_no_companions(plan, allow_selected_search=True)
        with _writer(primary_path) as primary, _writer(search_path) as search:
            if witness is None:
                if _verified_rows(primary, plan) != (plan.workspace_id, plan.keys):
                    raise CursorCleanupBlocked("cursor_cross_store_primary_changed")
                if not plan.primary_sha256 or primary_witness(primary, plan) != plan.primary_sha256:
                    raise CursorCleanupBlocked("cursor_cleanup_primary_witness_changed_or_missing")
                selected = select_search_rows(search, plan.session_id)
                if selected is None or search_rows_sha256(selected) != plan.search_sha256:
                    raise CursorCleanupBlocked("cursor_cross_store_search_changed")
                witness = {
                    "version": 1, "phase": "prepared", "locator_sha256": plan.locator_sha256,
                    "primary_sha256": plan.primary_sha256,
                    "search_sha256": search_rows_sha256(selected),
                    "search_rowid": selected.fts_rowid,
                }
                for kind, path in (("primary", primary_path), ("search", search_path)):
                    witness[f"{kind}_backup_sha256"] = _copy_store(path, _backup_path(
                        data_dir, receipt_id, kind=f".{kind}",
                    ))
                _plan, rows = _read_preimages(plan, data_dir, receipt_id, witness)
                committed_or_prepared = True
                record_witness(witness)
            else:
                plan, rows = _read_preimages(plan, data_dir, receipt_id, witness)
            primary_gone, search_gone = _state(primary, search, plan, rows, witness)
            if not primary_gone:
                search_commit_proven = search_gone
                try:
                    if not search_gone:
                        delete_search_rows(search, rows)
                        search.commit()
                        search_commit_proven = True
                        search.execute("BEGIN IMMEDIATE")
                        if not search_rows_absent(search, rows):
                            raise CursorCleanupBlocked("cursor_cross_store_search_reappeared")
                    _verify_no_companions(plan, allow_selected_search=True)
                    # Only a positively witnessed search commit authorizes the
                    # second store or compensation after restarting.
                    witness = {**witness, "phase": "search_committed"}
                    record_witness(witness)
                    delete_primary_rows(primary, plan)
                    primary.commit()
                except (OSError, ValueError, sqlite3.Error):
                    if search_commit_proven:
                        # Invalidate the delete witness before putting the search
                        # rows back. A later independent disappearance cannot
                        # reuse the old search commit as recovery authority.
                        record_witness({**witness, "phase": "restoring_search"})
                        if _restore_search_after_failure(primary, search, plan, rows, witness):
                            record_witness({**witness, "phase": "prepared"})
                            return {"status": "partial_failure", "reason_codes": ["cursor_cross_store_search_restored"]}
                    raise
        _verify_no_companions(plan)
        with _read_db(primary_path) as primary, _read_db(search_path) as search:
            if not primary_absent(primary, plan) or not search_rows_absent(search, rows):
                raise CursorCleanupBlocked("cursor_cross_store_commit_unverified")
        if witness["phase"] != "verified":
            record_witness({**witness, "phase": "verified"})
        return {"status": "deleted", "reason_codes": ["cursor_cross_store_rows_deleted"]}
    except (OSError, ValueError, sqlite3.Error) as exc:
        reason = (str(exc) if isinstance(exc, (CursorCleanupBlocked, SearchCleanupBlocked))
                  else "cursor_cross_store_transaction_unavailable")
        return {"status": "partial_failure" if committed_or_prepared else "retained", "reason_codes": [reason]}
