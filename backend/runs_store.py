"""Persistent store for webhook review runs (file-based JSON)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import SETTINGS_PATH

RUNS_PATH = SETTINGS_PATH.parent / "runs.json"
MAX_RUNS = 200


def _ensure_dir() -> None:
    RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_runs() -> list[dict[str, Any]]:
    _ensure_dir()
    if not RUNS_PATH.exists():
        return []
    try:
        data = json.loads(RUNS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_runs(runs: list[dict[str, Any]]) -> None:
    _ensure_dir()
    RUNS_PATH.write_text(
        json.dumps(runs[:MAX_RUNS], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_run(owner: str, repo: str, pull_number: int, pr_url: str = "") -> str:
    """Append a new run with status 'queued'. Returns run_id."""
    runs = _load_runs()
    run_id = f"{owner}/{repo}#{pull_number}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    if not pr_url:
        pr_url = f"https://github.com/{owner}/{repo}/pull/{pull_number}"
    run = {
        "id": run_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "owner": owner,
        "repo": repo,
        "pr_number": pull_number,
        "pr_url": pr_url,
        "status": "queued",
        "completed_at": None,
        "error": None,
    }
    runs.insert(0, run)
    _save_runs(runs)
    return run_id


def update_run_status(run_id: str, status: str, error: str | None = None) -> None:
    """Set run status to 'running', 'success', or 'failure'."""
    runs = _load_runs()
    for r in runs:
        if r.get("id") == run_id:
            r["status"] = status
            r["completed_at"] = datetime.now(timezone.utc).isoformat() if status in ("success", "failure") else None
            r["error"] = error
            break
    _save_runs(runs)


def get_runs(limit: int = 100) -> list[dict[str, Any]]:
    """Return runs newest first, capped at limit."""
    runs = _load_runs()
    return runs[:limit]
