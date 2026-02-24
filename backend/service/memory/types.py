"""
Shared data types for the memory subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MemorySource(str, Enum):
    """Where a memory entry originated."""
    LONG_TERM = "long_term"       # MEMORY.md / memory/*.md files
    SHORT_TERM = "short_term"     # JSONL transcript entries
    BOOTSTRAP = "bootstrap"       # Project context files (AGENTS.md, etc.)


@dataclass
class MemoryEntry:
    """A single piece of stored memory.

    Both long-term (markdown heading sections) and short-term
    (transcript turns) are normalized into this structure.
    """
    source: MemorySource
    content: str
    timestamp: Optional[datetime] = None
    filename: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def token_estimate(self) -> int:
        """Rough token estimate (3 chars ≈ 1 token for mixed en/ko)."""
        return max(1, len(self.content) // 3)


@dataclass
class MemorySearchResult:
    """A search hit with relevance score."""
    entry: MemoryEntry
    score: float = 0.0
    snippet: str = ""
    match_type: str = "keyword"  # "keyword" | "recency" | "combined"

    @property
    def source(self) -> MemorySource:
        return self.entry.source

    @property
    def content(self) -> str:
        return self.entry.content


@dataclass
class MemoryStats:
    """Aggregate statistics about the memory store."""
    long_term_entries: int = 0
    short_term_entries: int = 0
    long_term_chars: int = 0
    short_term_chars: int = 0
    total_files: int = 0
    last_write: Optional[datetime] = None
