"""
Embedding provider abstraction for the vector memory system.

Supports three providers:
  - **OpenAI**   : text-embedding-3-small / large / ada-002
  - **Google**   : text-embedding-004 / embedding-001
  - **Anthropic**: Voyage AI — voyage-3 / voyage-3-large / voyage-3-lite

Each provider implements a common interface for:
  1. Single text → vector   (``embed_text``)
  2. Batch texts → vectors  (``embed_batch``)
  3. Dimension query        (``dimension``)

Usage::

    from service.memory.embedding import get_embedding_provider

    provider = get_embedding_provider("openai", "text-embedding-3-small", api_key="sk-...")
    vector = await provider.embed_text("Hello world")          # list[float]
    vectors = await provider.embed_batch(["Hello", "World"])   # list[list[float]]
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, List, Optional, Type

import httpx

logger = getLogger(__name__)

# ── Max batch size per provider (API limits) ──────────────────────────
_DEFAULT_BATCH = 96


# ======================================================================
# Abstract base
# ======================================================================

class EmbeddingProvider(ABC):
    """Common interface for all embedding providers."""

    def __init__(self, model: str, api_key: str, **kwargs):
        self.model = model
        self.api_key = api_key

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Embed a single text and return its vector."""

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts and return their vectors."""

    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimension for the current model."""


# ======================================================================
# OpenAI
# ======================================================================

# Known dimensions per model
_OPENAI_DIMS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_OPENAI_URL = "https://api.openai.com/v1/embeddings"


class OpenAIEmbedding(EmbeddingProvider):
    """OpenAI Embeddings API provider."""

    async def embed_text(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        vectors: List[List[float]] = []

        for i in range(0, len(texts), _DEFAULT_BATCH):
            batch = texts[i : i + _DEFAULT_BATCH]
            payload = {"input": batch, "model": self.model}
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(_OPENAI_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            # Sort by index to preserve order
            sorted_data = sorted(data["data"], key=lambda d: d["index"])
            vectors.extend([d["embedding"] for d in sorted_data])

        return vectors

    def dimension(self) -> int:
        return _OPENAI_DIMS.get(self.model, 1536)


# ======================================================================
# Google (Gemini)
# ======================================================================

_GOOGLE_DIMS: Dict[str, int] = {
    "text-embedding-004": 768,
    "embedding-001": 768,
}

_GOOGLE_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
)


class GoogleEmbedding(EmbeddingProvider):
    """Google Generative AI Embeddings (Gemini) provider."""

    async def embed_text(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        vectors: List[List[float]] = []
        url = _GOOGLE_URL_TEMPLATE.format(model=self.model)

        for i in range(0, len(texts), _DEFAULT_BATCH):
            batch = texts[i : i + _DEFAULT_BATCH]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": t}]},
                    }
                    for t in batch
                ]
            }
            params = {"key": self.api_key}

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, params=params)
                resp.raise_for_status()
                data = resp.json()

            for emb in data.get("embeddings", []):
                vectors.append(emb["values"])

        return vectors

    def dimension(self) -> int:
        return _GOOGLE_DIMS.get(self.model, 768)


# ======================================================================
# Anthropic / Voyage AI
# ======================================================================

_VOYAGE_DIMS: Dict[str, int] = {
    "voyage-3-large": 1024,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-code-3": 1024,
}

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


class VoyageEmbedding(EmbeddingProvider):
    """Voyage AI Embeddings provider (Anthropic partner)."""

    async def embed_text(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        vectors: List[List[float]] = []

        for i in range(0, len(texts), _DEFAULT_BATCH):
            batch = texts[i : i + _DEFAULT_BATCH]
            payload = {
                "input": batch,
                "model": self.model,
                "input_type": "document",
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(_VOYAGE_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            for d in data.get("data", []):
                vectors.append(d["embedding"])

        return vectors

    def dimension(self) -> int:
        return _VOYAGE_DIMS.get(self.model, 1024)


# ======================================================================
# Factory
# ======================================================================

_PROVIDER_MAP: Dict[str, Type[EmbeddingProvider]] = {
    "openai": OpenAIEmbedding,
    "google": GoogleEmbedding,
    "anthropic": VoyageEmbedding,
}


def get_embedding_provider(
    provider_name: str,
    model: str,
    api_key: str,
) -> EmbeddingProvider:
    """Instantiate the appropriate embedding provider.

    Args:
        provider_name: ``"openai"`` | ``"google"`` | ``"anthropic"``
        model: Model identifier string.
        api_key: API key for the provider.

    Returns:
        An :class:`EmbeddingProvider` instance.

    Raises:
        ValueError: If *provider_name* is unknown.
    """
    cls = _PROVIDER_MAP.get(provider_name)
    if cls is None:
        available = ", ".join(sorted(_PROVIDER_MAP))
        raise ValueError(
            f"Unknown embedding provider '{provider_name}'. "
            f"Available: {available}"
        )
    return cls(model=model, api_key=api_key)


def get_dimension(provider_name: str, model: str) -> int:
    """Return the expected vector dimension for a provider/model pair."""
    dims_map = {
        "openai": _OPENAI_DIMS,
        "google": _GOOGLE_DIMS,
        "anthropic": _VOYAGE_DIMS,
    }
    return dims_map.get(provider_name, {}).get(model, 1536)
