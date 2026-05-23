"""Summary generation + key timestamp extraction + recommendation reason.

Uses DeepSeek to generate ~200 char Chinese summaries from show notes / description.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


_SUMMARY_PROMPT = """You are a professional podcast summariser. Given a podcast episode's metadata and show notes, generate:

1. A concise ~200-word summary in **Chinese** capturing key arguments and takeaways
2. Any notable timestamps mentioned in the show notes (with labels)

## Episode Details
- Title: {title}
- Show: {show_title}
- Description: {description}
- Show Notes: {show_notes}

## Instructions
- Focus on concrete takeaways, not generic praise
- Use neutral, factual language
- If show notes are thin, generate a summary from the description alone
- Add disclaimer: the summary is AI-generated from show notes
- Timestamps should be exact from show notes, not guessed

## Output Format
Return ONLY valid JSON:
{{
  "summary": "~200字中文摘要",
  "timestamps": [
    {{"time_str": "12:34", "label": "讨论核心论点"}},
    {{"time_str": "45:00", "label": "案例分享"}}
  ]
}}

If no timestamps exist in the show notes, return empty array for timestamps.
"""


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
)
async def generate_summary(
    title: str,
    show_title: str,
    description: str | None,
    show_notes: str | None,
) -> dict[str, Any]:
    """Generate summary and extract timestamps for a single episode.

    Returns: {"summary": "...", "timestamps": [{"time_str": "...", "label": "..."}, ...]}
    """
    # Truncate long fields
    desc = (description or "")[:2000]
    notes = (show_notes or "")[:5000]

    prompt = _SUMMARY_PROMPT.format(
        title=title,
        show_title=show_title,
        description=desc,
        show_notes=notes,
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
        max_tokens=1000,
    )

    raw = resp.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse summary JSON: %s", raw[:100])
        result = {
            "summary": f"Based on the episode '{title}' from {show_title}. "
                       f"{description[:200] if description else 'No summary available.'}",
            "timestamps": [],
        }

    return result
