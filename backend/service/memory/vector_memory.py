"""
Vector Memory Manager — orchestrates FAISS indexing & retrieval.

Sits between the ``SessionMemoryManager`` and the low-level
:class:`SessionVectorStore`, providing:

1. **Automatic indexing** — scans ``memory/*.md`` files, chunks them,
   embeds via the configured provider, and upserts into FAISS.
2. **Semantic search** — given a query string, embeds it and runs
   a similarity search against the session's vector DB.
3. **Lifecycle** — initialises, persists, and tears down cleanly.

Configuration is read from :class:`LTMConfig` at init time so
it can be toggled without a server restart (config reload).

Usage::

    from service.memory.vector_memory import VectorMemoryManager

    vmm = VectorMemoryManager(storage_path="/tmp/sessions/abc123")
    await vmm.initialize()               # loads config, creates index
    await vmm.index_memory_files()        # scans + embeds + upserts
    results = await vmm.search("JWT token expiration")
    vmm.save()                            # persist index to disk
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.memory.embedding import (
    EmbeddingProvider,
    get_embedding_provider,
    get_dimension,
)
from service.memory.vector_store import (
    SessionVectorStore,
    VectorSearchResult,
    chunk_text,
)

logger = getLogger(__name__)

# Use configured timezone (unused in this module but kept for consistency)
from service.utils.utils import _configured_tz as _get_tz  # noqa: F401


class VectorMemoryManager:
    """High-level orchestrator for vector-based long-term memory.

    One instance per session.  Lazily initialised — does nothing
    until :meth:`initialize` is awaited.

    Args:
        storage_path: Session's root storage directory.
    """

    def __init__(self, storage_path: str):
        self._storage_path = storage_path
        self._store: Optional[SessionVectorStore] = None
        self._provider: Optional[EmbeddingProvider] = None
        self._enabled = False

        # Config cache (loaded from LTMConfig)
        self._chunk_size = 1024
        self._chunk_overlap = 256
        self._top_k = 6
        self._score_threshold = 0.35
        self._max_inject_chars = 10000

        self._initialized = False

    # ── Properties ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def store(self) -> Optional[SessionVectorStore]:
        return self._store

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """Load config and set up the vector store + embedding provider.

        Returns:
            ``True`` if successfully initialised (and enabled),
            ``False`` if disabled or misconfigured.
        """
        try:
            config = self._load_config()
            if config is None or not config.enabled:
                logger.debug("VectorMemoryManager: disabled by config")
                self._enabled = False
                return False

            # Resolve API key: config value, or fall back to env
            api_key = config.embedding_api_key
            if not api_key:
                import os
                api_key = os.environ.get("LTM_EMBEDDING_API_KEY", "")
            if not api_key:
                logger.warning(
                    "VectorMemoryManager: no embedding API key configured"
                )
                self._enabled = False
                return False

            # Embedding provider
            self._provider = get_embedding_provider(
                provider_name=config.embedding_provider,
                model=config.embedding_model,
                api_key=api_key,
            )

            # Vector store
            dim = self._provider.dimension()
            self._store = SessionVectorStore(
                storage_path=self._storage_path,
                dimension=dim,
            )
            self._store.load_or_create()

            # Cache config values
            self._chunk_size = config.chunk_size
            self._chunk_overlap = config.chunk_overlap
            self._top_k = config.top_k
            self._score_threshold = config.score_threshold
            self._max_inject_chars = config.max_inject_chars

            self._enabled = True
            self._initialized = True

            logger.info(
                "VectorMemoryManager initialized: provider=%s model=%s dim=%d "
                "chunks=%d/%d top_k=%d",
                config.embedding_provider, config.embedding_model, dim,
                self._chunk_size, self._chunk_overlap, self._top_k,
            )
            return True

        except Exception:
            logger.warning(
                "VectorMemoryManager: initialization failed",
                exc_info=True,
            )
            self._enabled = False
            return False

    def save(self) -> None:
        """Persist the vector index to disk."""
        if self._store:
            self._store.save()

    # ── Indexing ──────────────────────────────────────────────────────

    async def index_memory_files(self) -> Dict[str, int]:
        """Scan all long-term memory .md files and index new chunks.

        Reads from ``<storage_path>/memory/*.md``, chunks, embeds,
        and upserts into the FAISS index.  Already-indexed chunks
        (identified by source + chunk_index) are skipped.

        Returns:
            Dict mapping source_file → number of NEW chunks indexed.
        """
        if not self._enabled or not self._provider or not self._store:
            return {}

        memory_dir = Path(self._storage_path) / "memory"
        if not memory_dir.exists():
            return {}

        results: Dict[str, int] = {}

        md_files = sorted(memory_dir.rglob("*.md"))
        for filepath in md_files:
            try:
                if filepath.stat().st_size == 0:
                    continue
                content = filepath.read_text(encoding="utf-8").strip()
                if not content:
                    continue

                rel_path = str(filepath.relative_to(Path(self._storage_path)))
                added = await self._index_single_file(rel_path, content)
                if added > 0:
                    results[rel_path] = added

            except Exception as exc:
                logger.warning(
                    "VectorMemoryManager: failed to index %s: %s",
                    filepath, exc,
                )

        if results:
            self._store.save()
            total = sum(results.values())
            logger.info(
                "VectorMemoryManager: indexed %d new chunks across %d files",
                total, len(results),
            )

        return results

    async def index_text(
        self,
        text: str,
        source_file: str,
        *,
        replace: bool = False,
    ) -> int:
        """Index a single piece of text (e.g. a new execution record).

        Args:
            text: Text content to chunk and embed.
            source_file: Logical source identifier.
            replace: If ``True``, remove previous chunks for this
                     source before adding.

        Returns:
            Number of chunks added.
        """
        if not self._enabled or not self._provider or not self._store:
            return 0

        if replace:
            self._store.remove_source(source_file)

        added = await self._index_single_file(source_file, text)
        if added > 0:
            self._store.save()
        return added

    async def _index_single_file(self, source_file: str, content: str) -> int:
        """Chunk, embed, and upsert a single file's content."""
        chunks = chunk_text(
            content,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )
        if not chunks:
            return 0

        # Embed
        try:
            vectors = await self._provider.embed_batch(chunks)
        except Exception as exc:
            logger.warning(
                "VectorMemoryManager: embedding failed for %s: %s",
                source_file, exc,
            )
            return 0

        # Upsert into FAISS
        added = self._store.add_chunks(
            texts=chunks,
            vectors=vectors,
            source_file=source_file,
        )
        return added

    # ── Search ────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[VectorSearchResult]:
        """Semantic similarity search against the session's vector DB.

        Args:
            query: Natural language search query.
            top_k: Override config top_k.
            score_threshold: Override config score_threshold.

        Returns:
            List of :class:`VectorSearchResult` sorted by descending score.
        """
        if not self._enabled or not self._provider or not self._store:
            return []

        if not query or not query.strip():
            return []

        try:
            query_vector = await self._provider.embed_text(query)
        except Exception as exc:
            logger.warning(
                "VectorMemoryManager: query embedding failed: %s", exc
            )
            return []

        return self._store.search(
            query_vector,
            top_k=top_k or self._top_k,
            score_threshold=score_threshold if score_threshold is not None else self._score_threshold,
        )

    def build_vector_context(
        self,
        results: List[VectorSearchResult],
        *,
        max_chars: Optional[int] = None,
    ) -> Optional[str]:
        """Format vector search results as an XML-tagged context block.

        Args:
            results: Search results from :meth:`search`.
            max_chars: Character budget (default: config max_inject_chars).

        Returns:
            Formatted string for prompt injection, or ``None``.
        """
        if not results:
            return None

        budget = max_chars or self._max_inject_chars
        parts: List[str] = []
        total_chars = 0

        for r in results:
            chunk = (
                f'<vector-memory source="{r.source_file}" '
                f'score="{r.score:.3f}" chunk="{r.chunk_index}">\n'
                f"{r.text}\n"
                f"</vector-memory>"
            )
            if (total_chars + len(chunk)) > budget:
                break
            parts.append(chunk)
            total_chars += len(chunk)

        if not parts:
            return None

        return "\n\n".join(parts)

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic info about the vector memory."""
        base = {
            "enabled": self._enabled,
            "initialized": self._initialized,
        }
        if self._store:
            base.update(self._store.get_stats())
        return base

    # ── Config loader ─────────────────────────────────────────────────

    @staticmethod
    def _load_config():
        """Load ``LTMConfig`` from the global config manager.

        Returns ``None`` if the config system is unavailable.
        """
        try:
            from service.config import get_config_manager
            from service.config.sub_config.general.ltm_config import LTMConfig

            mgr = get_config_manager()
            return mgr.load_config(LTMConfig)
        except Exception:
            logger.debug(
                "VectorMemoryManager: could not load LTMConfig",
                exc_info=True,
            )
            return None
