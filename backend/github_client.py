"""GitHub API: fetch PR diff and post review (summary + inline comments)."""
from __future__ import annotations

import httpx
from github import Github


def get_pr_diff(github_token: str, owner: str, repo: str, pull_number: int) -> str:
    """Fetch PR diff via GitHub API (Accept: application/vnd.github.v3.diff)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(
            url,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3.diff",
            },
        )
        resp.raise_for_status()
        return resp.text or ""


def post_review(
    github_token: str,
    owner: str,
    repo: str,
    pull_number: int,
    commit_id: str,
    summary: str,
    inline_comments: list[dict],
    review_scope: str = "",
    model_used: str = "",
    batch_warning: str = "",
    review_warnings: list[str] | None = None,
) -> None:
    """Post PR summary as issue comment and inline comments as pull request review."""
    g = Github(github_token)
    repo_obj = g.get_repo(f"{owner}/{repo}")
    pr = repo_obj.get_pull(pull_number)
    issue = pr.as_issue()

    # 1) Post summary as issue comment
    detail_lines = []
    if model_used:
        detail_lines.append(f"Model: `{model_used}`")
    if review_scope:
        detail_lines.append(review_scope)
    if batch_warning:
        detail_lines.append(f"Batching: {batch_warning}")
    for w in review_warnings or []:
        detail_lines.append(f"AI output: {w}")
    detail_block = "\n".join(f"- {line}" for line in detail_lines) + "\n\n" if detail_lines else ""

    body = "## 🤖 AI Review Summary\n\n" + detail_block + (summary or "No summary generated.")
    issue.create_comment(body)

    # 2) Post inline comments (one API call per comment for compatibility)
    if inline_comments:
        MAX_BODY = 60000
        for c in inline_comments:
            path = str(c.get("file") or "").strip()
            line = int(c.get("line") or 0)
            body_text = (str(c.get("comment") or "").replace("\r\n", "\n").strip())[:MAX_BODY]
            if path and line > 0 and body_text:
                try:
                    pr.create_review_comment(body_text, commit_id, path, line, side="RIGHT")
                except Exception:
                    pass
