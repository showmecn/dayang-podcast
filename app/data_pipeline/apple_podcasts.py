"""Apple Podcasts Search API integration.

Apple's Search API is undocumented but widely used.
Endpoint: https://itunes.apple.com/search?term=...&media=podcast&limit=...
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://itunes.apple.com/search"


async def search_podcasts(query: str, limit: int = 25, country: str = "us") -> list[dict[str, Any]]:
    """Search podcasts via Apple iTunes Search API.

    Args:
        query: Search term
        limit: Max results (10-200)
        country: ISO country code (us, cn, jp, etc.)
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            BASE_URL,
            params={
                "term": query,
                "media": "podcast",
                "limit": min(limit, 200),
                "country": country,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])


def map_apple_to_show(apple_result: dict[str, Any]) -> dict[str, Any]:
    """Map Apple Podcasts API result to our internal show format."""
    return {
        "title": apple_result.get("collectionName", ""),
        "description": apple_result.get("description", apple_result.get("collectionName", "")),
        "feed_url": apple_result.get("feedUrl", ""),
        "artwork_url": apple_result.get("artworkUrl600", apple_result.get("artworkUrl100", "")),
        "author": apple_result.get("artistName", ""),
        "category": [apple_result.get("primaryGenreName", "Unknown")],
        "language": apple_result.get("language", "en")[:10],
        "source": "apple",
        "source_show_id": str(apple_result.get("collectionId", "")),
    }
