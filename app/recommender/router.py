"""Recommendation API router — orchestrates the full pipeline.

flow: parse request → check cache [HIT → return] → vector retrieve top-20 →
LLM re-rank top-3 → generate summaries → cache result → return
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import get_cached_recommendation, set_cached_recommendation
from app.database import get_session
from app.models.schemas import (
    EpisodeRecommendation,
    LatestResponse,
    RecommendRequest,
    RecommendResponse,
    Timestamp,
)
from app.recommender.fallback import fallback_full_text_search, fallback_recent_episodes
from app.recommender.reranker import rerank
from app.recommender.retriever import retrieve_top_k
from app.summary.generator import generate_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["recommendations"])

# Minimum relevance score for results to appear in top-N
MIN_RELEVANCE = 88


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    req: RecommendRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Main recommendation endpoint.

    Full pipeline:
    1. Check cache (skip if refresh=True)
    2. Embed query → vector search top-20
    3. LLM re-rank top-3
    4. Generate summaries + timestamps
    5. Cache result
    6. Return response
    """
    start = time.monotonic()
    topic = req.topic.strip()

    # --- Step 1: Check cache ---
    if not req.refresh:
        cached = await get_cached_recommendation(topic)
        if cached:
            elapsed = int((time.monotonic() - start) * 1000)
            cached["cached"] = True
            cached["processing_time_ms"] = elapsed
            cached["disclaimer"] = "AI-generated recommendations and summaries. Verify with original content."
            return cached

    # --- Step 2: Vector search (top-20) ---
    candidates = await retrieve_top_k(session, topic, top_k=20, min_score=0.3)

    # --- Step 2b: Fallback if no candidates ---
    if not candidates:
        logger.info("No vector candidates for topic '%s', trying full-text fallback", topic)
        candidates = await fallback_full_text_search(session, topic, top_k=10)
        if not candidates:
            logger.info("Full-text fallback also empty for '%s', returning recent episodes", topic)
            candidates = await fallback_recent_episodes(session, top_k=3)

    # --- Step 3: LLM re-rank (top-20 → top-3) ---
    ranked = await rerank(topic, candidates, top_k=req.top_k)

    # --- Step 3b: Relevance threshold filter ---
    ranked = [ep for ep in ranked if (ep.get("relevance_score") or 0) >= MIN_RELEVANCE]
    note: str | None = None
    if len(ranked) == 0:
        note = "No highly relevant episodes found for this topic"
    elif len(ranked) < req.top_k:
        note = f"Only {len(ranked)} highly relevant episodes found for this topic"

    # --- Step 3c: Date-first sort (pub_date DESC, relevance DESC) ---
    def _sort_key(ep: dict) -> tuple:
        pub = ep.get("published_at")
        if pub is None:
            pub = datetime.min.replace(tzinfo=timezone.utc)
        return (pub, ep.get("relevance_score") or 0)

    ranked = sorted(ranked, key=_sort_key, reverse=True)

    # --- Step 4: Generate summaries in parallel ---
    recommendations = []
    summary_tasks = [
        generate_summary(
            title=ep.get("episode_title", ""),
            show_title=ep.get("show_title", ""),
            description=ep.get("description"),
            show_notes=ep.get("show_notes"),
        )
        for ep in ranked
    ]
    summary_results = await asyncio.gather(*summary_tasks, return_exceptions=True)

    for ep, summary_data in zip(ranked, summary_results):
        if isinstance(summary_data, Exception):
            logger.warning("Summary generation failed: %s", summary_data)
            summary_data = {"summary": "Summary not available.", "timestamps": []}

        timestamps = []
        for ts in summary_data.get("timestamps", []):
            timestamps.append(Timestamp(
                time_str=ts.get("time_str", ""),
                label=ts.get("label", ""),
            ))

        recommendations.append(EpisodeRecommendation(
            episode_id=ep["episode_id"],
            show_id=ep["show_id"],
            episode_title=ep.get("episode_title", ""),
            show_title=ep.get("show_title", ""),
            show_artwork_url=ep.get("show_artwork_url"),
            published_at=ep.get("published_at"),
            duration_sec=ep.get("duration_sec"),
            audio_url=ep.get("audio_url"),
            episode_url=ep.get("episode_url"),
            summary=summary_data.get("summary", "Summary not available."),
            reason=ep.get("reason", f"Matches your query about '{topic}'"),
            timestamps=timestamps,
            relevance_score=ep.get("relevance_score"),
        ))

    elapsed = int((time.monotonic() - start) * 1000)

    response: dict[str, Any] = {
        "topic": topic,
        "recommendations": [r.model_dump() for r in recommendations],
        "cached": False,
        "total_candidates": len(candidates),
        "processing_time_ms": elapsed,
        "note": note,
        "disclaimer": "AI-generated recommendations and summaries. Verify with original content.",
    }

    # --- Step 5: Cache result ---
    try:
        await set_cached_recommendation(topic, response)
    except Exception as exc:
        logger.warning("Failed to cache recommendation: %s", exc)

    return response


