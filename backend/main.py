"""FastAPI app: webhook for GitHub PR events, settings API, serve frontend."""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import (
    auth_enabled,
    clear_session_cookie,
    require_admin,
    set_session_cookie,
    _admin_password,
)
from config import load_settings, save_settings
from github_client import get_pr_diff, post_review, create_webhook, list_repos
from review import run_review_pipeline
from runs_store import add_run, get_runs, update_run_status


def _auth_dep(request: Request) -> None:
    require_admin(request)

# In-memory OAuth state (state -> timestamp) for CSRF; cleared on use and when stale
_oauth_states: dict[str, float] = {}
_OAUTH_STATE_TTL = 600  # 10 min

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
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    webhook_secret: str | None = None
    ai_provider: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    model: str | None = None
    max_batch_chars: int | None = None
    max_tokens: int | None = None
    max_inline_comments: int | None = None


class CreateWebhookBody(BaseModel):
    owner: str
    repo: str
    webhook_url: str | None = None


class LoginBody(BaseModel):
    password: str


def _prune_oauth_states() -> None:
    now = time.time()
    for k in list(_oauth_states):
        if now - _oauth_states[k] > _OAUTH_STATE_TTL:
            del _oauth_states[k]


def _request_base_url(request: Request) -> str:
    """Base URL for redirect_uri etc. Use X-Forwarded-Proto/Host when behind a proxy (e.g. Railway)."""
    base = str(request.base_url).rstrip("/")
    proto = request.headers.get("X-Forwarded-Proto", "").strip().lower()
    host = request.headers.get("X-Forwarded-Host", "").strip() or request.headers.get("Host", "").strip()
    if proto and host:
        return f"{proto}://{host}"
    return base


def _constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


@app.post("/api/auth/login")
def api_login(body: LoginBody, request: Request):
    """Accept admin password and set session cookie. Returns 401 if auth disabled or wrong password."""
    if not auth_enabled():
        raise HTTPException(status_code=400, detail="Admin password not configured (set ADMIN_PASSWORD).")
    secret = _admin_password()
    if not _constant_time_compare(body.password, secret):
        raise HTTPException(status_code=401, detail="Invalid password.")
    response = JSONResponse(content={"ok": True})
    secure = (
        request.url.scheme == "https"
        or request.headers.get("X-Forwarded-Proto") == "https"
        or os.environ.get("SECURE_COOKIE") == "1"
    )
    set_session_cookie(response, secret, secure=secure)
    return response


@app.post("/api/auth/logout")
def api_logout():
    response = JSONResponse(content={"ok": True})
    clear_session_cookie(response)
    return response


@app.get("/api/auth/status")
def api_auth_status(request: Request):
    """Return whether auth is required and whether the current request is authenticated."""
    if not auth_enabled():
        return {"auth_required": False, "authenticated": True}
    from auth import get_session_cookie, verify_session_cookie
    cookie = get_session_cookie(request)
    secret = _admin_password()
    return {"auth_required": True, "authenticated": bool(cookie and verify_session_cookie(cookie, secret))}


@app.get("/api/settings")
def api_get_settings(request: Request, _: None = Depends(_auth_dep)):
    s = load_settings()
    # Mask secrets in response
    out = dict(s)
    if out.get("github_token"):
        out["github_token"] = "***" + out["github_token"][-4:] if len(out["github_token"]) > 4 else "***"
    if out.get("github_oauth_client_secret"):
        out["github_oauth_client_secret"] = "***" if out["github_oauth_client_secret"] else ""
    if out.get("webhook_secret"):
        out["webhook_secret"] = "***" if out["webhook_secret"] else ""
    if out.get("openai_api_key"):
        out["openai_api_key"] = "***"
    if out.get("anthropic_api_key"):
        out["anthropic_api_key"] = "***"
    return out


@app.post("/api/settings")
def api_post_settings(update: SettingsUpdate, request: Request, _: None = Depends(_auth_dep)):
    s = load_settings()
    if update.github_token is not None:
        if not update.github_token.startswith("***"):
            s["github_token"] = update.github_token
    if update.github_oauth_client_id is not None:
        s["github_oauth_client_id"] = update.github_oauth_client_id
    if update.github_oauth_client_secret is not None and update.github_oauth_client_secret and not update.github_oauth_client_secret.startswith("***"):
        s["github_oauth_client_secret"] = update.github_oauth_client_secret
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


