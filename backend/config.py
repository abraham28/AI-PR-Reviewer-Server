"""Settings storage: file-based JSON, loaded on startup and saved on update."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "settings.json"


def _ensure_data_dir() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    _ensure_data_dir()
    if not SETTINGS_PATH.exists():
        return _default_settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return {**_default_settings(), **data}
    except Exception:
        return _default_settings()


def _default_settings() -> dict[str, Any]:
    return {
        "github_token": "",
        "webhook_secret": "",
        "ai_provider": "anthropic",  # "openai" | "anthropic"
        "openai_api_key": "",
        "anthropic_api_key": "",
        "model": "",  # e.g. "claude-sonnet-4-20250514" or "gpt-4o"
        "max_batch_chars": 12000,
        "max_tokens": 4096,
        "max_inline_comments": 20,
    }


def save_settings(settings: dict[str, Any]) -> None:
    _ensure_data_dir()
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
