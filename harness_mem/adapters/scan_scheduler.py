"""Fair recent-plus-backlog transcript scan planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from harness_mem.adapters.protocol import SessionRecord
from harness_mem.adapters.snapshot import TranscriptSyncResult
from harness_mem.core.interfaces.transcript_store import TranscriptStore
from harness_mem.core.schemas.transcript import TranscriptScanFrontier, TranscriptScanRetry


def session_scan_key(session: SessionRecord) -> str:
    """Return a stable ordering key independent of modification time."""

    path = Path(session["path"]).expanduser().resolve(strict=False).as_posix().casefold()
    return f"{path}#{str(session['session_id']).casefold()}"


def normalize_source_root(source_root: Path | str) -> str:
    return Path(source_root).expanduser().resolve(strict=False).as_posix().casefold()


@dataclass
class SessionScanPlan:
    """One bounded recent lane followed by a persistent backlog traversal."""

    sessions: list[SessionRecord]
    frontier: TranscriptScanFrontier
    _store: TranscriptStore
    _backlog_wrap: dict[str, bool] = field(default_factory=dict)
    _lanes: dict[str, str] = field(default_factory=dict)
    _primary_lane: str | None = None
    _cycle_advanced: bool = False
    scanned_keys: list[str] = field(default_factory=list)

    def lane_for(self, session: SessionRecord) -> str:
        return self._lanes.get(session_scan_key(session), "backlog")

    def mark_scanned(self, session: SessionRecord) -> None:
        key = session_scan_key(session)
        self.scanned_keys.append(key)
        if key not in self._backlog_wrap:
            return
        now = datetime.now(timezone.utc)
        if self._backlog_wrap[key] and not self._cycle_advanced:
            self.frontier.scan_cycle += 1
            self.frontier.scanned_in_cycle = 0
            self.frontier.last_completed_cycle_at = now
            self._cycle_advanced = True
        self.frontier.cursor_key = key
        self.frontier.scanned_in_cycle += 1
        self.frontier.last_scanned_at = now

    def mark_failed(self, session: SessionRecord, error: Exception, *, now: datetime | None = None) -> None:
        """Schedule a bounded retry while allowing the backlog cursor to advance."""

        key = session_scan_key(session)
        retry = self.frontier.retry_sources.get(key, TranscriptScanRetry())
        retry.attempts += 1
        # 30 s, 1 min, 2 min ... up to one hour.  The retry lane is independent
        # from normal frontier traversal, so a broken file cannot block history.
        delay_seconds = min(3600, 30 * (2 ** max(0, retry.attempts - 1)))
        current = now or datetime.now(timezone.utc)
        retry.next_retry_at = current + timedelta(seconds=delay_seconds)
        retry.last_error = f"{type(error).__name__}: {error}"[:512]
        retry.updated_at = current
        self.frontier.retry_sources[key] = retry
        self.mark_scanned(session)

    def mark_succeeded(self, session: SessionRecord) -> None:
        self.frontier.retry_sources.pop(session_scan_key(session), None)
        self.mark_scanned(session)

    def advance_lane_turn(self, changed_lane: str | None, *, change_limit: int) -> None:
        """Persist the next one-item lane after the lane that used the slot."""

        if change_limit != 1 or changed_lane not in {"recent", "backlog"}:
            return
        if not any(self.lane_for(session) == "recent" for session in self.sessions):
            return
        if not any(self.lane_for(session) == "backlog" for session in self.sessions):
            return
        self.frontier.next_lane = "backlog" if changed_lane == "recent" else "recent"

    def commit(self) -> None:
        self._store.save_scan_frontier(self.frontier)


@dataclass(frozen=True)
class SessionSyncFailure:
    session: SessionRecord
    error: Exception


@dataclass(frozen=True)
class FairSessionSyncResult:
    ingested: int
    updated: int
    unchanged: int
    sessions_scanned: int
    failures: list[SessionSyncFailure]
    frontier: TranscriptScanFrontier


async def sync_sessions_fairly(
    store: TranscriptStore,
    *,
    project_name: str,
    client: str,
    source_root: Path | str,
    sessions: list[SessionRecord],
    change_limit: int,
    sync_session: Callable[[SessionRecord], Awaitable[TranscriptSyncResult]],
) -> FairSessionSyncResult:
    """Synchronize a bounded change budget while advancing backlog fairly."""

    plan = plan_session_scan(
        store,
        project_name=project_name,
        client=client,
        source_root=source_root,
        sessions=sessions,
        change_limit=change_limit,
    )
    ingested = 0
    updated = 0
    unchanged = 0
    scanned = 0
    failures: list[SessionSyncFailure] = []
    try:
        lane_changes = {"recent": 0, "backlog": 0}
        lane_limits = _lane_change_limits(plan, change_limit)
        deferred: list[SessionRecord] = []
        first_changed_lane: str | None = None
        for session in plan.sessions:
            if ingested + updated >= max(1, int(change_limit)):
                break
            lane = plan.lane_for(session)
            if lane_changes[lane] >= lane_limits[lane]:
                deferred.append(session)
                continue
            scanned += 1
            try:
                result = await sync_session(session)
                if result.action == "ingested":
                    ingested += 1
                    lane_changes[lane] += 1
                    first_changed_lane = first_changed_lane or lane
                elif result.action == "updated":
                    updated += 1
                    lane_changes[lane] += 1
                    first_changed_lane = first_changed_lane or lane
                else:
                    unchanged += 1
                plan.mark_succeeded(session)
            except Exception as exc:  # noqa: BLE001 - report and continue the backlog.
                failures.append(SessionSyncFailure(session=session, error=exc))
                plan.mark_failed(session, exc)

        # If one lane had no changes, use its unused capacity for candidates in
        # the other lane. This keeps a quiet backlog from reducing useful work.
        for session in deferred:
            if ingested + updated >= max(1, int(change_limit)):
                break
            scanned += 1
            try:
                result = await sync_session(session)
                if result.action == "ingested":
                    ingested += 1
                    first_changed_lane = first_changed_lane or plan.lane_for(session)
                elif result.action == "updated":
                    updated += 1
                    first_changed_lane = first_changed_lane or plan.lane_for(session)
                else:
                    unchanged += 1
                plan.mark_succeeded(session)
            except Exception as exc:  # noqa: BLE001 - report and continue the backlog.
                failures.append(SessionSyncFailure(session=session, error=exc))
                plan.mark_failed(session, exc)

        # Every adapter supplies an untruncated inventory for its project scope.
        # Absence updates lifecycle state only; immutable source revisions stay
        # in the ledger and can be reconstructed after host-side deletion.
        store.mark_sources_missing_from_inventory(
            project_name=project_name,
            client=client,
            observed_session_ids={str(session["session_id"]) for session in sessions},
        )
        plan.advance_lane_turn(first_changed_lane, change_limit=change_limit)
    finally:
        plan.commit()
    return FairSessionSyncResult(
        ingested=ingested,
        updated=updated,
        unchanged=unchanged,
        sessions_scanned=scanned,
        failures=failures,
        frontier=plan.frontier,
    )


def plan_session_scan(
    store: TranscriptStore,
    *,
    project_name: str,
    client: str,
    source_root: Path | str,
    sessions: list[SessionRecord],
    change_limit: int,
) -> SessionScanPlan:
    """Reserve recent capacity while making durable progress through backlog."""

    root = normalize_source_root(source_root)
    frontier = store.get_scan_frontier(
        project_name=project_name,
        client=client,
        source_root=root,
    ) or TranscriptScanFrontier(
        project_name=project_name,
        client=client,
        source_root=root,
    )
    if not sessions:
        return SessionScanPlan([], frontier, store)

    total_budget = max(1, int(change_limit))
    # This is a probe budget, not a changed-session limit.  Full content is
    # still hashed by the adapter before a source is called unchanged.
    probe_budget = max(4, total_budget * 4)
    # A wider probe window must not also widen the recent lane. Keep the
    # original half-budget reservation so the backlog keeps receiving slots.
    recent_budget = max(1, (total_budget + 1) // 2)
    recent = sessions[:recent_budget]
    recent_keys = {session_scan_key(session) for session in recent}

    ordered = sorted(sessions, key=session_scan_key)
    keys = [session_scan_key(session) for session in ordered]
    start = 0
    wrap_at_start = False
    if frontier.cursor_key:
        try:
            start = keys.index(frontier.cursor_key) + 1
            if start >= len(ordered):
                start = 0
                wrap_at_start = True
        except ValueError:
            start = 0
            wrap_at_start = True

    traversal = [*ordered[start:], *ordered[:start]]
    wrapped_flags = [wrap_at_start] * (len(ordered) - start) + [True] * start
    backlog: list[SessionRecord] = []
    backlog_wrap: dict[str, bool] = {}
    for session, wrapped in zip(traversal, wrapped_flags):
        key = session_scan_key(session)
        if key in recent_keys:
            continue
        backlog.append(session)
        backlog_wrap[key] = wrapped

    retry_due = {
        key
        for key, retry in frontier.retry_sources.items()
        if retry.next_retry_at is None or retry.next_retry_at <= datetime.now(timezone.utc)
    }
    backlog_by_key = {session_scan_key(session): session for session in backlog}
    recent_by_key = {session_scan_key(session): session for session in recent}
    retry_sessions: list[SessionRecord] = []
    for key in sorted(retry_due):
        retry_session = backlog_by_key.get(key) or recent_by_key.get(key)
        if retry_session is not None:
            retry_sessions.append(retry_session)
        if len(retry_sessions) >= max(1, total_budget):
            break
    # Pending retries must not immediately re-enter normal traversal. They get
    # another chance only through the due-retry lane after their backoff ends.
    retry_keys = set(frontier.retry_sources)
    recent = [session for session in recent if session_scan_key(session) not in retry_keys]
    backlog = [session for session in backlog if session_scan_key(session) not in retry_keys]

    primary_lane = frontier.next_lane if recent and backlog else ("recent" if recent else "backlog")
    ordered_lanes = (recent, backlog) if primary_lane == "recent" else (backlog, recent)
    candidates: list[SessionRecord] = [*retry_sessions]
    lanes: dict[str, str] = {session_scan_key(session): "backlog" for session in retry_sessions}
    for index in range(max(len(recent), len(backlog))):
        for lane_sessions in ordered_lanes:
            if index >= len(lane_sessions) or len(candidates) >= probe_budget:
                continue
            session = lane_sessions[index]
            candidates.append(session)
            lanes[session_scan_key(session)] = "recent" if lane_sessions is recent else "backlog"

    return SessionScanPlan(
        sessions=candidates,
        frontier=frontier,
        _store=store,
        _backlog_wrap=backlog_wrap,
        _lanes=lanes,
        _primary_lane=primary_lane,
    )


def _lane_change_limits(plan: SessionScanPlan, change_limit: int) -> dict[str, int]:
    """Reserve changed-session capacity for both lanes whenever they exist."""

    total = max(1, int(change_limit))
    has_recent = any(plan.lane_for(session) == "recent" for session in plan.sessions)
    has_backlog = any(plan.lane_for(session) == "backlog" for session in plan.sessions)
    if not has_recent or not has_backlog:
        return {"recent": total, "backlog": total}
    if total == 1:
        primary = plan._primary_lane or "recent"
        return {
            primary: 1,
            "backlog" if primary == "recent" else "recent": 0,
        }
    recent_limit = (total + 1) // 2
    return {"recent": recent_limit, "backlog": total - recent_limit}


__all__ = [
    "SessionScanPlan",
    "FairSessionSyncResult",
    "SessionSyncFailure",
    "normalize_source_root",
    "plan_session_scan",
    "session_scan_key",
    "sync_sessions_fairly",
]
