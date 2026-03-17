"""Diff batching and AI review pipeline (adapted from GitHub Actions workflow)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

# Batch building (pure functions)


def split_file_sections(diff_text: str) -> tuple[str, list[str]]:
    prefix_lines: list[str] = []
    sections: list[str] = []
    current_section: list[str] = []

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_section:
                sections.append("".join(current_section))
            current_section = [line]
        elif current_section:
            current_section.append(line)
        else:
            prefix_lines.append(line)

    if current_section:
        sections.append("".join(current_section))

    return "".join(prefix_lines), sections


def extract_file_path(section_text: str) -> str:
    for line in section_text.splitlines():
        if line.startswith("+++ b/"):
            return line[6:]

    lines = section_text.splitlines()
    if lines and lines[0].startswith("diff --git "):
        parts = lines[0].split()
        if len(parts) >= 4 and parts[3].startswith("b/"):
            return parts[3][2:]

    return "unknown"


def split_hunks(section_text: str) -> tuple[str, list[str]]:
    header_lines: list[str] = []
    hunks: list[str] = []
    current_hunk: list[str] = []
    in_hunk = False

    for line in section_text.splitlines(keepends=True):
        if line.startswith("@@ "):
            if current_hunk:
                hunks.append("".join(current_hunk))
            current_hunk = [line]
            in_hunk = True
        elif in_hunk:
            current_hunk.append(line)
        else:
            header_lines.append(line)

    if current_hunk:
        hunks.append("".join(current_hunk))

    return "".join(header_lines), hunks


def split_large_hunk(
    file_header: str, hunk_text: str, max_segment_chars: int
) -> list[str]:
    hunk_lines = hunk_text.splitlines(keepends=True)
    if not hunk_lines:
        return []

    hunk_header = hunk_lines[0]
    body_lines = hunk_lines[1:]
    current = [file_header, hunk_header]
    current_len = len(file_header) + len(hunk_header)
    segments: list[str] = []

    for line in body_lines:
        if current_len + len(line) > max_segment_chars and len(current) > 2:
            segments.append("".join(current))
            current = [file_header, hunk_header, line]
            current_len = len(file_header) + len(hunk_header) + len(line)
        else:
            current.append(line)
            current_len += len(line)

    segments.append("".join(current))
    return segments


def build_segments(
    section_text: str, max_batch_chars: int
) -> list[dict[str, str]]:
    file_path = extract_file_path(section_text)
    file_header, hunks = split_hunks(section_text)

    if not hunks:
        return [{"file": file_path, "text": section_text}]

    segments: list[dict[str, str]] = []
    max_segment_chars = max(max_batch_chars, len(file_header) + 64)

    for hunk in hunks:
        candidate = file_header + hunk
        if len(candidate) <= max_batch_chars:
            segments.append({"file": file_path, "text": candidate})
            continue

        for segment in split_large_hunk(file_header, hunk, max_segment_chars):
            segments.append({"file": file_path, "text": segment})

    return segments


def pack_batches(
    segments: list[dict[str, str]], max_batch_chars: int
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_files: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current_parts, current_files, current_len
        if not current_parts:
            return
        batches.append(
            {
                "files": current_files[:],
                "diff": "".join(current_parts).rstrip() + "\n",
            }
        )
        current_parts = []
        current_files = []
        current_len = 0

    for segment in segments:
        text = segment["text"]
        file_path = segment["file"]

        if current_parts and current_len + len(text) > max_batch_chars:
            flush()

        if not current_parts and len(text) > max_batch_chars:
            current_parts.append(text)
            current_len += len(text)
            if file_path not in current_files:
                current_files.append(file_path)
            flush()
            continue

        current_parts.append(text)
        current_len += len(text)
        if file_path not in current_files:
            current_files.append(file_path)

    flush()
    return batches


def build_review_batches(
    full_diff: str, max_batch_chars: int = 12000
) -> tuple[list[dict[str, Any]], str, str]:
    """Returns (batches, review_scope, batch_warning)."""
    if not full_diff.strip():
        batches = [
            {"index": 1, "files": [], "diff": "(no diff)\n"},
        ]
        scope = "No diff to review."
        warning = ""
        return batches, scope, warning

    prefix, sections = split_file_sections(full_diff)
    segments: list[dict[str, str]] = []

    if prefix.strip():
        segments.append({"file": "diff-metadata", "text": prefix})

    for section in sections:
        segments.extend(build_segments(section, max_batch_chars))

    if not segments:
        batches = [
            {"index": 1, "files": [], "diff": full_diff.rstrip() + "\n"},
        ]
    else:
        batches = pack_batches(segments, max_batch_chars)
        for index, batch in enumerate(batches, start=1):
            batch["index"] = index

    scope = (
        f"Reviewed the full PR diff in {len(batches)} batch(es) "
        f"with a max batch size of {max_batch_chars} characters."
    )
    oversized = [
        b["index"]
        for b in batches
        if len(b.get("diff", "")) > max_batch_chars
    ]
    warning = ""
    if oversized:
        warning = (
            "Some individual diff batches exceeded the target batch size. "
            f"Oversized batch indices: {', '.join(str(i) for i in oversized)}."
        )
    return batches, scope, warning


# --- JSON extraction ---


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    fence_match = re.search(
        r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE
    )
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def extract_review_json(text: str) -> dict[str, Any] | None:
    stripped = strip_code_fences(text)
    if not stripped:
        return None

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    decoder = json.JSONDecoder()
    for start in range(len(stripped)):
        if stripped[start] != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate

    return None


def dedupe_comments(
    comments: list[dict[str, Any]], limit: int = 20
) -> list[dict[str, Any]]:
    seen: set[tuple[str, int, str]] = set()
    unique: list[dict[str, Any]] = []
    for comment in comments:
        key = (
            comment.get("file", ""),
            int(comment.get("line", 0)),
            comment.get("comment", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(comment)
        if len(unique) >= limit:
            break
    return unique


def filter_comments_to_changed_lines(
    diff_text: str, comments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep only comments whose (file, line) appear as added lines in the diff."""
    valid_lines: dict[str, set[int]] = {}
    current_file: str | None = None
    current_line: int | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            current_line = None
            continue

        if line.startswith("@@"):
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match:
                current_line = int(match.group(1))
            continue

        if current_file is None or current_line is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            valid_lines.setdefault(current_file, set()).add(current_line)
            current_line += 1
        elif line.startswith(" "):
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue

    filtered = []
    for comment in comments:
        file_path = comment.get("file", "")
        line = int(comment.get("line", 0))
        if line in valid_lines.get(file_path, set()):
            filtered.append(comment)
    return filtered


