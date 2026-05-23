"""Diversity post-processor — ensures top-K results span different shows.

This is a non-ML, deterministic dedup step applied after LLM re-ranking.
It does NOT touch the scoring pipeline; it simply enforces that returned
episodes come from at most 1 episode per show_id.

Strategy: show_id dedup + substitution from the candidate pool.
A replacement picks the next-highest-similarity episode from a different show.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def diversify_ranked(
    ranked: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Enforce show diversity in ranked results.

    Args:
        ranked: Re-ranked results from LLM reranker (sorted by rank/score desc).
        candidates: Full candidate pool from vector search (sorted by similarity desc).
        top_k: How many results to return.

    Returns:
        Diverse result list with at most 1 episode per show_id.
        Falls back to at least 2 different shows if pool too small.
    """
    if len(ranked) <= 1:
        return ranked

    # --- Phase 1: Dedup — keep highest-scored episode per show ---
    seen_sids: set[str] = set()
    result: list[dict[str, Any]] = []

    for ep in ranked:
        sid = str(ep.get("show_id", ""))
        if sid not in seen_sids:
            seen_sids.add(sid)
            result.append(ep)
        # else: this show already has a higher-ranked episode, skip

    logger.debug(
        "Dedup: %d ranked → %d unique shows", len(ranked), len(result)
    )

    # Already diverse enough
    if len(result) >= top_k:
        return result[:top_k]

    # --- Phase 2: Substitution — find fillers from different shows ---
    needed = top_k - len(result)
    for c in candidates:
        if needed <= 0:
            break
        sid = str(c.get("show_id", ""))
        if sid not in seen_sids:
            filler = {
                **c,
                "reason": f"Also matches your query about this topic",
                "relevance_score": _similarity_to_score(c.get("similarity", 0.5)),
            }
            result.append(filler)
            seen_sids.add(sid)
            needed -= 1

    # --- Phase 3: If pool truly exhausted (edge case), allow repeats ---
    if len(result) < top_k:
        logger.warning(
            "Not enough diverse shows (%d unique from %d candidates) — "
            "repeating shows to fill top-%d",
            len(seen_sids),
            len(candidates),
            top_k,
        )
        # Fill remaining slots from ranked (allows duplicate shows as last resort)
        for ep in ranked:
            if len(result) >= top_k:
                break
            sid = str(ep.get("show_id", ""))
            # Already have this show but we have no choice
            candidate_ids = {str(r.get("episode_id", "")) for r in result}
            if str(ep.get("episode_id", "")) not in candidate_ids:
                result.append(ep)

    return result[:top_k]


def _similarity_to_score(similarity: float) -> int:
    """Map cosine similarity (0-1) to a conservative relevance score (0-100)."""
    return max(50, min(99, int(similarity * 95)))
