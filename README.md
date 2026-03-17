# AI PR Reviewer

Webhook-based app that reviews GitHub pull requests with AI (OpenAI or Anthropic) and posts a summary plus inline comments. Run in Docker and expose with ngrok for GitHub webhooks.

## Quick start

1. **Build and run with Docker**

   ```bash
   docker compose up -d
   ```

   App: http://localhost:8000

2. **Configure in the UI**

   - Open http://localhost:8000
   - Set **GitHub Personal Access Token** (needs `repo`; for org repos often `read:org` too)
   - Set **Webhook secret** (optional; use the same value in GitHub)
   - Choose **AI Provider** (Anthropic or OpenAI) and set the matching API key
   - Optionally set **Model** (e.g. `claude-sonnet-4-20250514`, `gpt-4o`) and review limits
   - Click **Save settings**

3. **Expose with ngrok**

   ```bash
   ngrok http 8000
   ```

   Use the ngrok HTTPS URL (e.g. `https://abc123.ngrok.io`) as the base for the webhook.

4. **Add GitHub webhook**

   - Repo → **Settings → Webhooks → Add webhook**
   - **Payload URL:** `https://YOUR-NGROK-URL/api/webhook/github`
   - **Content type:** `application/json`
   - **Secret:** same as in the app (optional)
   - **Events:** **Pull requests**
   - Save

On **pull_request** (opened/synchronize), the app fetches the diff, runs batched AI review, and posts a summary comment plus inline comments on the PR.

## API

- `GET /` – Frontend (settings UI)
- `GET /api/settings` – Read settings (secrets masked)
- `POST /api/settings` – Update settings (JSON body)
- `POST /api/webhook/github` – GitHub webhook (pull_request)
- `GET /api/health` – Health check
- `GET /docs` – OpenAPI docs

## Settings (frontend + API)

| Setting | Description |
|--------|-------------|
| GitHub token | Personal Access Token for repo access and posting comments |
| Webhook secret | Optional; must match GitHub webhook secret |
| AI provider | `anthropic` or `openai` |
| OpenAI / Anthropic API key | Key for the selected provider |
| Model | e.g. `claude-sonnet-4-20250514`, `gpt-4o` (defaults if empty) |
| Max batch chars | Diff batch size (default 12000) |
| Max tokens | Per AI request (default 4096) |
| Max inline comments | Cap per PR (default 20) |

## Run without Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 and set the webhook URL in GitHub to your public URL (e.g. ngrok) + `/api/webhook/github`.