# --- Prompt builders ---


def batch_prompt(batch: dict[str, Any], batch_count: int) -> str:
    import textwrap
    files = ", ".join(batch.get("files", [])) or "unknown files"
    return textwrap.dedent(
        f"""\
        Review batch {batch["index"]}/{batch_count} of a pull request diff.

        This is only part of the full diff, so only report issues clearly supported by this batch.
        Prioritize high-confidence bugs, regressions, correctness issues, concrete security problems, and missing tests.
        Do not speculate about files or code that are not shown.
        Do not question intended logic, architecture, naming, or design choices unless the diff itself shows a likely defect.
        Do not give planning advice, refactoring suggestions, or "consider changing" feedback.
        If behavior could plausibly be intentional and the diff does not clearly show a bug, do not comment on it.

        Respond with valid JSON only, without markdown fences, in this exact shape:
        {{
          "batch_summary": "fact-based summary of the specific code changes in this batch",
          "patch": "unified git patch limited to this batch or empty string",
          "inline_comments": [
            {{
              "file": "path/to/file.go",
              "line": 12,
              "comment": "message"
            }}
          ]
        }}

        Rules:
        - Use file paths exactly as they appear in the diff.
        - Use only changed head-side line numbers shown in this batch.
        - Return at most 5 inline comments.
        - Return an empty string for patch if there is no safe patch for this batch.
        - Return an empty array for inline_comments if there are no review comments.

        Files in this batch: {files}

        Diff batch:
        {batch["diff"]}
        """
    )


SYSTEM_PROMPT = (
    "You are a senior software engineer reviewing a pull request. "
    "Only report high-confidence bugs and regressions that are directly supported by the diff. "
    "Do not produce style feedback, planning advice, or speculative critiques of intended logic. "
    "Respond with valid JSON only and do not use markdown fences."
)


