"""Podcast Index API v2.0 integration.

Docs: https://podcastindex-org.github.io/docs-api/
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

BASE_URL = "https://api.podcastindex.org/api/1.0"


def _headers() -> dict[str, str]:
    """Generate auth headers for Podcast Index API."""
    api_key = settings.podcast_index_api_key
    api_secret = settings.podcast_index_api_secret
    epoch = int(time.time())
    raw = api_key + api_secret + str(epoch)
    sha1 = hashlib.sha1(raw.encode()).hexdigest()  # noqa: S324
    return {
        "X-Auth-Key": api_key,
        "X-Auth-Date": str(epoch),
        "Authorization": sha1,
        "User-Agent": f"DayangPodcast/0.1 (zcompany)",
    }


async def search_podcasts(query: str, max_results: int = 25) -> list[dict[str, Any]]:
    """Search podcasts by keyword.

    Returns raw JSON from Podcast Index API.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/search/byterm",
            params={"q": query, "max": max_results},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("feeds", [])


async def get_podcast_by_feed_url(feed_url: str) -> dict[str, Any] | None:
    """Look up a podcast by its RSS feed URL."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/podcasts/byfeedurl",
            params={"url": feed_url},
            headers=_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("feed")


async def get_recent_episodes(
    feed_id: int,
    max_results: int = 50,
    since_pubdate: int | None = None,
) -> list[dict[str, Any]]:
    """Get recent episodes for a specific podcast feed.

    Args:
        feed_id: Podcast Index feed ID
        max_results: Max episodes to return
        since_pubdate: Unix timestamp — only return episodes after this date
    """
    params: dict[str, Any] = {"id": feed_id, "max": max_results}
    if since_pubdate:
        params["since"] = since_pubdate

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/episodes/byfeedid",
            params=params,
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])


async def get_trending_podcasts(max_results: int = 20) -> list[dict[str, Any]]:
    """Get trending/popular podcasts."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{BASE_URL}/podcasts/trending",
            params={"max": max_results},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("feeds", [])
