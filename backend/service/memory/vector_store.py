"""
FAISS-backed per-session vector store for long-term memory.

Each session gets its own FAISS index stored on disk alongside the
existing ``memory/`` folder::

    <session_storage>/
        memory/
            MEMORY.md
            2026-03-02.md
            ...
        vectordb/
            index.faiss       ← FAISS flat L2 index
            metadata.json     ← chunk metadata (text, source, timestamps)

Design decisions:
    - **Index type:** ``IndexFlatIP`` (inner product / cosine sim on
      L2-normalised vectors).  Simple, no training required, perfect
      for the small-to-medium scale of per-session memory.
    - **Persistence:** Index is saved/loaded with ``faiss.write_index``
      / ``faiss.read_index``.  Metadata is stored in a JSON sidecar.
    - **Incremental upsert:** New chunks are appended; existing chunks
      (identified by ``(source_file, chunk_index)``) are skipped.
    - **Thread-safety:** A ``threading.Lock`` guards mutations.

Usage::

    from service.memory.vector_store import SessionVectorStore
    store = SessionVectorStore(storage_path="/tmp/sessions/abc123", dimension=1536)
    store.load_or_create()

    store.add_chunks(texts=["chunk1", "chunk2"], vectors=[v1, v2],
                     metadatas=[{"source": "MEMORY.md"}, ...])

    results = store.search(query_vector, top_k=5)
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = getLogger(__name__)

KST = timezone(timedelta(hours=9))

# Directory name inside the session storage path
_VECTORDB_DIR = "vectordb"
_INDEX_FILE = "index.faiss"
_META_FILE = "metadata.json"


# ── Chunk metadata record ─────────────────────────────────────────────

@dataclass
class ChunkMeta:
    """Metadata stored alongside each vector in the index."""

    text: str                       # The original chunk text
    source_file: str                # e.g. "memory/MEMORY.md"
    chunk_index: int                # Chunk ordinal within the source
    created_at: str = ""            # ISO-8601 timestamp
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChunkMeta":
        return cls(
            text=d.get("text", ""),
            source_file=d.get("source_file", ""),
            chunk_index=d.get("chunk_index", 0),
            created_at=d.get("created_at", ""),
            metadata=d.get("metadata", {}),
        )


# ── Search result ─────────────────────────────────────────────────────

@dataclass
class VectorSearchResult:
    """A single result from a vector similarity search."""

    text: str
    source_file: str
    score: float                    # Cosine similarity (0–1)
    chunk_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Session Vector Store
# ======================================================================

class SessionVectorStore:
    """Per-session FAISS vector database.

    Manages a flat inner-product index over L2-normalised vectors
    so that similarity scores correspond to cosine similarity.

    Args:
        storage_path: The session's root storage directory.
        dimension: Vector dimensionality (must match the embedding model).
    """

    def __init__(self, storage_path: str, dimension: int):
        self._storage_path = Path(storage_path)
        self._db_dir = self._storage_path / _VECTORDB_DIR
        self._index_path = self._db_dir / _INDEX_FILE
        self._meta_path = self._db_dir / _META_FILE
        self._dimension = dimension

        self._index: Optional[Any] = None          # faiss.IndexFlatIP
        self._chunks: List[ChunkMeta] = []          # Parallel to index rows
        self._chunk_keys: set = set()               # (source_file, chunk_index) dedup
        self._lock = threading.Lock()
        self._dirty = False

    # ── Properties ────────────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def size(self) -> int:
        """Number of vectors currently in the index."""
        if self._index is None:
            return 0
        return self._index.ntotal

    @property
    def db_dir(self) -> Path:
        return self._db_dir

    # ── Lifecycle ─────────────────────────────────────────────────────

    def load_or_create(self) -> None:
        """Load an existing FAISS index from disk, or create a new one."""
        import faiss  # Lazy import to avoid hard dependency when disabled

        self._db_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if self._index_path.exists() and self._meta_path.exists():
                try:
                    self._index = faiss.read_index(str(self._index_path))
                    with open(self._meta_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    self._chunks = [ChunkMeta.from_dict(d) for d in raw]
                    self._chunk_keys = {
                        (c.source_file, c.chunk_index) for c in self._chunks
                    }
                    logger.info(
                        "VectorStore loaded: %d vectors, dim=%d from %s",
                        self._index.ntotal, self._dimension, self._db_dir,
                    )
                    # Validate dimension consistency
                    if self._index.d != self._dimension:
                        logger.warning(
                            "VectorStore dimension mismatch: index=%d, expected=%d. "
                            "Rebuilding index.",
                            self._index.d, self._dimension,
                        )
                        self._create_empty_index(faiss)
                    return
                except Exception as exc:
                    logger.warning(
                        "VectorStore: failed to load, creating fresh: %s", exc
                    )

            self._create_empty_index(faiss)

    def _create_empty_index(self, faiss_module) -> None:
        """Create a fresh empty FAISS index."""
        self._index = faiss_module.IndexFlatIP(self._dimension)
        self._chunks = []
        self._chunk_keys = set()
        self._dirty = True
        logger.info(
            "VectorStore created: empty index, dim=%d at %s",
            self._dimension, self._db_dir,
        )

    def save(self) -> None:
        """Persist the index and metadata to disk."""
        if self._index is None:
            return

        import faiss

        with self._lock:
            if not self._dirty:
                return

            self._db_dir.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(self._index_path))

            meta_list = [c.to_dict() for c in self._chunks]
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False)

            self._dirty = False
            logger.debug(
                "VectorStore saved: %d vectors to %s",
                self._index.ntotal, self._db_dir,
            )

    def clear(self) -> None:
        """Delete the index and start fresh."""
        import faiss

        with self._lock:
            self._create_empty_index(faiss)
            # Remove disk files
            if self._index_path.exists():
                self._index_path.unlink()
            if self._meta_path.exists():
                self._meta_path.unlink()
            self._dirty = False
            logger.info("VectorStore cleared: %s", self._db_dir)

    # ── Write operations ──────────────────────────────────────────────

    def add_chunks(
        self,
        *,
        texts: List[str],
        vectors: List[List[float]],
        source_file: str,
        start_chunk_index: int = 0,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Add text chunks and their corresponding vectors to the index.

        Duplicate chunks (same ``source_file`` + ``chunk_index``) are skipped.

        Args:
            texts: The text content of each chunk.
            vectors: Pre-computed embedding vectors.
            source_file: Source filename (relative to session storage).
            start_chunk_index: Starting chunk ordinal.
            metadatas: Extra metadata per chunk.

        Returns:
            Number of new chunks actually added (after dedup).
        """
        if len(texts) != len(vectors):
            raise ValueError(
                f"texts ({len(texts)}) and vectors ({len(vectors)}) "
                f"must have the same length"
            )
        if not texts:
            return 0

        now_str = datetime.now(KST).isoformat()

        new_vecs: List[List[float]] = []
        new_metas: List[ChunkMeta] = []

        with self._lock:
            for i, (text, vec) in enumerate(zip(texts, vectors)):
                idx = start_chunk_index + i
                key = (source_file, idx)
                if key in self._chunk_keys:
                    continue  # Skip duplicate

                meta = ChunkMeta(
                    text=text,
                    source_file=source_file,
                    chunk_index=idx,
                    created_at=now_str,
                    metadata=metadatas[i] if metadatas and i < len(metadatas) else {},
                )
                new_vecs.append(vec)
                new_metas.append(meta)
                self._chunk_keys.add(key)

            if not new_vecs:
                return 0

            # Normalise and add to index
            arr = np.array(new_vecs, dtype=np.float32)
            _l2_normalize(arr)
            self._index.add(arr)
            self._chunks.extend(new_metas)
            self._dirty = True

        logger.debug(
            "VectorStore: added %d chunks from %s (total: %d)",
            len(new_metas), source_file, self.size,
        )
        return len(new_metas)

    def remove_source(self, source_file: str) -> int:
        """Remove all chunks from a given source file.

        Because FAISS ``IndexFlatIP`` doesn't support in-place deletion,
        this method rebuilds the index without the matching entries.

        Args:
            source_file: Source file path to remove.

        Returns:
            Number of chunks removed.
        """
        import faiss

        with self._lock:
            keep_idx = [
                i for i, c in enumerate(self._chunks)
                if c.source_file != source_file
            ]
            removed = len(self._chunks) - len(keep_idx)
            if removed == 0:
                return 0

            # Rebuild index
            if keep_idx:
                old_vecs = np.array(
                    [self._index.reconstruct(i) for i in keep_idx],
                    dtype=np.float32,
                )
                self._chunks = [self._chunks[i] for i in keep_idx]
                self._index = faiss.IndexFlatIP(self._dimension)
                self._index.add(old_vecs)
            else:
                self._create_empty_index(faiss)

            self._chunk_keys = {
                (c.source_file, c.chunk_index) for c in self._chunks
            }
            self._dirty = True

        logger.debug(
            "VectorStore: removed %d chunks for %s (total: %d)",
            removed, source_file, self.size,
        )
        return removed

    # ── Search ────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: List[float],
        *,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> List[VectorSearchResult]:
        """Search for the most similar chunks to a query vector.

        Args:
            query_vector: The embedding of the search query.
            top_k: Maximum results to return.
            score_threshold: Minimum cosine similarity.

        Returns:
            List of :class:`VectorSearchResult` sorted by descending score.
        """
        if self._index is None or self._index.ntotal == 0:
            return []

        q = np.array([query_vector], dtype=np.float32)
        _l2_normalize(q)

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(q, k)

        results: List[VectorSearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._chunks):
                continue
            sim = float(score)
            if sim < score_threshold:
                continue

            chunk = self._chunks[idx]
            results.append(VectorSearchResult(
                text=chunk.text,
                source_file=chunk.source_file,
                score=sim,
                chunk_index=chunk.chunk_index,
                metadata=chunk.metadata,
            ))

        return results

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return a summary of the vector store state."""
        source_counts: Dict[str, int] = {}
        for c in self._chunks:
            source_counts[c.source_file] = source_counts.get(c.source_file, 0) + 1

        return {
            "total_vectors": self.size,
            "dimension": self._dimension,
            "sources": source_counts,
            "index_file_exists": self._index_path.exists(),
            "db_dir": str(self._db_dir),
        }


# ── Helpers ───────────────────────────────────────────────────────────

def _l2_normalize(vectors: np.ndarray) -> None:
    """In-place L2 normalisation (rows)."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    vectors /= norms


def chunk_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> List[str]:
    """Split text into overlapping chunks.

    Attempts to split on paragraph / sentence boundaries when possible.

    Args:
        text: Full text to split.
        chunk_size: Target character count per chunk.
        chunk_overlap: Overlap between consecutive chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    if len(text) <= chunk_size:
        return [text.strip()]

    chunks: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        # Try to find a natural break point near the end
        if end < text_len:
            # Prefer paragraph break
            para_break = text.rfind("\n\n", start + chunk_size // 2, end)
            if para_break > start:
                end = para_break + 2  # Include the double newline
            else:
                # Try sentence boundary (. ! ?)
                for delim in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
                    sent_break = text.rfind(delim, start + chunk_size // 2, end)
                    if sent_break > start:
                        end = sent_break + len(delim)
                        break
                else:
                    # Try line break
                    line_break = text.rfind("\n", start + chunk_size // 2, end)
                    if line_break > start:
                        end = line_break + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # If we've consumed all remaining text, stop.
        if end >= text_len:
            break

        # Advance with overlap – ensure at least 1 char forward progress.
        start = max(start + 1, end - chunk_overlap)

    return chunks