# ---------------------------------------------------------------------------
# Latest episodes endpoint (non-AI, no search)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Random episodes endpoint (non-AI, no search, pure DB random query)
# ---------------------------------------------------------------------------


@router.get("/random", response_model=LatestResponse)
async def random_episodes(
    limit: int = 4,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return random episodes with audio_url, preferring last-30-day freshness.

    Pure DB query — no AI, no LLM, no model inference.
    Response format matches /api/latest exactly (frontend shares rendering).
    """
    start = time.monotonic()

    # Single query: prefer recent (≤ 30 days) but random within each tier.
    # If fewer than `limit` recent episodes exist, older ones fill automatically.
    sql = text("""
        SELECT
            e.id          AS episode_id,
            e.show_id,
            e.title       AS episode_title,
            s.title       AS show_title,
            e.description,
            e.show_notes,
            e.published_at,
            e.duration_sec,
            e.audio_url,
            e.episode_url,
            s.artwork_url AS show_artwork_url
        FROM episodes e
        JOIN shows s ON s.id = e.show_id
        WHERE e.audio_url IS NOT NULL
        ORDER BY
            CASE WHEN e.published_at > NOW() - INTERVAL '30 days' THEN 1 ELSE 2 END,
            RANDOM()
        LIMIT :limit
    """)
    result = await session.execute(sql, {"limit": limit})
    rows = result.all()

    recommendations = [
        EpisodeRecommendation(
            episode_id=row.episode_id,
            show_id=row.show_id,
            episode_title=row.episode_title,
            show_title=row.show_title,
            show_artwork_url=row.show_artwork_url,
            published_at=row.published_at,
            duration_sec=row.duration_sec,
            audio_url=row.audio_url,
            episode_url=row.episode_url,
            summary=(row.description or "")[:500] if row.description else "No summary available.",
            reason=f"Random episode from 《{row.show_title}》",
            timestamps=[],
        )
        for row in rows
    ]

    note: str | None = None
    if len(recommendations) < limit:
        note = f"Only {len(recommendations)} episodes with audio available"

    return {
        "recommendations": [r.model_dump() for r in recommendations],
        "total": len(recommendations),
        "note": note,
    }


# Shows to include in /api/latest results — Chinese tech/business podcasts
LATEST_SHOW_NAMES = [
    "硅谷101",
    "罗永浩的十字路口",
    "科技早8点",
    "疯投圈",
]


@router.get("/latest", response_model=LatestResponse)
async def latest_episodes(
    limit: int = 5,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the latest episode from each curated show.

    No AI search or re-ranking — just DB query ordered by published_at DESC.
    Returns one episode per show, sorted most-recent-first.
    """
    start = time.monotonic()

    sql = text("""
        WITH latest_per_show AS (
            SELECT DISTINCT ON (e.show_id)
                e.id AS episode_id,
                e.show_id,
                e.title AS episode_title,
                s.title AS show_title,
                e.description,
                e.show_notes,
                e.published_at,
                e.duration_sec,
                e.audio_url,
                e.episode_url,
                s.artwork_url AS show_artwork_url
            FROM episodes e
            JOIN shows s ON s.id = e.show_id
            WHERE s.title = ANY(:show_names)
            ORDER BY e.show_id, e.published_at DESC NULLS LAST
        )
        SELECT * FROM latest_per_show
        ORDER BY published_at DESC NULLS LAST
        LIMIT :limit
    """)
    result = await session.execute(sql, {
        "show_names": LATEST_SHOW_NAMES,
        "limit": limit,
    })
    rows = result.all()

    recommendations = [
        EpisodeRecommendation(
            episode_id=row.episode_id,
            show_id=row.show_id,
            episode_title=row.episode_title,
            show_title=row.show_title,
            show_artwork_url=row.show_artwork_url,
            published_at=row.published_at,
            duration_sec=row.duration_sec,
            audio_url=row.audio_url,
            episode_url=row.episode_url,
            summary=(row.description or "")[:500] if row.description else "No summary available.",
            reason=f"Latest episode from 《{row.show_title}》",
            timestamps=[],
        )
        for row in rows
    ]

    note: str | None = None
    if len(recommendations) < limit:
        note = f"Only {len(recommendations)} shows with episodes available"

    return {
        "recommendations": [r.model_dump() for r in recommendations],
        "total": len(recommendations),
        "note": note,
    }

