"""FastAPI app: webhook for GitHub PR events, settings API, serve frontend."""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import load_settings, save_settings
from github_client import get_pr_diff, post_review
from review import run_review_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI PR Reviewer", version="1.0.0")

# Frontend: prefer built SPA (frontend/dist), else static (frontend/)
ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
FRONTEND_STATIC = ROOT / "frontend"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
elif FRONTEND_STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_STATIC)), name="static")

executor = ThreadPoolExecutor(max_workers=2)


# --- Settings API ---


class SettingsUpdate(BaseModel):
    github_token: str | None = None
    webhook_secret: str | None = None
    ai_provider: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    model: str | None = None
    max_batch_chars: int | None = None
    max_tokens: int | None = None
    max_inline_comments: int | None = None


@app.get("/api/settings")
def api_get_settings():
    s = load_settings()
    # Mask secrets in response
    out = dict(s)
    if out.get("github_token"):
        out["github_token"] = "***" + out["github_token"][-4:] if len(out["github_token"]) > 4 else "***"
    if out.get("webhook_secret"):
        out["webhook_secret"] = "***" if out["webhook_secret"] else ""
    if out.get("openai_api_key"):
        out["openai_api_key"] = "***"
    if out.get("anthropic_api_key"):
        out["anthropic_api_key"] = "***"
    return out


@app.post("/api/settings")
def api_post_settings(update: SettingsUpdate):
    s = load_settings()
    if update.github_token is not None:
        if not update.github_token.startswith("***"):
            s["github_token"] = update.github_token
    if update.webhook_secret is not None:
        s["webhook_secret"] = update.webhook_secret
    if update.ai_provider is not None:
        s["ai_provider"] = update.ai_provider
    if update.openai_api_key is not None:
        if not update.openai_api_key.startswith("***"):
            s["openai_api_key"] = update.openai_api_key
    if update.anthropic_api_key is not None:
        if not update.anthropic_api_key.startswith("***"):
            s["anthropic_api_key"] = update.anthropic_api_key
    if update.model is not None:
        s["model"] = update.model
    if update.max_batch_chars is not None:
        s["max_batch_chars"] = update.max_batch_chars
    if update.max_tokens is not None:
        s["max_tokens"] = update.max_tokens
    if update.max_inline_comments is not None:
        s["max_inline_comments"] = update.max_inline_comments
    save_settings(s)
    return {"ok": True}


def _make_call_ai(settings: dict):
    provider = (settings.get("ai_provider") or "anthropic").lower()
    model = (settings.get("model") or "").strip()
    max_tokens = int(settings.get("max_tokens") or 4096)

    def call_ai(prompt: str, system_prompt: str):
        if provider == "openai":
            from ai.openai_client import review_batch
            key = (settings.get("openai_api_key") or "").strip()
            if not key:
                raise ValueError("OpenAI API key not set")
            return review_batch(key, model or "gpt-4o", prompt, system_prompt, max_tokens)
        else:
            from ai.anthropic_client import review_batch
            key = (settings.get("anthropic_api_key") or "").strip()
            if not key:
                raise ValueError("Anthropic API key not set")
            return review_batch(key, model or "claude-sonnet-4-20250514", prompt, system_prompt, max_tokens)

    return call_ai


def _run_review(owner: str, repo: str, pull_number: int, head_sha: str):
    try:
        settings = load_settings()
        token = (settings.get("github_token") or "").strip()
        if not token:
            logger.error("GitHub token not configured")
            return
        diff = get_pr_diff(token, owner, repo, pull_number)
        if not diff or not diff.strip():
            logger.info("No diff for PR %s/%s#%s", owner, repo, pull_number)
            post_review(
                token, owner, repo, pull_number, head_sha,
                summary="No diff to review (empty or unchanged).",
                inline_comments=[],
            )
            return
        call_ai = _make_call_ai(settings)
        max_batch = int(settings.get("max_batch_chars") or 12000)
        max_comments = int(settings.get("max_inline_comments") or 20)
        summary, comments, scope, batch_warning, review_warnings, model_used = run_review_pipeline(
            diff, call_ai, max_batch_chars=max_batch, max_inline_comments=max_comments
        )
        post_review(
            token, owner, repo, pull_number, head_sha,
            summary=summary,
            inline_comments=comments,
            review_scope=scope,
            model_used=model_used,
            batch_warning=batch_warning,
            review_warnings=review_warnings,
        )
        logger.info("Posted review for %s/%s#%s", owner, repo, pull_number)
    except Exception as e:
        logger.exception("Review failed: %s", e)


def _verify_webhook(payload: bytes, signature: str | None, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/api/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    settings = load_settings()
    secret = (settings.get("webhook_secret") or "").strip()
    if secret and not _verify_webhook(raw, sig, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return JSONResponse(content={"ok": True, "ignored": "not pull_request"})
    action = body.get("action")
    if action not in ("opened", "synchronize"):
        return JSONResponse(content={"ok": True, "ignored": f"action={action}"})
    repo = body.get("repository", {})
    owner = repo.get("owner", {}).get("login") or repo.get("owner", {}).get("name")
    repo_name = repo.get("name")
    pr = body.get("pull_request", {})
    pull_number = pr.get("number")
    head_sha = (pr.get("head", {}).get("sha") or "").strip()
    if not owner or not repo_name or not pull_number or not head_sha:
        raise HTTPException(status_code=400, detail="Missing repo or PR fields")
    background_tasks.add_task(_run_review, owner, repo_name, pull_number, head_sha)
    return JSONResponse(content={"ok": True, "review": "queued"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --- Serve frontend ---


@app.get("/")
def index():
    if FRONTEND_DIST.exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    if (FRONTEND_STATIC / "index.html").exists():
        return FileResponse(FRONTEND_STATIC / "index.html")
    return JSONResponse(
        content={
            "message": "AI PR Reviewer API",
            "docs": "/docs",
            "settings": "Configure via /api/settings (POST).",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
