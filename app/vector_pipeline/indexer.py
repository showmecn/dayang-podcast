"""Batch embedding indexer — full initialisation and incremental update.

Manages the lifecycle of episode embeddings in the pgvector index.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Episode
from app.vector_pipeline.embedder import embed_episodes_batch

logger = logging.getLogger(__name__)


async def index_missing_embeddings(session: AsyncSession, batch_size: int = 50) -> int:
    """Generate embeddings for episodes that don't have one yet.

    Returns number of episodes indexed.
    """
    result = await session.execute(
        select(Episode).where(Episode.embedding.is_(None)).limit(batch_size)
    )
    episodes = list(result.scalars().all())

    if not episodes:
        return 0

    episode_dicts = [
        {
            "title": e.title,
            "description": e.description,
            "show_notes": e.show_notes,
        }
        for e in episodes
    ]

    embeddings = await embed_episodes_batch(episode_dicts)

    for ep, emb in zip(episodes, embeddings):
        ep.embedding = emb

    await session.commit()
    logger.info("Indexed %d episode embeddings", len(episodes))
    return len(episodes)


async def index_all_episodes(session: AsyncSession) -> int:
    """Full index: iterates all episodes without embeddings in batches.

    Call this on initial seed to populate the entire vector index.
    """
    total = 0
    while True:
        count = await index_missing_embeddings(session, batch_size=50)
        total += count
        if count == 0:
            break
    return total


async def create_vector_index(session: AsyncSession) -> None:
    """Create pgvector IVF index for cosine similarity.

    Uses IVFFlat with cosine distance (vector_cosine_ops).
    """
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_episodes_embedding_cosine
        ON episodes
        USING ivf (embedding vector_cosine_ops)
        WITH (lists = 100)
    """))
    await session.commit()


async def drop_vector_index(session: AsyncSession) -> None:
    """Drop the vector index (for rebuilds)."""
    await session.execute(text("DROP INDEX IF EXISTS idx_episodes_embedding_cosine"))
    await session.commit()


async def get_unindexed_count(session: AsyncSession) -> int:
    """Count episodes without embeddings."""
    result = await session.execute(
        select(text("COUNT(*)")).select_from(Episode).where(Episode.embedding.is_(None))
    )
    return result.scalar() or 0
