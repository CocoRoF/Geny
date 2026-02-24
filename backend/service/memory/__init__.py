"""
Memory subsystem for Claude Control.

Provides long-term and short-term memory backed by files inside the
session's storage directory, inspired by OpenClaw's MEMORY.md +
session JSONL patterns.

Public API:
    SessionMemoryManager   — per-session facade
    LongTermMemory         — MEMORY.md file I/O
    ShortTermMemory        — JSONL transcript I/O
    MemorySearchResult     — search hit dataclass
"""

from service.memory.manager import SessionMemoryManager
from service.memory.long_term import LongTermMemory
from service.memory.short_term import ShortTermMemory
from service.memory.types import MemoryEntry, MemorySearchResult

__all__ = [
    "SessionMemoryManager",
    "LongTermMemory",
    "ShortTermMemory",
    "MemoryEntry",
    "MemorySearchResult",
]
