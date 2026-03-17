"""OpenAI API client for PR review."""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI


def review_batch(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int = 4096,
) -> tuple[str, str]:
    """Call OpenAI for one batch. Returns (raw_response_json_string, model_used)."""
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model or "gpt-4o",
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice and choice.message else ""
    # Normalize to same shape as Anthropic for _extract_text_from_response
    body: dict[str, Any] = {
        "content": [{"type": "text", "text": content or ""}],
    }
    return json.dumps(body), (response.model or model or "gpt-4o")
