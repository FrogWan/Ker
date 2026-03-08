from __future__ import annotations

from ker.tools.tool_base import ToolContext, safe_path


def read_file(ctx: ToolContext, path: str) -> str:
    p = safe_path(ctx.workspace, path)
    if not p.exists():
        return f"Error: File not found: {path}"
    if not p.is_file():
        return f"Error: Not a file: {path}"
    return p.read_text(encoding="utf-8")


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    p = safe_path(ctx.workspace, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}"


def edit_file(ctx: ToolContext, path: str, old_text: str, new_text: str) -> str:
    p = safe_path(ctx.workspace, path)
    if not p.exists():
        return f"Error: File not found: {path}"
    text = p.read_text(encoding="utf-8")
    if old_text not in text:
        return _not_found_message(path, old_text, text)
    count = text.count(old_text)
    if count > 1:
        return f"Warning: old_text appears {count} times. Provide more context for unique replacement."
    updated = text.replace(old_text, new_text, 1)
    p.write_text(updated, encoding="utf-8")
    return f"Edited {path}"


def list_dir(ctx: ToolContext, path: str) -> str:
    p = safe_path(ctx.workspace, path)
    if not p.exists():
        return f"Error: Directory not found: {path}"
    if not p.is_dir():
        return f"Error: Not a directory: {path}"
    items = []
    for item in sorted(p.iterdir(), key=lambda x: x.name.lower()):
        prefix = "[D]" if item.is_dir() else "[F]"
        items.append(f"{prefix} {item.name}")
    return "\n".join(items) if items else f"Directory {path} is empty"


def _not_found_message(path: str, old_text: str, content: str) -> str:
    import difflib

    lines = content.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    window = max(1, len(old_lines))
    best_ratio = 0.0
    best_start = 0
    for i in range(max(1, len(lines) - window + 1)):
        ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i
    if best_ratio > 0.5:
        diff = "\n".join(
            difflib.unified_diff(
                old_lines,
                lines[best_start : best_start + window],
                fromfile="old_text (provided)",
                tofile=f"{path} (actual, line {best_start + 1})",
                lineterm="",
            )
        )
        return f"Error: old_text not found in {path}. Best match at line {best_start + 1} ({best_ratio:.0%} similar):\n{diff}"
    return f"Error: old_text not found in {path}."
