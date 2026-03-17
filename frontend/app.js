(function () {
  const API = "/api";
  const $ = (id) => document.getElementById(id);

  function setStatus(msg, type) {
    const el = $("status");
    if (el) {
      el.textContent = msg;
      el.className = "status " + (type || "");
    }
  }

  function setWebhookStatus(msg, type) {
    const el = $("webhook_status");
    if (el) {
      el.textContent = msg;
      el.className = "status " + (type || "");
    }
  }

  function showToast(msg, kind) {
    const el = $("github_toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "toast " + (kind || "info");
    el.hidden = false;
    setTimeout(() => { el.hidden = true; }, 5000);
  }

  function setWebhookUrl() {
    const base = window.location.origin + "/api/webhook/github";
    const el = $("webhook_url");
    if (el) el.textContent = base;
    const sample = $("oauth_callback_sample");
    if (sample) sample.textContent = window.location.origin + "/api/auth/github/callback";
    const input = $("webhook_url_input");
    if (input && !input.value) input.placeholder = base;
  }

  function toggleProvider() {
    const p = $("ai_provider");
    if (p) document.body.setAttribute("data-provider", p.value);
  }

  function updateGitHubStatus(settings) {
    const status = $("github_status");
    if (!status) return;
    const token = settings.github_token;
    status.textContent = (token && String(token).length > 0) ? "Connected" : "";
  }

  async function load() {
    try {
      const r = await fetch(API + "/settings");
      if (!r.ok) throw new Error(r.statusText);
      const s = await r.json();
      const set = (id, val) => { const e = $(id); if (e) e.value = val ?? ""; };
      set("github_token", s.github_token || "");
      set("github_oauth_client_id", s.github_oauth_client_id || "");
      set("github_oauth_client_secret", s.github_oauth_client_secret || "");
      set("webhook_secret", s.webhook_secret || "");
      set("ai_provider", s.ai_provider || "anthropic");
      set("openai_api_key", s.openai_api_key || "");
      set("anthropic_api_key", s.anthropic_api_key || "");
      set("model", s.model || "");
      set("max_batch_chars", s.max_batch_chars ?? 12000);
      set("max_tokens", s.max_tokens ?? 4096);
      set("max_inline_comments", s.max_inline_comments ?? 20);
      updateGitHubStatus(s);
      toggleProvider();
      // URL feedback
      const params = new URLSearchParams(window.location.search);
      const github = params.get("github");
      if (github === "connected") {
        showToast("GitHub connected successfully.", "success");
        history.replaceState({}, "", window.location.pathname);
      } else if (github === "error") {
        showToast("GitHub connection failed. Check OAuth app callback URL and try again.", "error");
        history.replaceState({}, "", window.location.pathname);
      }
    } catch (e) {
      setStatus("Failed to load settings: " + e.message, "error");
    }
  }

  async function save() {
    const btn = $("save_btn");
    if (btn) btn.disabled = true;
    setStatus("Saving…");
    try {
      const r = await fetch(API + "/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          github_token: $("github_token")?.value.trim() || undefined,
          github_oauth_client_id: $("github_oauth_client_id")?.value.trim() || undefined,
          github_oauth_client_secret: $("github_oauth_client_secret")?.value.trim() || undefined,
          webhook_secret: $("webhook_secret")?.value.trim() || undefined,
          ai_provider: $("ai_provider")?.value || undefined,
          openai_api_key: $("openai_api_key")?.value.trim() || undefined,
          anthropic_api_key: $("anthropic_api_key")?.value.trim() || undefined,
          model: $("model")?.value.trim() || undefined,
          max_batch_chars: parseInt($("max_batch_chars")?.value, 10) || undefined,
          max_tokens: parseInt($("max_tokens")?.value, 10) || undefined,
          max_inline_comments: parseInt($("max_inline_comments")?.value, 10) || undefined,
        }),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || r.statusText);
      }
      setStatus("Saved.", "success");
    } catch (e) {
      setStatus("Error: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function connectGitHub() {
    const clientId = $("github_oauth_client_id")?.value.trim();
    const secret = $("github_oauth_client_secret")?.value.trim();
    if (!clientId) {
      showToast("Enter OAuth Client ID and Secret first, then Save. Then click Connect.", "error");
      return;
    }
    // Save so backend has client secret for callback (user may have already saved)
    fetch(API + "/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        github_oauth_client_id: clientId,
        github_oauth_client_secret: secret || undefined,
      }),
    }).then(() => {
      window.location.href = API + "/auth/github";
    }).catch(() => {
      showToast("Save OAuth settings first (Client ID and Secret), then try Connect again.", "error");
    });
  }

  async function loadRepos() {
    const select = $("webhook_repo");
    if (!select) return;
    setWebhookStatus("Loading…");
    try {
      const r = await fetch(API + "/repos");
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || r.statusText);
      }
      const data = await r.json();
      select.innerHTML = '<option value="">— Select repo —</option>';
      (data.repos || []).forEach((repo) => {
        const opt = document.createElement("option");
        opt.value = repo.full_name;
        opt.textContent = repo.full_name + (repo.private ? " (private)" : "");
        select.appendChild(opt);
      });
      setWebhookStatus("Loaded " + (data.repos || []).length + " repos.", "success");
    } catch (e) {
      setWebhookStatus(e.message || "Failed to load repos", "error");
    }
  }

  async function createWebhook() {
    const manual = $("webhook_repo_manual")?.value.trim();
    const select = $("webhook_repo");
    const repo = manual || (select && select.value);
    if (!repo || !repo.includes("/")) {
      setWebhookStatus("Select a repo or enter owner/repo", "error");
      return;
    }
    const [owner, ...rest] = repo.split("/");
    const repoName = rest.join("/");
    if (!repoName) {
      setWebhookStatus("Enter owner/repo", "error");
      return;
    }
    const webhookUrl = $("webhook_url_input")?.value.trim() || null;
    const btn = $("create_webhook_btn");
    if (btn) btn.disabled = true;
    setWebhookStatus("Creating…");
    try {
      const r = await fetch(API + "/webhooks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner, repo: repoName, webhook_url: webhookUrl || undefined }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || r.statusText);
      setWebhookStatus(data.message || "Webhook created.", "success");
    } catch (e) {
      setWebhookStatus(e.message || "Failed to create webhook", "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  $("ai_provider")?.addEventListener("change", toggleProvider);
  $("save_btn")?.addEventListener("click", save);
  $("connect_github_btn")?.addEventListener("click", connectGitHub);
  $("load_repos_btn")?.addEventListener("click", loadRepos);
  $("create_webhook_btn")?.addEventListener("click", createWebhook);
  setWebhookUrl();
  load();
})();
