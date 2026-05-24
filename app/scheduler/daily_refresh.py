"""Daily data refresh script — called by GitHub Actions cron.

Steps:
1. Open DB connection
2. For each tracked show, fetch new episodes from feed
3. Parse → dedup → insert
4. Generate embeddings for new episodes
5. Update vector index
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("daily_refresh")


async def run_daily_refresh():
    """Main daily refresh routine."""
    from app.database import async_session_factory, Show, Episode
    from app.data_pipeline.feed_parser import parse_feed
    from app.vector_pipeline.indexer import index_missing_embeddings

    start = datetime.now(timezone.utc)
    logger.info("Daily refresh started at %s", start.isoformat())

    async with async_session_factory() as session:
        # 1. Get all tracked shows with feed URLs
        result = await session.execute(
            select(Show.id, Show.title, Show.feed_url).where(Show.feed_url.isnot(None))
        )
        shows = result.all()
        logger.info("Found %d tracked shows", len(shows))

        # 2. For each show, fetch recent episodes
        total_new = 0
        for show_id, title, feed_url in shows:
            try:
                episodes = parse_feed(feed_url)
                if not episodes:
                    continue

                # Get existing episode IDs for dedup
                existing_result = await session.execute(
                    select(Episode.source_episode_id, Episode.title).where(
                        Episode.show_id == show_id
                    )
                )
                existing_keys = set()
                for row in existing_result.all():
                    if row[0]:
                        existing_keys.add(row[0])
                    else:
                        existing_keys.add(row[1].strip().lower()[:100])

                from app.data_pipeline.etl import _dedup_key, _detect_language

                new_count = 0
                for ep in episodes:
                    key = _dedup_key(ep)
                    if key in existing_keys:
                        continue

                    new_ep = Episode(
                        show_id=show_id,
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
                    new_count += 1
                    total_new += 1

                if new_count > 0:
                    logger.info("  [%s] %d new episodes", title, new_count)

            except Exception as exc:
                logger.warning("  [%s] ERROR: %s", title, exc)
                continue

        await session.commit()

        # 3. Generate embeddings for new episodes (in batches)
        if total_new > 0:
            logger.info("Generating embeddings for %d new episodes...", total_new)
            indexed = await index_missing_embeddings(session, batch_size=50)
            logger.info("  Indexed %d embeddings", indexed)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Daily refresh completed in %.1f seconds. %d new episodes added.", elapsed, total_new)
    return total_new


def main():
    """Entry point for CLI (called by GitHub Actions)."""
    total = asyncio.run(run_daily_refresh())
    print(f"DAILY_REFRESH_RESULT={total}")
    sys.exit(0)


if __name__ == "__main__":
    main()
