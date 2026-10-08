"""HybridSlideSearch — semantic + metadata hybrid retrieval service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from slidestein.retrieval.provider import EmbeddingProvider
from slidestein.retrieval.request import SlideRetrievalRequest, build_enriched_query
from slidestein.retrieval.scoring import (
    DEFAULT_WEIGHTS,
    HybridRetrievalWeights,
    archetype_fit,
    compute_hybrid_score,
    density_fit,
    function_fit,
    job_fit,
    role_fit,
    semantic_score as _semantic_score,
)
from slidestein.retrieval.store import SlideVectorStore


@dataclass
class HybridSlideSearchResult:
    """A single result from HybridSlideSearch, with full score explainability."""

    rank: int
    slide_id: str
    deck_id: str
    slide_number: int
    hybrid_score: float
    semantic_distance: float
    semantic_score: float
    slide_function_fit: Optional[float]
    communication_job_fit: Optional[float]
    visual_archetype_fit: Optional[float]
    storyline_role_fit: Optional[float]
    density_fit: Optional[float]
    slide_function: str
    primary_communication_job: str
    secondary_communication_jobs: str
    storyline_roles: str
    visual_archetype: str
    density: str
    description: str


class HybridSlideSearch:
    """Hybrid slide retrieval combining semantic and structured-metadata scoring.

    Parameters
    ----------
    provider:
        Embedding provider used to embed the query.
    store:
        LanceDB vector store to search.
    weights:
        Scoring weights.  Defaults to HybridRetrievalWeights defaults.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        store: SlideVectorStore,
        weights: Optional[HybridRetrievalWeights] = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._weights = weights or DEFAULT_WEIGHTS

    def search(self, request: SlideRetrievalRequest) -> list[HybridSlideSearchResult]:
        """Execute a hybrid search and return ranked results.

        Steps:
        1. Build enriched query text (query + required_content_elements).
        2. Embed the enriched query (one SAP call).
        3. Retrieve candidate pool = max(top_k * 5, 25) from the vector store.
        4. If strict_slide_function, filter candidates to matching function only.
        5. Score each candidate with the hybrid scoring functions.
        6. Sort by hybrid_score descending, semantic_score as tie-breaker.
        7. Return top_k results with rank assigned 1-based.
        """
        enriched_query = build_enriched_query(request)
        query_vector = self._provider.embed_query(enriched_query)

        candidate_k = max(request.top_k * 5, 25)
        raw_candidates = self._store.search_cosine(
            query_vector=query_vector,
            top_k=candidate_k,
            active_only=True,
        )

        # Strict function filter applied AFTER vector search to preserve pool size.
        if request.strict_slide_function and request.slide_function is not None:
            target_fn = request.slide_function.value
            raw_candidates = [
                c for c in raw_candidates if c.get("slide_function") == target_fn
            ]

        # Score candidates.
        scored: list[tuple] = []
        for row in raw_candidates:
            distance = row["_distance"]
            sem = _semantic_score(distance)

            f = function_fit(request.slide_function, row.get("slide_function", ""))
            j = job_fit(
                request.primary_communication_job,
                row.get("primary_communication_job", ""),
                row.get("secondary_communication_jobs", ""),
            )
            a = archetype_fit(request.preferred_visual_archetypes, row.get("visual_archetype", ""))
            r = role_fit(request.storyline_roles, row.get("storyline_roles", ""))
            d = density_fit(request.density, row.get("density", ""))

            hybrid = compute_hybrid_score(sem, f, j, a, r, d, self._weights)
            scored.append((hybrid, sem, distance, f, j, a, r, d, row))

        # Sort by hybrid_score descending, then semantic_score for tie-breaking.
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

        results: list[HybridSlideSearchResult] = []
        for rank_idx, (hybrid, sem, dist, f, j, a, r, d, row) in enumerate(
            scored[: request.top_k], start=1
        ):
            results.append(
                HybridSlideSearchResult(
                    rank=rank_idx,
                    slide_id=row["slide_id"],
                    deck_id=row.get("deck_id", ""),
                    slide_number=row.get("slide_number", 0),
                    hybrid_score=hybrid,
                    semantic_distance=dist,
                    semantic_score=sem,
                    slide_function_fit=f,
                    communication_job_fit=j,
                    visual_archetype_fit=a,
                    storyline_role_fit=r,
                    density_fit=d,
                    slide_function=row.get("slide_function", ""),
                    primary_communication_job=row.get("primary_communication_job", ""),
                    secondary_communication_jobs=row.get("secondary_communication_jobs", ""),
                    storyline_roles=row.get("storyline_roles", ""),
                    visual_archetype=row.get("visual_archetype", ""),
                    density=row.get("density", ""),
                    description=row.get("description", ""),
                )
            )
        return results
