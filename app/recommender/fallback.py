"""Fallback strategies when vector search returns no results.

Cold start: no matching episodes → return recently published episodes sorted by publish date.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Episode, Show


async def fallback_recent_episodes(
    session: AsyncSession,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Cold-start fallback: return most recently published episodes.

    Used when vector search finds no matches above the similarity threshold.
    """
    # Use raw SQL with a simpler query to avoid ORM overhead
    sql = text("""
        SELECT
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
        ORDER BY e.published_at DESC NULLS LAST
        LIMIT :top_k
    """)
    result = await session.execute(sql, {"top_k": top_k})
    rows = result.all()

    return [
        {
            "episode_id": row.episode_id,
            "show_id": row.show_id,
            "episode_title": row.episode_title,
            "show_title": row.show_title,
            "description": row.description,
            "show_notes": row.show_notes,
            "published_at": row.published_at,
            "duration_sec": row.duration_sec,
            "audio_url": row.audio_url,
            "episode_url": row.episode_url,
            "show_artwork_url": row.show_artwork_url,
            "similarity": 0.0,
            "reason": "Popular recent episode — no direct topic matches found",
            "relevance_score": 50,
        }
        for row in rows
    ]


async def fallback_full_text_search(
    session: AsyncSession,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Full-text search fallback using PostgreSQL tsvector.

    Used when embedding similarity is below threshold but we have partial matches.
    """
    # Build tsquery from keywords
    words = query.strip().split()
    if not words:
        return await fallback_recent_episodes(session, top_k)

    tsquery = " | ".join(words)
    sql = text(f"""\
        SELECT
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
            s.artwork_url AS show_artwork_url,
            ts_rank(
                to_tsvector('english', coalesce(e.title, '') || ' ' ||
                            coalesce(e.description, '') || ' ' ||
                            coalesce(e.show_notes, '')),
                plainto_tsquery('english', :query)
            ) AS rank
        FROM episodes e
        JOIN shows s ON s.id = e.show_id
        WHERE
            to_tsvector('english', coalesce(e.title, '') || ' ' ||
                        coalesce(e.description, '') || ' ' ||
                        coalesce(e.show_notes, '')) @@ plainto_tsquery('english', :query)
        ORDER BY rank DESC
        LIMIT :top_k
    """)
    result = await session.execute(sql, {"query": tsquery, "top_k": top_k})
    rows = result.all()

    return [
        {
            "episode_id": row.episode_id,
            "show_id": row.show_id,
            "episode_title": row.episode_title,
            "show_title": row.show_title,
            "description": row.description,
            "show_notes": row.show_notes,
            "published_at": row.published_at,
            "duration_sec": row.duration_sec,
            "audio_url": row.audio_url,
            "episode_url": row.episode_url,
            "show_artwork_url": row.show_artwork_url,
            "similarity": float(row.rank) if hasattr(row, 'rank') else 0.0,
            "reason": "Keyword match — similar to your query",
            "relevance_score": 60,
        }
        for row in rows
    ]