def run_review_pipeline(
    full_diff: str,
    call_ai: Callable[[str, str], str],
    max_batch_chars: int = 12000,
    max_inline_comments: int = 20,
) -> tuple[str, list[dict[str, Any]], str, str, list[str], str]:
    """
    Run batched AI review on full_diff using call_ai(user_message, system_prompt) -> raw response text.
    Returns (summary, inline_comments, review_scope, batch_warning, review_warnings, selected_model).
    """
    batches, review_scope, batch_warning = build_review_batches(
        full_diff, max_batch_chars
    )
    total_batches = len(batches)
    batch_reviews: list[dict[str, Any]] = []
    review_warnings: list[str] = []
    collected_comments: list[dict[str, Any]] = []
    selected_model = ""

    for batch in batches:
        prompt = batch_prompt(batch, total_batches)
        raw = call_ai(prompt, SYSTEM_PROMPT)
        # call_ai may return (body, model) or just body
        if isinstance(raw, tuple):
            raw_body, selected_model = raw[0], raw[1] or selected_model
        else:
            raw_body = raw

        normalized = _normalize_batch_review(batch, raw_body)
        batch_reviews.append(normalized)

        if normalized.get("warning"):
            review_warnings.append(
                f"Batch {batch['index']}: {normalized['warning']}"
            )

        for c in normalized.get("inline_comments", []):
            collected_comments.append(c)

    # Optional: validation step could call AI again to filter comments; skip for simplicity
    aggregated = dedupe_comments(collected_comments, limit=max_inline_comments)
    aggregated = filter_comments_to_changed_lines(full_diff, aggregated)

    # Synthesize final summary
    summary = _synthesize_summary(batch_reviews)

    return (
        summary,
        aggregated,
        review_scope,
        batch_warning,
        review_warnings,
        selected_model,
    )


def _extract_text_from_response(response: dict[str, Any]) -> str:
    """Support both Anthropic (content[].text) and OpenAI (choices[].message.content) shapes."""
    if "content" in response:
        blocks = [
            block.get("text", "")
            for block in response.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(blocks)
    if "choices" in response and response["choices"]:
        msg = response["choices"][0].get("message", {})
        content = msg.get("content", "")
        return content if isinstance(content, str) else ""
    return ""


def _normalize_batch_review(
    batch: dict[str, Any], raw_body: str
) -> dict[str, Any]:
    warning = ""
    try:
        response = json.loads(raw_body)
    except json.JSONDecodeError:
        warning = "AI returned a non-JSON API response for this batch."
        return {
            "index": batch["index"],
            "files": batch.get("files", []),
            "batch_summary": f"Batch {batch['index']} could not be parsed.",
            "patch": "",
            "inline_comments": [],
            "warning": warning,
        }

    raw_review = _extract_text_from_response(response)
    parsed = extract_review_json(raw_review)

    if parsed is None:
        warning = "AI returned no structured JSON for this batch."
        return {
            "index": batch["index"],
            "files": batch.get("files", []),
            "batch_summary": f"Batch {batch['index']} completed without structured findings.",
            "patch": "",
            "inline_comments": [],
            "warning": warning,
        }

    batch_summary = str(
        parsed.get("batch_summary") or parsed.get("summary") or f"Batch {batch['index']} reviewed."
    ).strip()
    patch = str(parsed.get("patch", "")).strip() or ""

    inline_comments = []
    for item in parsed.get("inline_comments", []):
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file", "")).strip()
        comment = str(item.get("comment", "")).strip()
        try:
            line = int(item.get("line", 0))
        except (TypeError, ValueError):
            continue
        if file_path and comment and line > 0:
            inline_comments.append({"file": file_path, "line": line, "comment": comment})

    return {
        "index": batch["index"],
        "files": batch.get("files", []),
        "batch_summary": batch_summary,
        "patch": patch,
        "inline_comments": inline_comments,
        "warning": warning,
    }


def _synthesize_summary(batch_reviews: list[dict[str, Any]]) -> str:
    """Build final summary from batch reviews."""
    summaries = [
        str(r.get("batch_summary", "")).strip()
        for r in batch_reviews
        if r.get("batch_summary")
    ]
    if not summaries:
        return "AI review completed, but no notable findings were produced."
    if len(summaries) == 1:
        return summaries[0]

    # Simple concatenation without extra AI call to avoid token use and complexity
    combined = "Combined batched AI review:\n" + "\n".join(
        f"- {s}" for s in summaries[:8]
    )
    return combined
