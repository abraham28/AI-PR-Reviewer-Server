# AI PR Reviewer

Webhook-based app that reviews GitHub pull requests with AI (OpenAI or Anthropic) and posts a summary plus inline comments. Run in Docker and expose with ngrok for GitHub webhooks.

**Deploy on Railway:** see [docs/RAILWAY.md](docs/RAILWAY.md) for push-to-GitHub and Railway deployment (no Postgres required).

## Quick start

1. **Build and run with Docker**

   ```bash
   # When exposing publicly, set an admin password (used to sign in to the settings UI)
   export ADMIN_PASSWORD="your-secret-password"
   docker compose up -d
   ```

   App: http://localhost:8000. If `ADMIN_PASSWORD` is set, you must sign in with that password to access settings.

2. **Configure in the UI** (http://localhost:8000)

   **GitHub (integrated):**
   - **Option A – OAuth:** Create a [GitHub OAuth App](https://github.com/settings/developers) and set Authorization callback URL to `http://localhost:8000/api/auth/github/callback` (or your ngrok URL + `/api/auth/github/callback`). Enter Client ID and Client Secret in the app, save, then click **Connect with GitHub**.
   - **Option B – Token:** Or paste a Personal Access Token (scope `repo`, and `read:org` for private org repos).
   - Set **Webhook secret** (optional; used when creating webhooks and validating payloads).

   **AI:** Choose Anthropic or OpenAI, set the API key, and optionally the model name. Save.

3. **Expose with ngrok** (so GitHub can reach the webhook)

   ```bash
   ngrok http 8000
   ```

   If you use ngrok, open the app via the ngrok URL and reconnect GitHub (OAuth callback URL must match the URL you use).

4. **Add webhook to a repo**

   - In the app, open **Add webhook to a repo**, click **Load repos**, pick a repo (or type `owner/repo`). Set **Webhook URL** to your public URL (e.g. ngrok) + `/api/webhook/github`, or leave empty to use the current page origin. Click **Create webhook**.
   - Or manually: Repo → Settings → Webhooks → Add webhook → Payload URL `https://YOUR-URL/api/webhook/github`, content type `application/json`, events **Pull requests**.

On **pull_request** (opened/synchronize), the app fetches the diff, runs batched AI review, and posts a summary comment plus inline comments on the PR.

## API

- `GET /` – Frontend (settings UI)
- `GET /api/auth/status` – Auth status (no auth required)
- `POST /api/auth/login` – Sign in (body: `{"password": "..."}`; sets session cookie)
- `POST /api/auth/logout` – Sign out
- `GET /api/settings` – Read settings (secrets masked; requires auth if `ADMIN_PASSWORD` set)
- `POST /api/settings` – Update settings (JSON body; requires auth if set)
- `GET /api/auth/github` – Redirect to GitHub OAuth (requires auth if set)
- `GET /api/auth/github/callback` – OAuth callback (stores token)
- `GET /api/repos` – List repos (for webhook UI; requires token)
- `POST /api/webhooks/create` – Create webhook on a repo (body: `owner`, `repo`, optional `webhook_url`)
- `POST /api/webhook/github` – GitHub webhook (pull_request)
- `GET /api/health` – Health check
- `GET /docs` – OpenAPI docs

## Settings (frontend + API)

| Setting | Description |
|--------|-------------|
| GitHub token | Set via **Connect with GitHub** (OAuth) or paste a Personal Access Token |
| OAuth Client ID / Secret | From GitHub OAuth App; callback URL = this app’s origin + `/api/auth/github/callback` |
| Webhook secret | Optional; used when creating webhooks and validating payloads |
| AI provider | `anthropic` or `openai` |
| OpenAI / Anthropic API key | Key for the selected provider |
| Model | e.g. `claude-sonnet-4-20250514`, `gpt-4o` (defaults if empty) |
| Max batch chars | Diff batch size (default 12000) |
| Max tokens | Per AI request (default 4096) |
| Max inline comments | Cap per PR (default 20) |

## Security

- **Admin auth:** Set the environment variable `ADMIN_PASSWORD` to protect the settings UI and all control APIs (settings, repos list, webhook creation, GitHub OAuth). Without it, anyone who can reach the app can change configuration. The webhook endpoint `POST /api/webhook/github` stays public so GitHub can deliver events; protect it by setting a **webhook secret** in the app and in GitHub.
- **Session:** Signing in sets an HttpOnly, SameSite=Lax session cookie (Secure when using HTTPS or `X-Forwarded-Proto: https`). Sessions last 7 days.
- **Deploying publicly:** Always set `ADMIN_PASSWORD` (and use HTTPS). Optionally set `SECURE_COOKIE=1` if your proxy does not send `X-Forwarded-Proto`.

## Run without Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 and set the webhook URL in GitHub to your public URL (e.g. ngrok) + `/api/webhook/github`.
