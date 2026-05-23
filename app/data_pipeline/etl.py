"""ETL Pipeline: feedparse → dedup → classify → language-detect → store.

This is the core data ingestion pipeline. It handles both initial seed and daily refresh.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_pipeline.apple_podcasts import map_apple_to_show
from app.data_pipeline.feed_parser import parse_feed
from app.database import Show, Episode

# Language detection: simple heuristic for MVP
# Phase 2: replace with cld3 / langdetect
_CHINESE_RANGE = set(range(0x4E00, 0x9FFF + 1)) | set(range(0x3400, 0x4DBF + 1))


def _detect_language(text: str) -> str:
    """Simple character-range language detection.

    Returns 'zh', 'en', or 'unknown'.
    """
    if not text:
        return "unknown"
    chinese_chars = sum(1 for c in text if ord(c) in _CHINESE_RANGE)
    total = len(text.strip())
    if total == 0:
        return "unknown"
    ratio = chinese_chars / total
    if ratio > 0.15:
        return "zh"
    return "en"


def _classify_category(title: str, description: str) -> list[str]:
    """Simple keyword-based category classification.

    Returns list of category labels.
    """
    text = (title + " " + (description or "")).lower()
    categories = []

    tech_keywords = ["tech", "ai", "software", "startup", "programming", "data", "code",
                     "科技", "人工智能", "编程", "创业", "数据", "软件"]
    finance_keywords = ["finance", "investing", "stock", "market", "economy", "financ",
                        "金融", "投资", "股票", "市场", "经济", "基金", "理财"]
    law_keywords = ["law", "legal", "regulation", "policy", "compliance",
                    "法律", "法规", "合规", "监管", "政策"]
    business_keywords = ["business", "management", "leadership", "strategy", "entre",
                         "商业", "管理", "领导力", "战略", "营销", "品牌"]

    if any(kw in text for kw in tech_keywords):
        categories.append("tech")
    if any(kw in text for kw in finance_keywords):
        categories.append("finance")
    if any(kw in text for kw in law_keywords):
        categories.append("law")
    if any(kw in text for kw in business_keywords):
        categories.append("business")

    return categories if categories else ["general"]


def _dedup_key(episode: dict[str, Any]) -> str:
    """Generate dedup key from title or source_episode_id."""
    eid = episode.get("source_episode_id")
    if eid:
        return eid
    return episode.get("title", "").strip().lower()[:100]


def _is_recent(episode: dict[str, Any], days: int = 7) -> bool:
    """Check if episode was published within N days."""
    pub = episode.get("published_at")
    if not pub:
        return True
    now = datetime.now(timezone.utc)
    delta = now - pub
    return delta.days <= days


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

async def ingest_feed(
    session: AsyncSession,
    feed_url: str,
    show_data: dict[str, Any] | None = None,
    source: str = "podcast_index",
    incremental: bool = True,
) -> int:
    """Ingest episodes from an RSS feed.

    Args:
        session: DB session
        feed_url: RSS/Atom feed URL
        show_data: Optional show metadata to upsert
        source: Source platform identifier
        incremental: If True, only ingest episodes from last 7 days

    Returns:
        Number of new episodes ingested
    """
    # 1. Upsert show
    if show_data:
        show = await _upsert_show(session, feed_url, show_data, source)
    else:
        result = await session.execute(select(Show).where(Show.feed_url == feed_url))
        show = result.scalar_one_or_none()
        if not show:
            raise ValueError(f"Show not found for feed_url={feed_url} and no show_data provided")

    # 2. Parse feed
    episodes = parse_feed(feed_url)

    # 3. Filter
    if incremental:
        episodes = [ep for ep in episodes if _is_recent(ep)]

    if not episodes:
        return 0

    # 4. Get existing episode IDs for dedup
    result = await session.execute(
        select(Episode.source_episode_id, Episode.title).where(Episode.show_id == show.id)
    )
    existing_keys = set()
    for row in result.all():
        if row[0]:
            existing_keys.add(row[0])
        else:
            existing_keys.add(row[1].strip().lower()[:100])

    # 5. Insert new episodes
    count = 0
    for ep in episodes:
        key = _dedup_key(ep)
        if key in existing_keys:
            continue

        lang = _detect_language(ep.get("title", "") + " " + (ep.get("description") or ""))

        new_ep = Episode(
            id=uuid.uuid4(),
            show_id=show.id,
            title=ep["title"],
            description=ep.get("description"),
            show_notes=ep.get("show_notes"),
            published_at=ep["published_at"],
            duration_sec=ep.get("duration_sec"),
            audio_url=ep.get("audio_url"),
            episode_url=ep.get("episode_url"),
            source_episode_id=ep.get("source_episode_id"),
        )
        session.add(new_ep)
        existing_keys.add(key)
        count += 1

    await session.commit()
    return count


async def _upsert_show(
    session: AsyncSession,
    feed_url: str,
    show_data: dict[str, Any],
    source: str,
) -> Show:
    """Upsert a show record."""
    result = await session.execute(select(Show).where(Show.feed_url == feed_url))
    existing = result.scalar_one_or_none()

    if existing:
        # Update metadata
        for field in ("title", "description", "artwork_url", "author", "language"):
            if show_data.get(field):
                setattr(existing, field, show_data[field][:512] if field == "title" else show_data[field])
        await session.flush()
        return existing

    title = show_data.get("title", "Untitled")
    description = show_data.get("description") or ""
    language = _detect_language(title + " " + description)
    category = _classify_category(title, description)

    # Use provided category if available
    if show_data.get("category") and isinstance(show_data["category"], list):
        category = show_data["category"]

    show = Show(
        id=uuid.uuid4(),
        title=title[:512],
        description=description[:5000] if description else None,
        language=show_data.get("language", language)[:10],
        category=category,
        feed_url=feed_url,
        artwork_url=show_data.get("artwork_url"),
        author=str(show_data.get("author", ""))[:256] if show_data.get("author") else None,
        source=source,
        source_show_id=str(show_data.get("source_show_id", "") or ""),
    )
    session.add(show)
    await session.flush()
    return show


async def bulk_ingest_from_seed_list(
    session: AsyncSession,
    seed_list: list[dict[str, Any]],
    incremental: bool = True,
) -> dict[str, int]:
    """Ingest a list of seed shows.

    seed_list format::
        [{"feed_url": "...", "title": "...", "source": "manual", ...}, ...]

    Returns per-feed episode counts.
    """
    results = {}
    for entry in seed_list:
        try:
            show_data = {k: v for k, v in entry.items() if k != "feed_url"}
            count = await ingest_feed(
                session,
                feed_url=entry["feed_url"],
                show_data=show_data,
                source=entry.get("source", "manual"),
                incremental=incremental,
            )
            results[entry.get("title", entry["feed_url"])] = count
        except Exception as exc:
            results[entry.get("title", entry["feed_url"])] = f"ERROR: {exc}"

    return results
