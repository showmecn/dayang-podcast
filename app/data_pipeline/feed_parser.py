"""RSS feed parser — turns raw XML feeds into structured episode data.

Wraps feedparser with robust error handling.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser


def parse_feed(feed_url: str, timeout: int = 30) -> list[dict[str, Any]]:
    """Fetch and parse an RSS/Atom feed. Returns list of episode dicts.

    Each episode dict contains:
        title, description, show_notes, published_at, duration_sec,
        audio_url, episode_url, source_episode_id
    """
    parsed = feedparser.parse(feed_url)
    if parsed.bozo and not parsed.entries:
        raise FeedParseError(f"Failed to parse feed: {feed_url}", bozo_exception=parsed.bozo_exception)

    episodes = []
    for entry in parsed.entries:
        try:
            episode = _parse_entry(entry)
            if episode:
                episodes.append(episode)
        except Exception:
            # Skip malformed entries — one bad entry shouldn't kill the feed
            continue

    return episodes


def _parse_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a single feed entry into our episode format."""
    title = entry.get("title", "").strip()
    if not title:
        return None

    # Extract description (prefer content if available)
    description = ""
    if hasattr(entry, "content") and entry.content:
        description = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        description = entry.get("summary", "")
    elif hasattr(entry, "description"):
        description = entry.get("description", "")
    # Clean HTML tags
    description = _strip_html(description)

    # Show notes (often in content:encoded)
    show_notes = ""
    if hasattr(entry, "content_encoded"):
        show_notes = _strip_html(entry.get("content_encoded", ""))
    if not show_notes:
        show_notes = description

    # Published date
    published_at = _parse_date(entry)

    # Duration
    duration_sec = _parse_duration(entry)

    # Audio URL (enclosure)
    audio_url = None
    episode_url = None
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            href = enc.get("href", "")
            mime = enc.get("type", "")
            if "audio" in mime or href.endswith((".mp3", ".m4a", ".mp4", ".ogg", ".wav")):
                audio_url = href
                break

    # Episode URL (link)
    episode_url = entry.get("link", "")

    # Source episode ID (guid)
    source_episode_id = entry.get("id", entry.get("guid", ""))
    if hasattr(source_episode_id, "__dict__"):
        source_episode_id = source_episode_id.get("#text", str(source_episode_id))

    return {
        "title": title[:500],
        "description": description[:5000] if description else None,
        "show_notes": show_notes[:10000] if show_notes else None,
        "published_at": published_at,
        "duration_sec": duration_sec,
        "audio_url": audio_url,
        "episode_url": episode_url,
        "source_episode_id": str(source_episode_id) if source_episode_id else None,
    }


def _parse_date(entry: dict[str, Any]) -> datetime:
    """Parse published/updated date from entry."""
    for field in ("published_parsed", "updated_parsed"):
        time_tuple = entry.get(field)
        if time_tuple:
            try:
                from time import mktime

                return datetime.fromtimestamp(mktime(time_tuple), tz=timezone.utc)
            except (OSError, ValueError):
                continue

    # Fallback: try raw strings
    for field in ("published", "updated", "pubDate"):
        raw = entry.get(field)
        if raw:
            try:
                return parsedate_to_datetime(raw).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                # Try parsing ISO 8601
                from dateutil.parser import parse as dt_parse

                try:
                    return dt_parse(raw).replace(tzinfo=timezone.utc)
                except (ValueError, OverflowError):
                    continue

    return datetime.now(timezone.utc)


def _parse_duration(entry: dict[str, Any]) -> int | None:
    """Parse episode duration into seconds."""
    raw = entry.get("itunes_duration")
    if not raw:
        raw = entry.get("duration")

    if not raw:
        return None

    raw_str = str(raw).strip()

    # HH:MM:SS or MM:SS
    match = re.match(r"(?:(\d+):)?(\d+):(\d+)", raw_str)
    if match:
        h = int(match.group(1)) if match.group(1) else 0
        m = int(match.group(2))
        s = int(match.group(3))
        return h * 3600 + m * 60 + s

    # Just digits (seconds)
    try:
        return int(raw_str)
    except ValueError:
        return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class FeedParseError(Exception):
    def __init__(self, message: str, bozo_exception: Exception | None = None):
        self.bozo_exception = bozo_exception
        super().__init__(message)
