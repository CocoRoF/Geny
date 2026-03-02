"""
Memory subsystem for Geny Agent.

Provides long-term and short-term memory backed by files inside the
session's storage directory, inspired by OpenClaw's MEMORY.md +
session JSONL patterns.

Includes an optional FAISS-backed vector memory layer for semantic
search (see ``VectorMemoryManager``).

Public API:
    SessionMemoryManager   — per-session facade
    LongTermMemory         — MEMORY.md file I/O
    ShortTermMemory        — JSONL transcript I/O
    VectorMemoryManager    — FAISS vector indexing & retrieval
    MemorySearchResult     — search hit dataclass
"""

from service.memory.manager import SessionMemoryManager
from service.memory.long_term import LongTermMemory
from service.memory.short_term import ShortTermMemory
from service.memory.vector_memory import VectorMemoryManager
from service.memory.types import MemoryEntry, MemorySearchResult

__all__ = [
    "SessionMemoryManager",
    "LongTermMemory",
    "ShortTermMemory",
    "VectorMemoryManager",
    "MemoryEntry",
    "MemorySearchResult",
]
