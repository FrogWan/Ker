from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import urlparse

import httpx

from ker.tools.tool_base import ToolContext

USER_AGENT = "Mozilla/5.0"


def web_search(ctx: ToolContext, query: str, count: int = 5) -> str:
    api_key = os.getenv("BRAVE_API_KEY", "")
    if not api_key:
        return "Error: Brave Search API key not configured. Set BRAVE_API_KEY."
    n = min(max(count, 1), 10)
    try:
        r = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": n},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            timeout=10.0,
        )
        r.raise_for_status()
        results = r.json().get("web", {}).get("results", [])[:n]
        if not results:
            return f"No results for: {query}"
        lines = [f"Results for: {query}\n"]
        for i, item in enumerate(results, 1):
            lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
            if item.get("description"):
                lines.append(f"   {item['description']}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


def web_fetch(ctx: ToolContext, url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str:
    valid, err = _validate_url(url)
    if not valid:
        return json.dumps({"error": f"URL validation failed: {err}", "url": url}, ensure_ascii=False)
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30.0)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            text = json.dumps(r.json(), indent=2, ensure_ascii=False)
            extractor = "json"
        elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
            html_text = r.text
            content = _to_markdown(html_text) if extractMode == "markdown" else _strip_tags(html_text)
            text = content
            extractor = "html"
        else:
            text = r.text
            extractor = "raw"

        truncated = len(text) > maxChars
        if truncated:
            text = text[:maxChars]
        return json.dumps(
            {"url": url, "finalUrl": str(r.url), "status": r.status_code, "extractor": extractor, "truncated": truncated, "length": len(text), "text": text},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "url": url}, ensure_ascii=False)


def _validate_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{parsed.scheme or 'none'}'"
        if not parsed.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _strip_tags(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _to_markdown(html_text: str) -> str:
    text = re.sub(
        r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
        lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
        html_text,
        flags=re.I,
    )
    text = re.sub(r"<h([1-6])[^>]*>([\s\S]*?)</h\1>", lambda m: f"\n{'#' * int(m[1])} {_strip_tags(m[2])}\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>([\s\S]*?)</li>", lambda m: f"\n- {_strip_tags(m[1])}", text, flags=re.I)
    text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
    return _normalize(_strip_tags(text))
