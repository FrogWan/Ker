from __future__ import annotations

import logging

from ker.tools.tool_base import ToolContext, safe_path

logger = logging.getLogger(__name__)

# Directories in the workspace root that are part of the project source.
# Files written inside these are never redirected.
_PROJECT_DIRS = {"src", "tests", "docs", ".ker", ".github", ".vscode", "screenshots"}

# Script/code extensions that should be redirected when written to the project root.
_SCRIPT_EXTENSIONS = {
    ".py", ".js", ".ts", ".sh", ".bash", ".ps1", ".rb", ".pl", ".php",
    ".java", ".go", ".rs", ".c", ".cpp", ".cs", ".swift", ".kt",
}


def _is_scratch_file(workspace: "Path", resolved: "Path") -> bool:
    """Return True if the file looks like a scratch script written to the project root."""
    try:
        rel = resolved.relative_to(workspace.resolve())
    except ValueError:
        return False
    parts = rel.parts
    if not parts:
        return False
    # If the file lives inside a known project directory, it's fine.
    if parts[0].lower() in {d.lower() for d in _PROJECT_DIRS}:
        return False
    # Only redirect script/code files at the workspace root level.
    if len(parts) == 1 and resolved.suffix.lower() in _SCRIPT_EXTENSIONS:
        return True
    return False


def _redirect_to_tmp_code(ctx: ToolContext, path: str) -> tuple["Path", str]:
    """Redirect a scratch file path to .ker/tmp_code/ and return (new_resolved, new_display_path)."""
    # Normalise to forward slashes for consistent handling
    normalised = path.replace("\\", "/")
    # Strip leading slashes/dots to get a clean relative path
    clean = normalised.lstrip("./")
    new_rel = f".ker/tmp_code/{clean}"
    new_resolved = safe_path(ctx.workspace, new_rel)
    return new_resolved, new_rel


def read_file(ctx: ToolContext, path: str) -> str:
    p = safe_path(ctx.workspace, path)
    if not p.exists():
        return f"Error: File not found: {path}"
    if not p.is_file():
        return f"Error: Not a file: {path}"
    return p.read_text(encoding="utf-8")


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    p = safe_path(ctx.workspace, path)
    if _is_scratch_file(ctx.workspace, p):
        p, display_path = _redirect_to_tmp_code(ctx, path)
        logger.info("Redirected scratch file %s -> %s", path, display_path)
    else:
        display_path = path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {display_path}"


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
