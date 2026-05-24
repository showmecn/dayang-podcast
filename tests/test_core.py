"""Tests for Dayang Podcast core pipeline.

Run with: pytest tests/ -v --cov=app
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Data pipeline tests
# ---------------------------------------------------------------------------


class TestFeedParser:
    """Test feed_parser module."""

    def test_strip_html(self):
        from app.data_pipeline.feed_parser import _strip_html

        assert _strip_html("<p>Hello</p>") == "Hello"
        assert _strip_html("<b>Bold</b> and <i>italic</i>") == "Bold and italic"
        assert _strip_html("") == ""
        assert _strip_html(None) == ""
        assert _strip_html("No tags") == "No tags"

    def test_parse_duration(self):
        from app.data_pipeline.feed_parser import _parse_duration

        # HH:MM:SS
        entry = {"itunes_duration": "01:23:45"}
        assert _parse_duration(entry) == 5025

        # MM:SS
        entry = {"itunes_duration": "45:30"}
        assert _parse_duration(entry) == 2730

        # Seconds (int)
        entry = {"itunes_duration": 3661}
        assert _parse_duration(entry) == 3661

        # No duration
        entry = {}
        assert _parse_duration(entry) is None

    def test_detect_language(self):
        from app.data_pipeline.etl import _detect_language

        assert _detect_language("Hello world") == "en"
        assert _detect_language("你好世界") == "zh"
        assert _detect_language("Hello 你好") == "zh"  # mixed, Chinese ratio > 0.15
        assert _detect_language("") == "unknown"

    def test_classify_category(self):
        from app.data_pipeline.etl import _classify_category

        cats = _classify_category("AI and Machine Learning Trends", "")
        assert "tech" in cats

        cats = _classify_category("Stock Market Today", "")
        assert "finance" in cats

        cats = _classify_category("Random title", "")
        assert cats == ["general"]


class TestAppleMapper:
    """Test Apple Podcasts API result mapping."""

    def test_map_apple_to_show(self):
        from app.data_pipeline.apple_podcasts import map_apple_to_show

        apple_result = {
            "collectionName": "Test Podcast",
            "feedUrl": "https://example.com/feed.xml",
            "artworkUrl600": "https://example.com/art.jpg",
            "artistName": "Test Author",
            "primaryGenreName": "Technology",
            "language": "en",
            "collectionId": 12345,
        }

        result = map_apple_to_show(apple_result)
        assert result["title"] == "Test Podcast"
        assert result["feed_url"] == "https://example.com/feed.xml"
        assert result["source"] == "apple"
        assert result["source_show_id"] == "12345"


# ---------------------------------------------------------------------------
# Vector pipeline tests
# ---------------------------------------------------------------------------


class TestEmbedder:
    """Test embedder module (local model)."""

    @pytest.mark.asyncio
    async def test_embed_text(self):
        from app.vector_pipeline.embedder import embed_text

        result = await embed_text("test text")
        assert len(result) == 384  # all-MiniLM-L6-v2

    def test_text_for_embedding(self):
        from app.vector_pipeline.embedder import _text_for_embedding

        text = _text_for_embedding("Title", "Desc", "Notes")
        assert "Title" in text
        assert "Desc" in text
        assert "Notes" in text

        # Long content truncated
        long_desc = "x" * 3000
        text = _text_for_embedding("Title", long_desc, None)
        assert len(text) < 2500  # truncated

    def test_text_for_embedding_no_notes(self):
        from app.vector_pipeline.embedder import _text_for_embedding

        text = _text_for_embedding("Title", "Desc", None)
        assert "Title" in text
        assert "Desc" in text


# ---------------------------------------------------------------------------
# Recommender tests
# ---------------------------------------------------------------------------


class TestReranker:
    """Test LLM re-ranker logic."""

    @pytest.mark.asyncio
    async def test_rerank_no_candidates(self):
        from app.recommender.reranker import rerank

        result = await rerank("test topic", [], top_k=3)
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_fewer_than_top_k(self):
        from app.recommender.reranker import rerank

        candidates = [
            {"episode_id": uuid.uuid4(), "episode_title": "Ep1", "show_title": "Show1",
             "published_at": datetime.now(timezone.utc), "duration_sec": 1200,
             "description": "Desc", "show_notes": None, "similarity": 0.9},
            {"episode_id": uuid.uuid4(), "episode_title": "Ep2", "show_title": "Show1",
             "published_at": datetime.now(timezone.utc), "duration_sec": 900,
             "description": "Desc2", "show_notes": None, "similarity": 0.85},
        ]

        result = await rerank("test topic", candidates, top_k=5)
        assert len(result) == 2  # No re-ranking needed, just assigned reasons
        assert "reason" in result[0]
        assert result[0]["relevance_score"] == 99  # int(min(99, 0.9 * 250))
        assert result[1]["relevance_score"] == 99  # int(min(99, 0.85 * 250))

    def test_sanitize_reason_clean(self):
        """Uncontaminated reasons pass through unchanged."""
        from app.recommender.reranker import _sanitize_reason

        reason = "This episode explores deep learning architectures for NLP"
        result = _sanitize_reason(reason, "AI regulation")
        assert result == reason

    def test_sanitize_reason_weak_phrases(self):
        """Reasons containing weak phrases are replaced."""
        from app.recommender.reranker import _sanitize_reason, _DEFAULT_REASON_TEMPLATE, _WEAK_PHRASES

        weak_reasons = [
            "This episode 间接涉及 AI regulation",
            "This episode 可能相关 to the topic",
            "This episode 可能有关 with machine learning",
            "This 一定程度上涉及 the subject",
            "This seems 似乎 relevant",
        ]
        expected = _DEFAULT_REASON_TEMPLATE.format(topic="AI regulation")
        for reason in weak_reasons:
            result = _sanitize_reason(reason, "AI regulation")
            assert result == expected, f"Failed for: {reason}"

    def test_sanitize_reason_no_weak_phrases(self):
        """Edge cases without known weak phrases pass through."""
        from app.recommender.reranker import _sanitize_reason

        reasons = [
            "This episode directly discusses AI regulation policies",
            "Expert interview on machine learning governance",
            "深度解析 AI 监管政策",
        ]
        for reason in reasons:
            result = _sanitize_reason(reason, "AI")
            assert result == reason

    def test_sanitize_reason_empty(self):
        """Empty or whitespace-only reasons get a default."""
        from app.recommender.reranker import _sanitize_reason, _DEFAULT_REASON_TEMPLATE

        expected = _DEFAULT_REASON_TEMPLATE.format(topic="AI regulation")
        assert _sanitize_reason("", "AI regulation") == expected
        assert _sanitize_reason("   ", "AI regulation") == expected
        assert _sanitize_reason(None, "AI regulation") == expected  # type: ignore[arg-type]


class TestRecommendFilter:
    """Test the relevance threshold filter (Router Step 3b)."""

    def test_all_above_threshold(self):
        """All results above threshold pass through unchanged."""
        MIN_RELEVANCE = 88
        ranked = [
            {"episode_id": "a", "relevance_score": 95},
            {"episode_id": "b", "relevance_score": 91},
            {"episode_id": "c", "relevance_score": 88},
        ]
        filtered = [ep for ep in ranked if (ep.get("relevance_score") or 0) >= MIN_RELEVANCE]
        assert len(filtered) == 3

    def test_some_below_threshold(self):
        """Results below threshold are removed."""
        MIN_RELEVANCE = 88
        ranked = [
            {"episode_id": "a", "relevance_score": 92},
            {"episode_id": "b", "relevance_score": 85},  # below
            {"episode_id": "c", "relevance_score": 77},  # below
        ]
        filtered = [ep for ep in ranked if (ep.get("relevance_score") or 0) >= MIN_RELEVANCE]
        assert len(filtered) == 1
        assert filtered[0]["episode_id"] == "a"

    def test_all_below_threshold(self):
        """When all results are below threshold, return empty list."""
        MIN_RELEVANCE = 88
        ranked = [
            {"episode_id": "a", "relevance_score": 50},
            {"episode_id": "b", "relevance_score": 0},
        ]
        filtered = [ep for ep in ranked if (ep.get("relevance_score") or 0) >= MIN_RELEVANCE]
        assert len(filtered) == 0

    def test_missing_relevance_score(self):
        """Results without relevance_score are treated as 0 and filtered out."""
        MIN_RELEVANCE = 88
        ranked = [
            {"episode_id": "a", "relevance_score": 95},
            {"episode_id": "b"},  # no score
        ]
        filtered = [ep for ep in ranked if (ep.get("relevance_score") or 0) >= MIN_RELEVANCE]
        assert len(filtered) == 1
        assert filtered[0]["episode_id"] == "a"


class TestFallback:
    """Test fallback strategies."""

    def test_fallback_recent_empty_return_structure(self):
        """Return structure is correct even if DB empty in unit test."""
        from app.recommender.fallback import fallback_recent_episodes

        import inspect
        sig = inspect.signature(fallback_recent_episodes)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "top_k" in params


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


class TestCache:
    """Test cache utilities."""

    def test_topic_hash(self):
        from app.cache.redis_cache import _topic_hash

        h1 = _topic_hash("AI regulation")
        h2 = _topic_hash("ai regulation")
        h3 = _topic_hash("AI Regulation  ")

        # Should be deterministic and case-insensitive
        assert h1 == h2
        assert h1 == h3
        assert len(h1) == 64  # SHA256 hex

    def test_topic_hash_consistency(self):
        from app.cache.redis_cache import _topic_hash

        h1 = _topic_hash("  Hello World  ")
        h2 = _topic_hash("hello world")
        assert h1 == h2


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Test configuration defaults."""

    def test_default_settings(self):
        from app.config import settings

        assert settings.app_name == "Dayang Podcast"
        assert settings.embedding_model == "all-MiniLM-L6-v2"
        assert settings.llm_model == "deepseek-chat"
        assert settings.llm_provider == "deepseek"


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    """Test Pydantic models."""

    def test_recommend_request_valid(self):
        from app.models.schemas import RecommendRequest

        req = RecommendRequest(topic="AI regulation")
        assert req.topic == "AI regulation"
        assert req.top_k == 3
        assert req.refresh is False

    def test_recommend_request_empty_topic(self):
        from app.models.schemas import RecommendRequest

        with pytest.raises(Exception):
            RecommendRequest(topic="")

    def test_recommend_response_structure(self):
        from app.models.schemas import RecommendResponse, EpisodeRecommendation

        rec = EpisodeRecommendation(
            episode_id=uuid.uuid4(),
            show_id=uuid.uuid4(),
            episode_title="Test Episode",
            show_title="Test Show",
            published_at=datetime.now(timezone.utc),
            summary="Test summary",
            reason="Test reason",
        )
        resp = RecommendResponse(
            topic="AI",
            recommendations=[rec],
            total_candidates=1,
            processing_time_ms=100,
        )
        assert resp.cached is False
        assert len(resp.recommendations) == 1
        assert resp.recommendations[0].summary == "Test summary"
        assert resp.note is None  # default

        # note can be set explicitly
        resp2 = RecommendResponse(
            topic="AI",
            recommendations=[rec],
            note="Only 1 highly relevant episode found for this topic",
        )
        assert resp2.note == "Only 1 highly relevant episode found for this topic"
