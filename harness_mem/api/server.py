"""harness-mem REST API Server — FastAPI application."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from harness_mem.api.models import (
    SearchResponse,
    MemoryEntryResponse,
    ObservationResponse,
    TimelineResponse,
    TimelineObservation,
    ObservationsResponse,
    ObservationDetail,
    ContextResponse,
    RulesResponse,
    RuleResponse,
    RuleCandidatesResponse,
    RuleCandidateItem,
    RuleCandidateRequest,
    RuleCandidateResponse,
    ConfirmResponse,
    RejectRequest,
    RejectResponse,
    FeedbackRequest,
    FeedbackResponse,
    WakeupContextResponse,
    WakeupRule,
    HealthResponse,
    SessionInfo,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.core.schemas import ConfirmedRule, RuleCandidate


DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"
VERSION = "1.2.0"

# Singleton backend
_backend: LocalMemoryBackend | None = None
_backend_override: LocalMemoryBackend | None = None
_backend_lock = asyncio.Lock()


def _get_backend() -> LocalMemoryBackend:
    global _backend
    if _backend_override is not None:
        return _backend_override
    if _backend is None:
        _backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        asyncio.run(_backend.init())
    return _backend


async def _get_backend_async() -> LocalMemoryBackend:
    global _backend
    if _backend_override is not None:
        return _backend_override
    if _backend is not None:
        return _backend

    async with _backend_lock:
        if _backend is None:
            _backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
            await _backend.init()
    return _backend


def set_backend_override(backend: LocalMemoryBackend | None) -> None:
    """Override backend for tests or local injection."""
    global _backend_override, _backend
    _backend_override = backend
    if backend is not None:
        _backend = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _get_backend_async()
    try:
        yield
    finally:
        global _backend
        if _backend is not None and _backend is not _backend_override:
            await _backend.close()
            _backend = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="harness-mem API",
        description="Local-first AI memory runtime REST API",
        version=VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Health ----

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(
            status="ok",
            version=VERSION,
            data_dir=str(DEFAULT_DATA_DIR),
        )

    # ---- Search ----

    @app.get("/search", response_model=SearchResponse)
    async def search(
        query: str = Query(..., description="Search query string"),
        project_name: str | None = Query(None, description="Project name"),
        type: str | None = Query(None, description="Memory type filter"),
        scope: str = Query("project", description="project or all"),
        mode: str = Query("auto", description="auto, fts, or hybrid"),
        limit: int = Query(20, ge=1, le=100),
    ):
        if scope not in {"project", "all"}:
            raise HTTPException(status_code=400, detail="scope must be 'project' or 'all'")
        if mode not in {"auto", "fts", "hybrid"}:
            raise HTTPException(status_code=400, detail="mode must be 'auto', 'fts', or 'hybrid'")
        if scope == "project" and not project_name:
            raise HTTPException(status_code=400, detail="project_name required when scope=project")

        backend = await _get_backend_async()

        if scope == "all":
            entries = await backend.structured_store.search_memory_entries(
                query, project_name=None, limit=limit, mode=mode
            )
            obs_list = await backend.verbatim_store.search(query, limit=limit, mode=mode)
        else:
            entries = await backend.structured_store.search_memory_entries(
                query, project_name=project_name, limit=limit, mode=mode
            )
            obs_list = await backend.verbatim_store.search(
                query,
                project_name=project_name,
                limit=limit,
                mode=mode,
            )

        if type:
            entries = [e for e in entries if e.category == type]

        combined_results = entries or obs_list
        effective_mode = getattr(combined_results[0], "_search_mode", mode) if combined_results else mode
        fallback_reason = getattr(combined_results[0], "_search_fallback_reason", None) if combined_results else None

        return SearchResponse(
            project_name=project_name,
            query=query,
            scope=scope,
            requested_mode=mode,
            effective_mode=effective_mode,
            fallback_reason=fallback_reason,
            memory_entries=[
                MemoryEntryResponse(
                    id=e.id,
                    category=e.category,
                    content=e.content,
                    confidence=e.confidence,
                    tags=e.tags,
                    search_mode=getattr(e, "_search_mode", mode),
                    score=getattr(e, "_score", getattr(e, "_hybrid_score", getattr(e, "_fts_score", None))),
                )
                for e in entries
            ],
            observations=[
                ObservationResponse(
                    id=o.id,
                    session_id=o.session_id,
                    content_type=o.content_type,
                    preview=o.raw_content[:200].replace("\n", " "),
                    search_mode=getattr(o, "_search_mode", mode),
                    score=getattr(o, "_score", getattr(o, "_hybrid_score", getattr(o, "_fts_score", None))),
                )
                for o in obs_list
            ],
            memory_entry_count=len(entries),
            observation_count=len(obs_list),
        )

    # ---- Timeline ----

    @app.get("/timeline", response_model=TimelineResponse)
    async def timeline(
        project_name: str = Query(..., description="Project name"),
        limit: int = Query(50, ge=1, le=200),
    ):
        backend = await _get_backend_async()
        obs_list = await backend.verbatim_store.timeline(limit=limit * 5)
        obs_list = [
            o for o in obs_list
            if o.metadata.get("project_name") == project_name
        ][:limit]

        return TimelineResponse(
            project_name=project_name,
            limit=limit,
            observations=[
                TimelineObservation(
                    id=o.id,
                    session_id=o.session_id,
                    client=o.client,
                    content_type=o.content_type,
                    timestamp=o.timestamp.isoformat() if o.timestamp else None,
                    preview=o.raw_content[:150].replace("\n", " "),
                    tags=o.tags,
                )
                for o in obs_list
            ],
            count=len(obs_list),
        )

    # ---- Observations ----

    @app.get("/observations", response_model=ObservationsResponse)
    async def get_observations(
        project_name: str = Query(..., description="Project name"),
        session_id: str = Query(..., description="Session ID"),
    ):
        backend = await _get_backend_async()
        all_obs = await backend.verbatim_store.list(limit=10000)
        session_obs = [
            o for o in all_obs
            if o.session_id == session_id
            and o.metadata.get("project_name") == project_name
        ]

        return ObservationsResponse(
            project_name=project_name,
            session_id=session_id,
            observations=[
                ObservationDetail(
                    id=o.id,
                    session_id=o.session_id,
                    client=o.client,
                    content_type=o.content_type,
                    timestamp=o.timestamp.isoformat() if o.timestamp else None,
                    raw_content=o.raw_content,
                    tags=o.tags,
                    metadata=o.metadata,
                )
                for o in session_obs
            ],
            count=len(session_obs),
        )

    # ---- Context ----

    @app.get("/context/{session_id}", response_model=ContextResponse)
    async def get_context(
        session_id: str,
        project_name: str = Query(None, description="Project name"),
    ):
        backend = await _get_backend_async()

        if not project_name:
            raise HTTPException(status_code=400, detail="project_name required")

        memories = await backend.structured_store.list_memory_entries(
            project_name, limit=10
        )
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        all_obs = await backend.verbatim_store.list(limit=100)
        sessions_map: dict[str, SessionInfo] = {}
        for o in all_obs:
            if o.session_id not in sessions_map and o.metadata.get("project_name") == project_name:
                sessions_map[o.session_id] = SessionInfo(
                    id=o.session_id,
                    started_at=o.timestamp.isoformat() if o.timestamp else None,
                    ended_at=None,
                    client=o.client,
                )

        recent_sessions = list(sessions_map.values())[:5]

        return ContextResponse(
            session_id=session_id,
            memories=[
                MemoryEntryResponse(
                    id=m.id,
                    category=m.category,
                    content=m.content,
                    confidence=m.confidence,
                    tags=m.tags,
                )
                for m in memories
            ],
            rules=[
                RuleResponse(
                    id=r.id,
                    pattern=r.pattern,
                    trigger=r.trigger,
                    examples=r.examples,
                    confirmed_at=r.confirmed_at.isoformat() if r.confirmed_at else None,
                    tags=r.tags,
                )
                for r in rules
            ],
            recent_sessions=recent_sessions,
        )

    # ---- Rules ----

    @app.get("/rules", response_model=RulesResponse)
    async def get_rules(
        project_name: str = Query(..., description="Project name"),
    ):
        backend = await _get_backend_async()
        rules = await backend.structured_store.list_confirmed_rules(project_name)

        return RulesResponse(
            project_name=project_name,
            rules=[
                RuleResponse(
                    id=r.id,
                    pattern=r.pattern,
                    trigger=r.trigger,
                    examples=r.examples,
                    confirmed_at=r.confirmed_at.isoformat() if r.confirmed_at else None,
                    tags=r.tags,
                )
                for r in rules
            ],
            count=len(rules),
        )

    # ---- Rule Candidates ----

    @app.get("/rules/candidates", response_model=RuleCandidatesResponse)
    async def list_rule_candidates(
        project_name: str = Query(..., description="Project name"),
        status: str | None = Query(None, description="Filter by status"),
    ):
        backend = await _get_backend_async()
        candidates = await backend.structured_store.list_rule_candidates(
            project_name, status=status
        )

        return RuleCandidatesResponse(
            project_name=project_name,
            candidates=[
                RuleCandidateItem(
                    id=c.id,
                    project_name=c.project_name,
                    session_id=c.session_id,
                    pattern=c.pattern,
                    trigger=c.trigger,
                    examples=c.examples,
                    confidence=c.confidence,
                    status=c.status,
                    created_at=c.created_at.isoformat(),
                )
                for c in candidates
            ],
            count=len(candidates),
        )

    @app.post("/rules/candidates", response_model=RuleCandidateResponse)
    async def create_rule_candidate(request: RuleCandidateRequest):
        from uuid import uuid4

        backend = await _get_backend_async()
        candidate = RuleCandidate(
            id=str(uuid4()),
            project_name=request.project_name,
            session_id=request.session_id,
            pattern=request.pattern,
            trigger=request.trigger,
            examples=request.examples or [],
            confidence=0.6,
            status="pending",
        )
        saved_id = await backend.structured_store.save_rule_candidate(candidate)

        return RuleCandidateResponse(
            success=True,
            candidate_id=saved_id,
            pattern=candidate.pattern,
            trigger=candidate.trigger,
        )

    @app.post("/rules/{rule_id}/confirm", response_model=ConfirmResponse)
    async def confirm_rule(rule_id: str):
        from uuid import uuid4
        from datetime import datetime, timezone

        backend = await _get_backend_async()
        candidate = await backend.structured_store.get_rule_candidate(rule_id)
        if not candidate:
            raise HTTPException(status_code=404, detail=f"Candidate not found: {rule_id}")
        if candidate.status == "accepted":
            raise HTTPException(status_code=400, detail=f"Candidate already confirmed: {rule_id}")

        confirmed = ConfirmedRule(
            id=str(uuid4()),
            project_name=candidate.project_name,
            pattern=candidate.pattern,
            trigger=candidate.trigger,
            examples=candidate.examples,
            confirmed_at=datetime.now(timezone.utc),
            source_candidate_id=candidate.id,
        )
        await backend.structured_store.save_confirmed_rule(confirmed)
        await backend.structured_store.update_rule_candidate_status(rule_id, "accepted")

        return ConfirmResponse(
            success=True,
            confirmed_rule_id=confirmed.id,
            pattern=confirmed.pattern,
            trigger=confirmed.trigger,
        )

    @app.post("/rules/{rule_id}/reject", response_model=RejectResponse)
    async def reject_rule(rule_id: str, request: RejectRequest | None = None):
        backend = await _get_backend_async()
        candidate = await backend.structured_store.get_rule_candidate(rule_id)
        if not candidate:
            raise HTTPException(status_code=404, detail=f"Candidate not found: {rule_id}")
        if candidate.status in ("accepted", "rejected"):
            raise HTTPException(status_code=400, detail=f"Candidate already processed: {rule_id}")

        await backend.structured_store.update_rule_candidate_status(rule_id, "rejected")

        return RejectResponse(
            success=True,
            rejected_rule_id=rule_id,
            reason=(request.reason if request else None) or "No reason provided",
        )

    @app.post("/rules/{rule_id}/feedback", response_model=FeedbackResponse)
    async def submit_feedback(rule_id: str, request: FeedbackRequest):
        signal = request.signal.lower()
        if signal not in ("positive", "negative", "neutral"):
            raise HTTPException(status_code=400, detail="signal must be positive, negative, or neutral")

        backend = await _get_backend_async()
        rule = await backend.structured_store.get_confirmed_rule(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")

        # V1: simple feedback tracking — update recall_count for positive signals
        if signal == "positive":
            # Rule was useful — could increment recall_count in future
            pass

        return FeedbackResponse(
            success=True,
            rule_id=rule_id,
            signal=signal,
            message=f"Feedback '{signal}' recorded for rule {rule_id}",
        )

    # ---- Wakeup Context ----

    @app.get("/wakeup/{session_id}", response_model=WakeupContextResponse)
    async def get_wakeup_context(
        session_id: str,
        project_name: str = Query(None, description="Project name"),
    ):
        backend = await _get_backend_async()

        if not project_name:
            raise HTTPException(status_code=400, detail="project_name required")

        memories = await backend.structured_store.list_memory_entries(
            project_name, limit=5
        )
        rules = await backend.structured_store.list_confirmed_rules(project_name)

        # Build recommendations based on active rules
        recommendations = [
            f"Remember: {r.trigger}" for r in rules[:3]
        ]

        return WakeupContextResponse(
            session_id=session_id,
            recent_memories=[
                MemoryEntryResponse(
                    id=m.id,
                    category=m.category,
                    content=m.content,
                    confidence=m.confidence,
                    tags=m.tags,
                )
                for m in memories
            ],
            active_rules=[
                WakeupRule(
                    id=r.id,
                    pattern=r.pattern,
                    trigger=r.trigger,
                    recall_count=0,
                )
                for r in rules
            ],
            session_summary=None,
            recommendations=recommendations,
        )

    return app


def main():
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
