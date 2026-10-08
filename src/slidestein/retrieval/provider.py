"""Provider-independent embedding abstraction.

The rest of the application depends only on these types — never on SAP SDK types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class EmbeddingBatch:
    """Result of embedding one or more texts."""

    vectors: list[list[float]]
    model: str
    dimension: int


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal protocol for embedding providers."""

    def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
        """Embed a batch of retrieval documents (DOCUMENT input type)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query (QUERY input type)."""
        ...
