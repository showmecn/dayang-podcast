"""Recommendation API router — orchestrates the full pipeline.

flow: parse request → check cache [HIT → return] → vector retrieve top-20 →
LLM re-rank top-3 → diversity post-process → generate summaries →
cache result → return
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import get_cached_recommendation, set_cached_recommendation
from app.database import get_session
from app.models.schemas import (
    EpisodeRecommendation,
    RecommendRequest,
    RecommendResponse,
    Timestamp,
)
from app.recommender.diversify import diversify_ranked
from app.recommender.fallback import fallback_full_text_search, fallback_recent_episodes
from app.recommender.reranker import rerank
from app.recommender.retriever import retrieve_top_k
from app.summary.generator import generate_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["recommendations"])


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
    4. Diversity post-process (show_id dedup + substitution)
    5. Generate summaries + timestamps
    6. Cache result
    7. Return response
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
    candidates = await retrieve_top_k(session, topic, top_k=20, min_score=0.5)

    # --- Step 2b: Fallback if no candidates ---
    if not candidates:
        logger.info("No vector candidates for topic '%s', trying full-text fallback", topic)
        candidates = await fallback_full_text_search(session, topic, top_k=10)
        if not candidates:
            logger.info("Full-text fallback also empty for '%s', returning recent episodes", topic)
            candidates = await fallback_recent_episodes(session, top_k=3)

    # --- Step 3: LLM re-rank (top-20 → top-3) ---
    ranked = await rerank(topic, candidates, top_k=req.top_k)

    # --- Step 4: Diversity post-process (show_id dedup + substitution) ---
    diverse = diversify_ranked(ranked, candidates, top_k=req.top_k)
    logger.info(
        "Diversity post-process: %d ranked → %d diverse (topic=%s)",
        len(ranked), len(diverse), topic,
    )

    # --- Step 5: Generate summaries in parallel ---
    recommendations = []
    summary_tasks = [
        generate_summary(
            title=ep.get("episode_title", ""),
            show_title=ep.get("show_title", ""),
            description=ep.get("description"),
            show_notes=ep.get("show_notes"),
        )
        for ep in diverse
    ]
    summary_results = await asyncio.gather(*summary_tasks, return_exceptions=True)

    for ep, summary_data in zip(diverse, summary_results):
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
        "disclaimer": "AI-generated recommendations and summaries. Verify with original content.",
    }

    # --- Step 6: Cache result ---
    try:
        await set_cached_recommendation(topic, response)
    except Exception as exc:
        logger.warning("Failed to cache recommendation: %s", exc)

    return response
