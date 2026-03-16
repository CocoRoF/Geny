"""
Node Helpers — shared utility functions used by multiple node implementations.

Extracted to avoid duplication across node files while keeping each
node file focused on a single node class.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# Maximum number of TODO items (used by CreateTodosNode).
MAX_TODO_ITEMS = 20


def safe_format(template: str, state: Dict[str, Any]) -> str:
    """Substitute state fields into a prompt template, safely.

    Uses ``str.format(**mapping)`` with all values coerced to strings.
    Returns the raw *template* unchanged when substitution raises.
    """
    try:
        return template.format(**{
            k: (v if isinstance(v, str) else str(v) if v is not None else "")
            for k, v in state.items()
        })
    except (KeyError, IndexError):
        return template


def parse_categories(
    raw: Any,
    fallback: Optional[List[str]] = None,
) -> List[str]:
    """Parse categories from flexible user input.

    Accepts:
      - JSON array:       '["easy", "medium", "hard"]'
      - Single-quoted:    "['easy']"
      - Comma-separated:  'easy, medium, hard'
      - Single value:     'easy'
      - Python list:      ['easy', 'medium', 'hard']  (already parsed)

    Returns a list of lowercase stripped category strings,
    falling back to *fallback* when parsing yields nothing.
    """
    _fallback = fallback or ["easy", "medium", "hard"]

    if isinstance(raw, list):
        cats = [str(c).strip().lower() for c in raw if str(c).strip()]
        return cats if cats else _fallback

    if not isinstance(raw, str) or not raw.strip():
        return _fallback

    text = raw.strip()

    # Try JSON first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            cats = [str(c).strip().lower() for c in parsed if str(c).strip()]
            return cats if cats else _fallback
        if isinstance(parsed, dict):
            return _fallback  # JSON object is not a valid category list
    except (json.JSONDecodeError, TypeError):
        pass

    # Try single-quoted JSON  e.g.  ['easy', 'medium']
    if text.startswith("[") and text.endswith("]"):
        try:
            fixed = text.replace("'", '"')
            parsed = json.loads(fixed)
            if isinstance(parsed, list):
                cats = [str(c).strip().lower() for c in parsed if str(c).strip()]
                return cats if cats else _fallback
        except (json.JSONDecodeError, TypeError):
            pass

    # Comma-separated:  "easy, medium, hard"  or  "easy"
    parts = [p.strip().lower() for p in text.split(",") if p.strip()]
    return parts if parts else _fallback


def format_list_items(
    items: List[Dict[str, Any]],
    max_chars: int,
) -> str:
    """Format a list of items (e.g. todos) into readable markdown."""
    text = ""
    for item in items:
        status = item.get("status", "pending")
        result = item.get("result", "No result")
        if result and len(result) > max_chars:
            result = result[:max_chars] + "... (truncated)"
        text += f"\n### {item.get('title', 'Item')} [{status}]\n{result}\n"
    return text
