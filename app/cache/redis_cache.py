"""Redis cache layer for topic → recommendation results.

Uses Upstash Redis-compatible endpoint.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400  # 24 hours

_client: aioredis.Redis | None = None


async def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        if settings.redis_url:
            _client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
            )
        else:
            # No Redis configured — return a no-op mock
            _client = None  # type: ignore[assignment]
    return _client  # type: ignore[return-value]


def _topic_hash(topic: str) -> str:
    """Generate deterministic hash from topic string."""
    return hashlib.sha256(topic.strip().lower().encode()).hexdigest()


async def get_cached_recommendation(topic: str) -> dict[str, Any] | None:
    """Retrieve cached recommendation for a topic.

    Returns None if cache miss.
    """
    client = await get_client()
    if client is None:
        return None

    key = f"rec:{_topic_hash(topic)}"
    try:
        raw = await client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Cache GET error: %s", exc)

    return None


async def set_cached_recommendation(
    topic: str,
    data: dict[str, Any],
    ttl: int = CACHE_TTL_SECONDS,
) -> None:
    """Store recommendation result in cache with TTL."""
    client = await get_client()
    if client is None:
        return

    key = f"rec:{_topic_hash(topic)}"
    try:
        await client.setex(key, ttl, json.dumps(data, default=str))
    except Exception as exc:
        logger.warning("Cache SET error: %s", exc)


async def invalidate_cache(topic: str) -> None:
    """Remove cached entry for a topic (force refresh next time)."""
    client = await get_client()
    if client is None:
        return

    key = f"rec:{_topic_hash(topic)}"
    try:
        await client.delete(key)
    except Exception as exc:
        logger.warning("Cache DELETE error: %s", exc)


async def get_cache_stats() -> dict[str, Any]:
    """Get cache hit/miss counters (for monitoring)."""
    client = await get_client()
    if client is None:
        return {"enabled": False}

    try:
        info = await client.info("stats")
        return {
            "enabled": True,
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
            "hit_rate": (
                info["keyspace_hits"] / (info["keyspace_hits"] + info["keyspace_misses"])
                if (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)) > 0
                else 0
            ),
        }
    except Exception as exc:
        logger.warning("Failed to get cache stats: %s", exc)
        return {"enabled": True, "error": str(exc)}


async def health_check() -> bool:
    """Check if Redis is reachable."""
    client = await get_client()
    if client is None:
        return False
    try:
        return await client.ping()
    except Exception:
        return False
