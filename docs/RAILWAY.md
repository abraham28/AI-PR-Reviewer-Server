# Deploy AI PR Reviewer on Railway

This guide walks you through pushing the app to GitHub and deploying it on [Railway](https://railway.app) so you get a public URL for the settings UI and the GitHub webhook.

**You do not need Postgres.** This app stores settings in a JSON file. Railway gives you a **Volume** to persist that file across deploys. Use Postgres only if you later change the app to use a database.

---

## 1. Push the app to GitHub

If the project is not yet in a Git repo:

```bash
cd pr-reviewer
git init
git add .
git commit -m "Initial commit: AI PR Reviewer"
```

Create a new repository on GitHub (e.g. [github.com/new](https://github.com/new)), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/pr-reviewer.git
git branch -M main
git push -u origin main
```

If the project is already in a repo, just ensure your latest changes are pushed:

```bash
git add .
git commit -m "Your message"
git push
```

---

## 2. Create a Railway project and connect GitHub

1. Go to [railway.app](https://railway.app) and sign in (e.g. with GitHub).
2. Click **New Project**.
3. Choose **Deploy from GitHub repo**.
4. Select the **pr-reviewer** repository (and the correct branch, e.g. `main`).
5. Railway will detect the **Dockerfile** and start a build. Wait for the first build to finish.

---

## 3. Configure the service

1. Click the service (your app).
2. Open the **Settings** tab.
3. **Root Directory:** leave default (repo root).
4. **Build:** Railway should use the Dockerfile automatically. No extra build command needed.
5. **Start Command:** leave default (uses `CMD` from the Dockerfile).
6. **Watch Paths:** optional; leave default if you want Railway to redeploy on every push.

---

## 4. Add a Volume (so settings persist)

Without a volume, settings are lost on every redeploy because the filesystem is ephemeral.

1. In your project, click **+ New** and choose **Volume**.
2. Name it e.g. `pr-reviewer-data`.
3. Attach the volume to your **app service**: in the volume’s settings, set the service, or in the service settings, add the volume and set the **mount path**.
4. Set the volume **mount path** to:
   ```text
   /app/backend/data
   ```
   This is where the app writes `settings.json`. Data in this path will persist across deploys.

---

## 5. Set environment variables

In the app service, open the **Variables** tab and add:

| Variable           | Value                    | Required |
|--------------------|--------------------------|----------|
| `ADMIN_PASSWORD`   | A strong password you’ll use to sign in to the UI | **Yes** (for public URL) |
| `PORT`             | Leave unset; Railway sets it automatically.      | No       |

Optional (only if you need them):

- `SECURE_COOKIE=1` – set if your app is behind HTTPS and cookies are not marked Secure (e.g. proxy not sending `X-Forwarded-Proto`).

Do **not** put GitHub tokens or API keys here; set those in the app’s **Settings** UI after deployment (they are stored in the volume).

---

## 6. Get your public URL

1. In the app service, open the **Settings** tab.
2. Under **Networking**, click **Generate Domain** (or use an existing one).
3. You’ll get a URL like `https://pr-reviewer-production-xxxx.up.railway.app`.

---

## 7. Use the app

1. Open the generated URL in your browser.
2. Sign in with the **ADMIN_PASSWORD** you set in Variables.
3. In the UI, configure:
   - **GitHub** (OAuth or token)
   - **Webhook secret** (recommended)
   - **AI provider** and API keys
4. For **GitHub OAuth**, in [GitHub → Developer settings → OAuth Apps](https://github.com/settings/developers), set the callback URL to:
   ```text
   https://YOUR-RAILWAY-URL/api/auth/github/callback
   ```
5. In **Add webhook to a repo**, use your Railway URL as the base (or leave Webhook URL empty to use the current origin). Create the webhook from the UI or add it manually in the repo with:
   - **Payload URL:** `https://YOUR-RAILWAY-URL/api/webhook/github`
   - **Content type:** `application/json`
   - **Events:** Pull requests
   - **Secret:** same as in the app

---

## Do I need Postgres?

**No.** This app does not use a database. It stores:

- Settings (tokens, API keys, etc.) in **`/app/backend/data/settings.json`**.

That path is persisted by the **Railway Volume** you mounted in step 4. Postgres is only needed if you later change the app to use a database (e.g. for multiple users or different persistence).

---

## Troubleshooting

- **502 Bad Gateway:** The app must listen on the port Railway provides. The Dockerfile already uses `PORT` (or 8000). Ensure no other `PORT` or start command overrides it.
- **Settings disappear after deploy:** Confirm the volume is attached to the app service and the mount path is exactly `/app/backend/data`.
- **Webhook not receiving events:** In GitHub, check the webhook URL and that the repo can reach your Railway URL. Set a webhook secret in both GitHub and the app.
- **Can’t sign in:** Ensure `ADMIN_PASSWORD` is set in the service Variables and you’re using the same value in the UI.
