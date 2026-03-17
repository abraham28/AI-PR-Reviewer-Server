(function () {
  const API = "/api";
  const $ = (id) => document.getElementById(id);

  function setStatus(msg, type) {
    const el = $("status");
    el.textContent = msg;
    el.className = "status " + (type || "");
  }

  function setWebhookUrl() {
    const el = $("webhook_url");
    if (el) el.textContent = window.location.origin + "/api/webhook/github";
  }

  function toggleProvider() {
    const p = $("ai_provider").value;
    document.body.setAttribute("data-provider", p);
  }

  async function load() {
    try {
      const r = await fetch(API + "/settings");
      if (!r.ok) throw new Error(r.statusText);
      const s = await r.json();
      $("github_token").value = s.github_token || "";
      $("webhook_secret").value = s.webhook_secret || "";
      $("ai_provider").value = s.ai_provider || "anthropic";
      $("openai_api_key").value = s.openai_api_key || "";
      $("anthropic_api_key").value = s.anthropic_api_key || "";
      $("model").value = s.model || "";
      $("max_batch_chars").value = s.max_batch_chars ?? 12000;
      $("max_tokens").value = s.max_tokens ?? 4096;
      $("max_inline_comments").value = s.max_inline_comments ?? 20;
      toggleProvider();
    } catch (e) {
      setStatus("Failed to load settings: " + e.message, "error");
    }
  }

  async function save() {
    const btn = $("save_btn");
    btn.disabled = true;
    setStatus("Saving…");
    try {
      const r = await fetch(API + "/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          github_token: $("github_token").value.trim() || undefined,
          webhook_secret: $("webhook_secret").value.trim() || undefined,
          ai_provider: $("ai_provider").value || undefined,
          openai_api_key: $("openai_api_key").value.trim() || undefined,
          anthropic_api_key: $("anthropic_api_key").value.trim() || undefined,
          model: $("model").value.trim() || undefined,
          max_batch_chars: parseInt($("max_batch_chars").value, 10) || undefined,
          max_tokens: parseInt($("max_tokens").value, 10) || undefined,
          max_inline_comments: parseInt($("max_inline_comments").value, 10) || undefined,
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
      btn.disabled = false;
    }
  }

  $("ai_provider").addEventListener("change", toggleProvider);
  $("save_btn").addEventListener("click", save);
  setWebhookUrl();
  load();
})();
