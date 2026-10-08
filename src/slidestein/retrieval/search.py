"""Provider-independent semantic slide search.

Pure vector cosine similarity — no hybrid scoring, no reranking, no filters.
"""

from __future__ import annotations

from dataclasses import dataclass

from slidestein.retrieval.provider import EmbeddingProvider
from slidestein.retrieval.store import SearchResult, SlideVectorStore


@dataclass
class SlideSearchResult:
    """Single ranked result from SemanticSlideSearch."""

    rank: int
    slide_id: str
    deck_id: str
    slide_number: int
    distance: float
    slide_function: str
    primary_communication_job: str | None
    visual_archetype: str
    density: str
    description: str


class SemanticSlideSearch:
    """Semantic search over the slide embedding index.

    Parameters
    ----------
    provider:
        EmbeddingProvider used to embed the query.
    store:
        SlideVectorStore to search.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        store: SlideVectorStore,
    ) -> None:
        self._provider = provider
        self._store = store

    def search(self, query: str, top_k: int = 5) -> list[SlideSearchResult]:
        """Return top_k slides most semantically similar to *query*.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Number of results to return.

        Raises
        ------
        ValueError
            If query is blank or top_k <= 0.
        """
        if not query.strip():
            raise ValueError("query must not be blank")
        if top_k <= 0:
            raise ValueError(f"top_k must be > 0, got {top_k}")

        query_vec = self._provider.embed_query(query)
        raw_rows = self._store.search_cosine(query_vec, top_k=top_k, active_only=True)

        results: list[SlideSearchResult] = []
        for i, row in enumerate(raw_rows, start=1):
            job_raw = row.get("primary_communication_job", "") or ""
            results.append(
                SlideSearchResult(
                    rank=i,
                    slide_id=row["slide_id"],
                    deck_id=row.get("deck_id", ""),
                    slide_number=row.get("slide_number", 0),
                    distance=row["_distance"],
                    slide_function=row.get("slide_function", ""),
                    primary_communication_job=job_raw if job_raw else None,
                    visual_archetype=row.get("visual_archetype", ""),
                    density=row.get("density", ""),
                    description=row.get("description", ""),
                )
            )
        return results
