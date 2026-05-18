"""Pydantic models for REST API request/response."""

from __future__ import annotations
from typing import Optional

from pydantic import BaseModel, Field


# ---- Search ----

class SearchRequest(BaseModel):
    query: str = Field(description="Search query string")
    project_name: Optional[str] = Field(None, description="Project name filter")
    type: Optional[str] = Field(None, description="Memory type filter")
    scope: str = Field("project", description="project or all")
    mode: str = Field("auto", description="auto, fts, or hybrid")
    limit: int = Field(20, ge=1, le=100)


class MemoryEntryResponse(BaseModel):
    id: str
    project_name: Optional[str] = None
    tech_stack: list[str] = Field(default_factory=list)
    category: str
    memory_type: str = "semantic"
    content: str
    confidence: float
    tags: list[str]
    search_mode: Optional[str] = None
    score: Optional[float] = None


class ObservationResponse(BaseModel):
    id: str
    project_name: Optional[str] = None
    tech_stack: list[str] = Field(default_factory=list)
    session_id: str
    content_type: str
    preview: str
    search_mode: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    project_name: Optional[str]
    query: str
    scope: str
    requested_mode: str
    effective_mode: str
    fallback_reason: Optional[str] = None
    memory_entries: list[MemoryEntryResponse]
    observations: list[ObservationResponse]
    memory_entry_count: int
    observation_count: int


# ---- Context ----

class ContextRequest(BaseModel):
    session_id: str = Field(description="Session ID to get context for")


class ContextResponse(BaseModel):
    session_id: str
    memories: list[MemoryEntryResponse]
    rules: list[RuleResponse]
    recent_sessions: list[SessionInfo]


# ---- Timeline ----

class TimelineRequest(BaseModel):
    project_name: str
    limit: int = Field(50, ge=1, le=200)


class TimelineObservation(BaseModel):
    id: str
    session_id: str
    client: str
    content_type: str
    timestamp: Optional[str]
    preview: str
    tags: list[str]


class TimelineResponse(BaseModel):
    project_name: str
    limit: int
    observations: list[TimelineObservation]
    count: int


# ---- Observations ----

class ObservationsRequest(BaseModel):
    project_name: str
    session_id: str


class ObservationDetail(BaseModel):
    id: str
    session_id: str
    client: str
    content_type: str
    timestamp: Optional[str]
    raw_content: str
    tags: list[str]
    metadata: dict


class ObservationsResponse(BaseModel):
    project_name: str
    session_id: str
    observations: list[ObservationDetail]
    count: int


# ---- Rules ----

class RuleResponse(BaseModel):
    id: str
    pattern: str
    trigger: str
    examples: list[str]
    confirmed_at: Optional[str]
    tags: list[str]


class RulesRequest(BaseModel):
    project_name: str


class RulesResponse(BaseModel):
    project_name: str
    rules: list[RuleResponse]
    count: int


# ---- Rule Candidates ----

class RuleCandidateRequest(BaseModel):
    project_name: str
    session_id: str
    pattern: str
    trigger: str
    examples: Optional[list[str]] = None


class RuleCandidateResponse(BaseModel):
    success: bool
    candidate_id: str
    pattern: str
    trigger: str


class RuleCandidatesRequest(BaseModel):
    project_name: str
    status: Optional[str] = None


class RuleCandidateItem(BaseModel):
    id: str
    project_name: str
    session_id: str
    pattern: str
    trigger: str
    examples: list[str]
    confidence: float
    status: str
    created_at: str


class RuleCandidatesResponse(BaseModel):
    project_name: str
    candidates: list[RuleCandidateItem]
    count: int


# ---- Feedback ----

class FeedbackRequest(BaseModel):
    signal: str = Field(description="positive, negative, or neutral")


class FeedbackResponse(BaseModel):
    success: bool
    rule_id: str
    signal: str
    message: Optional[str] = None


# ---- Confirm/Reject ----

class ConfirmResponse(BaseModel):
    success: bool
    confirmed_rule_id: str
    pattern: str
    trigger: str


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class RejectResponse(BaseModel):
    success: bool
    rejected_rule_id: str
    reason: Optional[str]


# ---- Wakeup Context ----

class WakeupRequest(BaseModel):
    session_id: str = Field(description="New session ID to generate wakeup context for")


class WakeupRule(BaseModel):
    id: str
    pattern: str
    trigger: str
    recall_count: int


class WakeupContextResponse(BaseModel):
    session_id: str
    recent_memories: list[MemoryEntryResponse]
    active_rules: list[WakeupRule]
    session_summary: Optional[str] = None
    recommendations: list[str]


# ---- Session Info ----

class SessionInfo(BaseModel):
    id: str
    started_at: Optional[str]
    ended_at: Optional[str]
    client: str


# ---- Health ----

class HealthResponse(BaseModel):
    status: str
    version: str
    data_dir: str
