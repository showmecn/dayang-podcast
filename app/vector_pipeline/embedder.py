"""Local sentence-transformers embedding client.

Uses all-MiniLM-L6-v2 for 384-dimensional embeddings.
No external API key needed — runs entirely locally.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", settings.embedding_model)
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def _text_for_embedding(title: str, description: str | None, show_notes: str | None) -> str:
    """Build a consolidated text from episode metadata for embedding.

    Strategy: title + description, with show_notes truncated to avoid
    diluting semantic signal with very long transcripts.
    """
    parts = [title]
    if description:
        parts.append(description[:2000])
    if show_notes:
        parts.append(show_notes[:1000])
    return "\n\n".join(parts)


async def embed_text(text: str) -> list[float]:
    """Embed a single text string.

    Returns 384-dimensional vector from all-MiniLM-L6-v2.
    """
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts.

    Returns list of 384-dimensional vectors, one per input text.
    """
    if not texts:
        return []
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


async def embed_episode(
    title: str,
    description: str | None = None,
    show_notes: str | None = None,
) -> list[float]:
    """Generate embedding for a single episode."""
    text = _text_for_embedding(title, description, show_notes)
    return await embed_text(text)


async def embed_episodes_batch(
    episodes: list[dict[str, Any]],
) -> list[list[float]]:
    """Generate embeddings for multiple episodes in batch.

    Args:
        episodes: List of dicts with keys: title, description, show_notes

    Returns:
        List of embedding vectors in same order as input.
    """
    texts = [
        _text_for_embedding(e["title"], e.get("description"), e.get("show_notes"))
        for e in episodes
    ]
    return await embed_batch(texts)
