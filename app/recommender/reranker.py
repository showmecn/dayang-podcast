"""LLM re-ranker — takes top-20 candidates, returns top-3 with reasons.

Uses DeepSeek to intelligently rank and explain recommendations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

_RERANK_PROMPT = """You are a podcast recommendation expert. Given a user's topic query and {num_candidates} candidate episodes, select the top {top_k} most relevant ones and provide:

1. A ranking from most to least relevant
2. A brief reason explaining why each fits
3. An estimated relevance score (0-100)

## User Query
{topic}

## Candidate Episodes
{candidates}

## Instructions
- Prioritise episodes whose title, description, or show notes directly address the user's query
- Consider both topic match and content depth (episodes with substantial show notes score higher)
- If multiple episodes match equally, prefer more recent ones
- Include diverse perspectives / shows when possible (don't pick 3 episodes from the same show)
- Return ONLY valid JSON (no markdown fences, no explanation text)

## Output Format
Return a JSON list of objects with the exact episode_id shown in brackets:
[
  {{
    "episode_id": "<exact episode_id from the list above>",
    "rank": 1,
    "reason": "Why this episode fits the topic (1-2 sentences in Chinese)",
    "relevance_score": 92
  }},
  ...
]
"""


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
)
async def rerank(
    topic: str,
    candidates: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Use LLM to re-rank and select top-K candidates.

    Args:
        topic: User's query topic
        candidates: List of candidate episode dicts from retriever
        top_k: How many to return after re-ranking

    Returns:
        Re-ranked candidates with 'reason' and 'relevance_score' added.
        Only top_k items returned.
    """
    if not candidates:
        return []

    if len(candidates) <= top_k:
        # No need to re-rank — just assign reasons
        result = []
        for i, c in enumerate(candidates):
            result.append({
                **c,
                "reason": f"Matches your query about '{topic}'",
                "relevance_score": 80,
            })
        return result

    # Build prompt
    candidates_text = _format_candidates(candidates)
    prompt = _RERANK_PROMPT.format(
        topic=topic,
        candidates=candidates_text,
        num_candidates=len(candidates),
        top_k=top_k,
    )

    # Call DeepSeek (OpenAI-compatible API)
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    model = settings.llm_model

    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )

    raw = resp.choices[0].message.content or "[]"
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]

    try:
        rankings = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM re-rank response: %s", raw[:200])
        # Fallback: return top-k by vector similarity
        return [
            {**c, "reason": f"Semantically matches your query about '{topic}'", "relevance_score": int(c["similarity"] * 100)}
            for c in candidates[:top_k]
        ]

    # Match rankings back to candidates
    candidate_map = {str(c["episode_id"]): c for c in candidates}
    result = []
    for r in sorted(rankings, key=lambda x: x.get("rank", 999)):
        ep_id = str(r.get("episode_id", ""))
        if ep_id in candidate_map:
            base = candidate_map[ep_id]
            result.append({
                **base,
                "reason": r.get("reason", f"Matches your query about '{topic}'"),
                "relevance_score": r.get("relevance_score", 80),
            })
            if len(result) >= top_k:
                break

    return result


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    """Format candidates for the LLM prompt."""
    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"[{c['episode_id']}] Episode: {c.get('episode_title', 'Untitled')}\n"
            f"    Show: {c.get('show_title', 'Unknown')}\n"
            f"    Published: {c.get('published_at', 'N/A')}\n"
            f"    Duration: {c.get('duration_sec', 0)}s\n"
            f"    Description: {(c.get('description') or '')[:300]}\n"
            f"    Show Notes: {(c.get('show_notes') or '')[:500]}\n"
        )
    return "\n".join(lines)
