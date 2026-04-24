"""Single-source formatter for tool-invocation summaries.

Both :mod:`service.logging.session_logger` and the legacy
``service.claude_manager.process_manager`` (removed in cycle
20260424_2 PR-4) historically carried a near-identical
``_format_tool_detail`` method, each with its own
``except Exception: return "(parse error)"`` swallower. Phase D of the
20260420_2 cycle (see ``dev_docs/20260420_2/plan/04_observability_and_error_surface.md``
§B) collapses them onto this module and removes the swallower.

Failure policy:
    - **Per-field** failures (e.g. a value that cannot be ``str()``-ed)
      surface as ``<unrepresentable: ExcType>`` rather than crashing
      the whole formatter.
    - **Top-level** failures log an ``exception`` and return a
      truncated ``repr(tool_input)`` (≤ 200 chars). The function
      *never* returns an empty string or the legacy
      ``"(parse error)"`` placeholder — log/UI consumers can rely on
      a non-empty, somewhat informative result.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Mapping, Optional

logger = getLogger(__name__)

_REPR_FALLBACK_LIMIT = 200
_MCP_KEY_ORDER = (
    "query",
    "path",
    "file_path",
    "command",
    "url",
    "content",
    "message",
    "prompt",
)


def _safe_str(value: Any) -> str:
    """Best-effort ``str(value).strip().replace("\\n", " ")`` that never
    raises. Per-field failures become an ``<unrepresentable: ...>``
    placeholder instead of bubbling up to the top-level handler."""
    try:
        return str(value).strip().replace("\n", " ")
    except Exception as exc:  # noqa: BLE001 — we deliberately swallow per-field
        return f"<unrepresentable: {type(exc).__name__}>"


def _truncate(text: str, limit: int, suffix: str = "...") -> str:
    """Trim *text* to *limit* characters, appending *suffix* on overflow."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}{suffix}"


def _basename(path: str) -> str:
    """Cross-platform basename, tolerant of mixed separators."""
    return path.replace("\\", "/").split("/")[-1]


def format_tool_detail(
    tool_name: str, tool_input: Optional[Mapping[str, Any]]
) -> str:
    """Render a concise, human-friendly summary of a tool invocation.

    Args:
        tool_name: The tool's identifier (case-insensitive comparison
            against the known patterns; ``mcp__server__tool`` style
            names are detected by the ``mcp__`` prefix or any embedded
            ``__``).
        tool_input: The tool's input dictionary. ``None`` or empty
            mapping returns ``"(no input)"``.

    Returns:
        A non-empty string suitable for log lines or chat-stream UI.
        Never returns ``""`` or ``"(parse error)"``.
    """
    if not tool_input:
        return "(no input)"

    try:
        return _format_tool_detail_inner(tool_name, tool_input)
    except Exception:
        # Top-level failure: stacktrace into the log, repr fallback to
        # the caller. Keeps the formatter contract intact (always a
        # non-empty string) without hiding the underlying bug.
        logger.exception(
            "tool detail formatting crashed; tool=%s", tool_name
        )
        try:
            fallback = repr(tool_input)
        except Exception as exc:  # noqa: BLE001 — repr() can blow up too
            return f"<unrepresentable input: {type(exc).__name__}>"
        return _truncate(fallback, _REPR_FALLBACK_LIMIT)


def _format_tool_detail_inner(
    tool_name: str, tool_input: Mapping[str, Any]
) -> str:
    """Pattern-match implementation. Kept separate from
    :func:`format_tool_detail` so the top-level guard is the only
    thing the public function does on the happy path."""
    name_lower = tool_name.lower()

    # Bash / shell commands.
    if name_lower in ("bash", "shell", "execute"):
        command = _safe_str(
            tool_input.get("command", tool_input.get("cmd", ""))
        )
        if command:
            return f"`{_truncate(command, 100)}`"

    # Read-style file operations.
    elif name_lower in ("read", "readfile", "read_file", "view"):
        file_path = _safe_str(
            tool_input.get(
                "file_path",
                tool_input.get("path", tool_input.get("file", "")),
            )
        )
        start_line = _safe_str(
            tool_input.get("start_line", tool_input.get("offset", ""))
        )
        end_line = _safe_str(
            tool_input.get("end_line", tool_input.get("limit", ""))
        )
        if file_path:
            filename = _basename(file_path)
            if start_line and end_line:
                return f"{filename} (L{start_line}-{end_line})"
            if start_line:
                return f"{filename} (from L{start_line})"
            return filename

    # Write/edit-style file operations.
    elif name_lower in ("write", "writefile", "write_file", "edit", "edit_file"):
        file_path = _safe_str(
            tool_input.get(
                "file_path",
                tool_input.get("path", tool_input.get("file", "")),
            )
        )
        raw_content = tool_input.get("content", tool_input.get("text", ""))
        if file_path:
            filename = _basename(file_path)
            content = _safe_str(raw_content)
            if content:
                lines = content.count("\n") + 1
                chars = len(content)
                return f"{filename} (+{lines} lines, {chars} chars)"
            return filename

    # Glob / list operations.
    elif name_lower in ("glob", "search", "find", "list", "ls", "listdir"):
        pattern = _safe_str(
            tool_input.get(
                "pattern",
                tool_input.get("query", tool_input.get("path", "")),
            )
        )
        if pattern:
            return f"`{_truncate(pattern, 60)}`"

    # Grep operations.
    elif name_lower in ("grep", "ripgrep", "rg"):
        pattern = _safe_str(
            tool_input.get(
                "pattern",
                tool_input.get("query", tool_input.get("regex", "")),
            )
        )
        path = _safe_str(
            tool_input.get("path", tool_input.get("directory", ""))
        )
        if pattern:
            pat = f"`{_truncate(pattern, 40, suffix='')}`"
            if path:
                return f"{pat} in {_basename(path)}"
            return pat

    # Web fetch.
    elif name_lower in ("fetch", "web", "http", "curl"):
        url = _safe_str(tool_input.get("url", tool_input.get("uri", "")))
        if url:
            return _truncate(url, 60)

    # MCP tool calls — ``mcp__server__tool`` and similar ``a__b`` names.
    elif tool_name.startswith("mcp__") or "__" in tool_name:
        for key in _MCP_KEY_ORDER:
            if key in tool_input:
                value = _safe_str(tool_input[key])
                return f"{key}=`{_truncate(value, 80)}`"

    # Default: first non-private parameter.
    for key, value in tool_input.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        value_str = _safe_str(value)
        return f"{key}=`{_truncate(value_str, 80)}`"

    return "(empty input)"