def _run_review(owner: str, repo: str, pull_number: int, head_sha: str, run_id: str = ""):
    if run_id:
        update_run_status(run_id, "running")
    try:
        settings = load_settings()
        token = (settings.get("github_token") or "").strip()
        if not token:
            logger.error("GitHub token not configured")
            if run_id:
                update_run_status(run_id, "failure", "GitHub token not configured")
            return
        diff = get_pr_diff(token, owner, repo, pull_number)
        if not diff or not diff.strip():
            logger.info("No diff for PR %s/%s#%s", owner, repo, pull_number)
            post_review(
                token, owner, repo, pull_number, head_sha,
                summary="No diff to review (empty or unchanged).",
                inline_comments=[],
            )
            if run_id:
                update_run_status(run_id, "success")
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
        if run_id:
            update_run_status(run_id, "success")
    except Exception as e:
        logger.exception("Review failed: %s", e)
        if run_id:
            update_run_status(run_id, "failure", str(e))


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
    pr_url = pr.get("html_url") or f"https://github.com/{owner}/{repo_name}/pull/{pull_number}"
    run_id = add_run(owner, repo_name, pull_number, pr_url)
    background_tasks.add_task(_run_review, owner, repo_name, pull_number, head_sha, run_id)
    return JSONResponse(content={"ok": True, "review": "queued", "run_id": run_id})


@app.get("/api/auth/github")
async def auth_github(request: Request, _: None = Depends(_auth_dep)):
    """Redirect to GitHub OAuth authorize URL."""
    s = load_settings()
    client_id = (s.get("github_oauth_client_id") or "").strip()
    client_secret = (s.get("github_oauth_client_secret") or "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="GitHub OAuth not configured. Set OAuth Client ID and Secret in Settings.",
        )
    base = _request_base_url(request)
    redirect_uri = f"{base}/api/auth/github/callback"
    state = secrets.token_urlsafe(32)
    _prune_oauth_states()
    _oauth_states[state] = time.time()
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}&redirect_uri={redirect_uri}&scope=repo,read:org&state={state}"
    )
    return RedirectResponse(url=url, status_code=302)


@app.get("/api/auth/github/callback")
async def auth_github_callback(request: Request, _: None = Depends(_auth_dep)):
    """Exchange code for token and store; redirect back to app."""
    s = load_settings()
    client_id = (s.get("github_oauth_client_id") or "").strip()
    client_secret = (s.get("github_oauth_client_secret") or "").strip()
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not client_id or not client_secret:
        return RedirectResponse(url="/?github=error", status_code=302)
    _prune_oauth_states()
    if not state or state not in _oauth_states:
        return RedirectResponse(url="/?github=error&reason=state", status_code=302)
    del _oauth_states[state]
    base = _request_base_url(request)
    redirect_uri = f"{base}/api/auth/github/callback"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
    if r.status_code != 200:
        return RedirectResponse(url="/?github=error", status_code=302)
    data = r.json()
    token = (data.get("access_token") or "").strip()
    if not token:
        return RedirectResponse(url="/?github=error", status_code=302)
    s = load_settings()
    s["github_token"] = token
    save_settings(s)
    return RedirectResponse(url="/?github=connected", status_code=302)


@app.get("/api/repos")
def api_list_repos(request: Request, _: None = Depends(_auth_dep)):
    """List repos the user has access to (requires GitHub token)."""
    s = load_settings()
    token = (s.get("github_token") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="GitHub token not set. Connect GitHub or paste a token.")
    try:
        repos = list_repos(token)
        return {"repos": repos}
    except Exception as e:
        logger.exception("List repos failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/webhooks/create")
async def api_create_webhook(request: Request, body: CreateWebhookBody, _: None = Depends(_auth_dep)):
    """Create a webhook on the given repo. Uses stored token and optional webhook_url (default: request origin + path)."""
    s = load_settings()
    token = (s.get("github_token") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="GitHub token not set. Connect GitHub or paste a token.")
    webhook_url = (body.webhook_url or "").strip()
    if not webhook_url:
        base = _request_base_url(request)
        webhook_url = f"{base}/api/webhook/github"
    secret = (s.get("webhook_secret") or "").strip()
    try:
        result = create_webhook(token, body.owner, body.repo, webhook_url, secret)
        return {"ok": True, "hook_id": result.get("id"), "message": f"Webhook added to {body.owner}/{body.repo}"}
    except Exception as e:
        logger.exception("Create webhook failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/runs")
def api_get_runs(request: Request, _: None = Depends(_auth_dep), limit: int = 100):
    """List recent webhook review runs (queued, running, success, failure)."""
    runs = get_runs(limit=min(limit, 200))
    return {"runs": runs}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --- Serve frontend ---


@app.get("/favicon.svg")
def favicon():
    """Serve favicon from frontend so it works with either static or dist."""
    for directory in (FRONTEND_STATIC, FRONTEND_DIST):
        path = directory / "favicon.svg"
        if path.exists():
            return FileResponse(path, media_type="image/svg+xml")
    raise HTTPException(status_code=404)


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
