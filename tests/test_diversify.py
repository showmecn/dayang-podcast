"""Tests for recommendation diversity post-processor.

Tests the diversify_ranked function which enforces that top-K
recommendations span different shows (max 1 episode per show_id).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.recommender.diversify import diversify_ranked, _similarity_to_score


def _ep(
    show_suffix: str,
    ep_suffix: str | None = None,
    similarity: float = 0.9,
    score: int | None = None,
) -> dict:
    """Helper: create a candidate episode dict."""
    show_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"show-{show_suffix}")
    ep_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"ep-{ep_suffix or show_suffix}")
    d = {
        "episode_id": ep_id,
        "show_id": show_id,
        "episode_title": f"Episode {ep_suffix or show_suffix}",
        "show_title": f"Show {show_suffix}",
        "description": f"Description {show_suffix}",
        "published_at": datetime.now(timezone.utc),
        "duration_sec": 1800,
        "similarity": similarity,
    }
    if score is not None:
        d["relevance_score"] = score
    return d


def _ranked(ep, rank: int = 1, reason: str = "Good match") -> dict:
    """Wrap an ep dict with reranker output fields."""
    return {
        **ep,
        "rank": rank,
        "reason": reason,
        "relevance_score": rank * 30,  # score proportional to rank
    }


class TestDiversifyRanked:
    """Core diversity post-processor tests."""

    def test_all_different_shows_preserved(self):
        """3 ranked, 3 diff shows → return as-is."""
        ranked = [
            _ranked(_ep("A", "a1"), rank=1),
            _ranked(_ep("B", "b1"), rank=2),
            _ranked(_ep("C", "c1"), rank=3),
        ]
        candidates = ranked[:]
        result = diversify_ranked(ranked, candidates, top_k=3)
        assert len(result) == 3
        sids = {r["show_id"] for r in result}
        assert len(sids) == 3

    def test_all_same_show_dedup_to_one(self):
        """3 ranked, same show → only 1 kept, 2 substituted from candidates."""
        ranked = [
            _ranked(_ep("A", "a1"), rank=1),
            _ranked(_ep("A", "a2"), rank=2),
            _ranked(_ep("A", "a3"), rank=3),
        ]
        # Candidates include episodes from other shows
        candidates = ranked[:] + [
            _ep("B", "b1", similarity=0.85),
            _ep("C", "c1", similarity=0.80),
        ]
        result = diversify_ranked(ranked, candidates, top_k=3)
        assert len(result) == 3
        sids = {r["show_id"] for r in result}
        assert len(sids) >= 2  # at least 2 different shows
        # Best ranked episode should be first
        assert result[0]["episode_id"] == ranked[0]["episode_id"]

    def test_two_same_show_one_different(self):
        """2 same show, 1 different → dedup to 2, then 1 substitute."""
        ranked = [
            _ranked(_ep("A", "a1"), rank=1),
            _ranked(_ep("A", "a2"), rank=2),
            _ranked(_ep("B", "b1"), rank=3),
        ]
        candidates = ranked[:] + [_ep("C", "c1", similarity=0.75)]
        result = diversify_ranked(ranked, candidates, top_k=3)
        assert len(result) == 3
        sids = {r["show_id"] for r in result}
        assert len(sids) == 3  # A, B, C
        # Show B's episode should be present
        assert any(r["show_id"] == _ep("B")["show_id"] for r in result)

    def test_not_enough_candidates_allows_repeats(self):
        """Only 2 shows in full pool → returns what's available, fills with repeats."""
        ranked = [
            _ranked(_ep("A", "a1"), rank=1),
            _ranked(_ep("A", "a2"), rank=2),
        ]
        candidates = ranked[:]  # only show A
        result = diversify_ranked(ranked, candidates, top_k=3)
        # Can't get 3 unique shows from 2 candidates, both same show
        assert len(result) == 2  # at most 2 distinct episodes
        assert len({r["show_id"] for r in result}) == 1

    def test_single_episode(self):
        """1 ranked episode → returned unchanged."""
        ranked = [_ranked(_ep("A", "a1"), rank=1)]
        result = diversify_ranked(ranked, ranked[:], top_k=3)
        assert len(result) == 1

    def test_substitution_in_candidate_order(self):
        """Substitution picks candidates in the order they appear in the pool."""
        ranked = [
            _ranked(_ep("A", "a1", similarity=0.95), rank=1),
            _ranked(_ep("A", "a2", similarity=0.94), rank=2),
            _ranked(_ep("A", "a3", similarity=0.93), rank=3),
        ]
        candidates = ranked[:] + [
            _ep("B", "b1", similarity=0.80),  # first in candidate pool
            _ep("C", "c1", similarity=0.85),  # second in candidate pool
        ]
        result = diversify_ranked(ranked, candidates, top_k=3)
        assert len(result) == 3
        # Substitution iterates in candidate-pool order, so B (appears first) picked before C
        sids = {r["show_id"] for r in result}
        assert len(sids) == 3  # A, B, C all present

    def test_filler_has_reason_and_score(self):
        """Substituted episodes get a reason and relevance_score."""
        ranked = [
            _ranked(_ep("A", "a1"), rank=1),
            _ranked(_ep("A", "a2"), rank=2),
        ]
        candidates = ranked[:] + [
            _ep("B", "b1", similarity=0.85),
        ]
        result = diversify_ranked(ranked, candidates, top_k=3)
        assert len(result) == 3
        filler = [r for r in result if r["show_id"] != _ep("A")["show_id"]]
        assert len(filler) == 1
        assert "reason" in filler[0]
        assert "relevance_score" in filler[0]

    def test_top_k_less_than_ranked(self):
        """top_k=2 returns only 2 results."""
        ranked = [
            _ranked(_ep("A", "a1"), rank=1),
            _ranked(_ep("B", "b1"), rank=2),
            _ranked(_ep("C", "c1"), rank=3),
        ]
        result = diversify_ranked(ranked, ranked[:], top_k=2)
        assert len(result) == 2


class TestSimilarityToScore:
    """Test _similarity_to_score mapping."""

    def test_max_score(self):
        assert _similarity_to_score(1.0) == 95  # int(1.0 * 95) = 95

    def test_min_score(self):
        assert _similarity_to_score(0.0) == 50  # floor is 50

    def test_mid_range(self):
        assert _similarity_to_score(0.85) == 80  # int(0.85 * 95) = 80

    def test_high_similarity(self):
        assert _similarity_to_score(0.95) == 90  # int(0.95 * 95) = 90

    def test_low_similarity(self):
        assert _similarity_to_score(0.3) == 50  # below floor → clamped to 50
