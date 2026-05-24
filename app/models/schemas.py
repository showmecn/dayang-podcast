"""Pydantic schemas for API request/response."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Episode / Show schemas
# ---------------------------------------------------------------------------

class EpisodeResponse(BaseModel):
    """Single episode in API responses."""
    id: uuid.UUID
    show_id: uuid.UUID
    title: str
    show_title: str = ""
    show_artwork_url: str | None = None
    description: str | None = None
    show_notes: str | None = None
    published_at: datetime
    duration_sec: int | None = None
    audio_url: str | None = None
    episode_url: str | None = None


class ShowResponse(BaseModel):
    """Show metadata."""
    id: uuid.UUID
    title: str
    description: str | None = None
    language: str
    category: list[str]
    artwork_url: str | None = None
    author: str | None = None
    source: str


# ---------------------------------------------------------------------------
# Recommendation schemas
# ---------------------------------------------------------------------------

class RecommendRequest(BaseModel):
    """POST /api/recommend payload."""
    topic: str = Field(..., min_length=1, max_length=500, description="User query topic")
    top_k: int = Field(default=3, ge=1, le=10, description="Number of recommendations")
    refresh: bool = Field(default=False, description="Bypass cache and force refresh")


class Timestamp(BaseModel):
    """Key timestamp with label."""
    time_str: str = Field(..., description="e.g. '12:34' or '01:23:45'")
    label: str = Field(..., description="Brief description of what happens at this timestamp")


class EpisodeRecommendation(BaseModel):
    """One recommended episode with summary and reason."""
    episode_id: uuid.UUID
    show_id: uuid.UUID
    episode_title: str
    show_title: str
    show_artwork_url: str | None = None
    published_at: datetime
    duration_sec: int | None = None
    audio_url: str | None = None
    episode_url: str | None = None
    summary: str = Field(..., description="~200 char Chinese summary")
    reason: str = Field(..., description="Why this episode matches the topic")
    timestamps: list[Timestamp] = Field(default_factory=list)
    relevance_score: float | None = None


class RecommendResponse(BaseModel):
    """Response to /api/recommend."""
    topic: str
    recommendations: list[EpisodeRecommendation]
    cached: bool = False
    total_candidates: int = 0
    processing_time_ms: int = 0
    note: str | None = Field(default=None, description="Additional info, e.g. insufficient highly relevant results")
    disclaimer: str = "AI-generated recommendations and summaries. Verify with original content."


# ---------------------------------------------------------------------------
# Error / Health
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Latest episodes schemas
# ---------------------------------------------------------------------------

class LatestResponse(BaseModel):
    """Response to GET /api/latest."""
    recommendations: list[EpisodeRecommendation]
    total: int
    note: str | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    db_connected: bool
    cache_connected: bool
    uptime_sec: float | None = None
