"""Seed data script — initializes database with curated podcast shows.

Run once on first deploy to populate the show catalog.

Usage:
    python scripts/seed_data.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_data")

# MVP seed list: curated high-quality podcast sources
# Source: https://podcastindex.org/ (find feed URLs via search)
SEED_SHOWS: list[dict[str, Any]] = [
    # --- Tech ---
    {
        "title": "Lex Fridman Podcast",
        "feed_url": "https://lexfridman.com/feed/podcast/",
        "source": "manual",
        "language": "en",
        "category": ["tech", "science"],
        "author": "Lex Fridman",
    },
    {
        "title": "a16z Podcast",
        "feed_url": "https://feeds.simplecast.com/QRZq1GmD",
        "source": "manual",
        "language": "en",
        "category": ["tech", "startup"],
        "author": "Andreessen Horowitz",
    },
    {
        "title": "TechCrunch",
        "feed_url": "https://feeds.megaphone.fm/TPD5748871894",
        "source": "manual",
        "language": "en",
        "category": ["tech"],
        "author": "TechCrunch",
    },
    {
        "title": "Acquired",
        "feed_url": "https://feeds.megaphone.fm/acquired",
        "source": "manual",
        "language": "en",
        "category": ["tech", "business"],
        "author": "Ben Gilbert & David Rosenthal",
    },
    # --- Finance ---
    {
        "title": "Bloomberg Businessweek",
        "feed_url": "https://feeds.megaphone.fm/PPY7324371028",
        "source": "manual",
        "language": "en",
        "category": ["finance", "business"],
        "author": "Bloomberg",
    },
    {
        "title": "Planet Money",
        "feed_url": "https://feeds.npr.org/510289/podcast.xml",
        "source": "manual",
        "language": "en",
        "category": ["finance", "economics"],
        "author": "NPR",
    },
    {
        "title": "The Tim Ferriss Show",
        "feed_url": "https://rss.art19.com/tim-ferriss-show",
        "source": "manual",
        "language": "en",
        "category": ["business", "self-improvement"],
        "author": "Tim Ferriss",
    },
    {
        "title": "HBR IdeaCast",
        "feed_url": "https://feeds.harvardbusiness.org/harvardbusiness/ideacast",
        "source": "manual",
        "language": "en",
        "category": ["business", "management"],
        "author": "Harvard Business Review",
    },
    # --- Law / Policy ---
    {
        "title": "The Lawfare Podcast",
        "feed_url": "https://feeds.simplecast.com/l3fMejb0",
        "source": "manual",
        "language": "en",
        "category": ["law", "policy"],
        "author": "Lawfare",
    },
    {
        "title": "Rational Security",
        "feed_url": "https://feeds.npr.org/510310/podcast.xml",
        "source": "manual",
        "language": "en",
        "category": ["law", "policy", "security"],
        "author": "NPR",
    },
    # --- Chinese podcasts (from Apple Podcasts / manual) ---
    {
        "title": "硅谷101",
        "feed_url": "https://sv101.substack.com/feed",
        "source": "manual",
        "language": "zh",
        "category": ["tech", "startup"],
        "author": "硅谷101",
    },
    {
        "title": "科技聚变",
        "feed_url": "https://techfusionfm.com/feed/podcast/",
        "source": "manual",
        "language": "zh",
        "category": ["tech"],
        "author": "科技聚变",
    },
    {
        "title": "声动早咖啡",
        "feed_url": "https://feeds.fireside.fm/shengpod/rss",
        "source": "manual",
        "language": "zh",
        "category": ["business", "tech"],
        "author": "声动活泼",
    },
    {
        "title": "忽左忽右",
        "feed_url": "https://leftright.xyz/feed/podcast/",
        "source": "manual",
        "language": "zh",
        "category": ["culture", "history"],
        "author": "忽左忽右",
    },
    # --- Science / AI ---
    {
        "title": "Practical AI",
        "feed_url": "https://feeds.simplecast.com/DE8Zefe0",
        "source": "manual",
        "language": "en",
        "category": ["ai", "tech"],
        "author": "Changelog Media",
    },
    {
        "title": "Hardcore History",
        "feed_url": "https://feeds.simplecast.com/ZbQ5abij",
        "source": "manual",
        "language": "en",
        "category": ["history"],
        "author": "Dan Carlin",
    },
]


async def seed():
    """Run seeding: init DB + ingest seed shows."""
    from app.database import init_db, async_session_factory
    from app.data_pipeline.etl import bulk_ingest_from_seed_list

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized (tables created).")

    async with async_session_factory() as session:
        logger.info("Ingesting %d seed shows...", len(SEED_SHOWS))
        results = await bulk_ingest_from_seed_list(
            session,
            seed_list=SEED_SHOWS,
            incremental=False,  # ingest ALL episodes on seed
        )

        success = 0
        errors = 0
        total_eps = 0
        for title, count in results.items():
            if isinstance(count, int):
                success += 1
                total_eps += count
                logger.info("  ✅ %s: %d episodes", title, count)
            else:
                errors += 1
                logger.warning("  ❌ %s: %s", title, count)

        logger.info("Seeding complete: %d/%d shows, %d total episodes", success, len(SEED_SHOWS), total_eps)


def main():
    asyncio.run(seed())


if __name__ == "__main__":
    main()
