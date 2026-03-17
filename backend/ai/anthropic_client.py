"""Anthropic API client for PR review."""
from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic


def review_batch(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int = 4096,
) -> tuple[str, str]:
    """Call Anthropic for one batch. Returns (raw_response_json_string, model_used)."""
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model or "claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    # Return body in same shape as API (content with text blocks)
    body: dict[str, Any] = {
        "content": [
            {"type": "text", "text": block.text}
            for block in response.content
            if hasattr(block, "text")
        ],
    }
    return json.dumps(body), response.model
