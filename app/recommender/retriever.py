"""Vector retriever — uses pgvector cosine similarity for top-K recall.

Uses SQLAlchemy ORM with pgvector's native cosine_distance operator
to avoid raw SQL injection surface.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Episode, Show
from app.vector_pipeline.embedder import embed_text


async def retrieve_top_k(
    session: AsyncSession,
    query: str,
    top_k: int = 20,
    min_score: float = 0.5,
) -> list[dict[str, Any]]:
    """Vector search: embed query → cosine similarity → top-K episodes.

    Uses pgvector's cosine_distance operator via SQLAlchemy ORM, selecting
    the distance alongside episode+show data.

    Args:
        session: DB session
        query: User's topic query
        top_k: Number of candidates to retrieve
        min_score: Minimum cosine similarity threshold (0-1)

    Returns:
        List of episode dicts with: episode_id, show_id, title, show_title,
        description, show_notes, published_at, duration_sec, audio_url,
        episode_url, show_artwork_url, similarity
    """
    # 1. Embed the query
    query_vector = await embed_text(query)

    # 2. Vector search — select distance alongside episode/show data
    #    cosine_distance returns a SQL expression; we use it both for
    #    ordering and as a selected column for post-filtering.
    dist_expr = Episode.embedding.cosine_distance(query_vector)

    stmt = (
        select(Episode, Show, dist_expr.label("distance"))
        .join(Show, Episode.show_id == Show.id)
        .where(Episode.embedding.isnot(None))
        .order_by(dist_expr)
        .limit(top_k * 2)  # fetch extra for threshold filtering
    )

    result = await session.execute(stmt)
    rows = result.all()

    candidates = []
    for episode, show, distance in rows:
        # Cosine similarity = 1 - cosine_distance
        similarity = 1.0 - float(distance)
        if similarity < min_score:
            continue

        candidates.append({
            "episode_id": episode.id,
            "show_id": episode.show_id,
            "episode_title": episode.title,
            "show_title": show.title,
            "description": episode.description,
            "show_notes": episode.show_notes,
            "published_at": episode.published_at,
            "duration_sec": episode.duration_sec,
            "audio_url": episode.audio_url,
            "episode_url": episode.episode_url,
            "show_artwork_url": show.artwork_url,
            "similarity": similarity,
        })

        if len(candidates) >= top_k:
            break

    return candidates
