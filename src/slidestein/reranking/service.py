"""VisionSlideRerankService — orchestrates hybrid retrieval + vision reranking."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from slidestein.reranking.brief import build_visual_rerank_brief
from slidestein.reranking.candidates import VisualCandidateInput
from slidestein.reranking.reranker import VisionReranker
from slidestein.reranking.result import VisionRankedCandidate, VisionRerankResult
from slidestein.reranking.rubric import (
    DEFAULT_VISION_WEIGHTS,
    VisionRerankWeights,
    compute_visual_score,
)
from slidestein.reranking.versions import VISION_RERANK_PROMPT_VERSION, VISION_RERANK_VERSION
from slidestein.retrieval.hybrid import HybridSlideSearch
from slidestein.retrieval.request import SlideRetrievalRequest

_MIN_CANDIDATE_K = 2
_MAX_CANDIDATE_K = 8


class VisionSlideRerankService:
    """Orchestrates hybrid retrieval followed by single-call vision reranking.

    Parameters
    ----------
    searcher:
        Configured HybridSlideSearch instance.
    library:
        SlideLibrary for resolving preview paths by slide_id.
    reranker:
        VisionReranker provider (e.g. SAPAICoreVisionReranker).
    weights:
        Vision rubric weights.  Defaults to VisionRerankWeights defaults.
    """

    def __init__(
        self,
        searcher: HybridSlideSearch,
        library: object,
        reranker: VisionReranker,
        weights: Optional[VisionRerankWeights] = None,
    ) -> None:
        self._searcher = searcher
        self._library = library
        self._reranker = reranker
        self._weights = weights or DEFAULT_VISION_WEIGHTS

    def rerank(
        self,
        request: SlideRetrievalRequest,
        candidate_k: int = 5,
    ) -> VisionRerankResult:
        """Run hybrid retrieval then vision reranking.

        Steps
        -----
        1. Validate candidate_k (2–8).
        2. Build a hybrid request with top_k = candidate_k.
        3. Run HybridSlideSearch.
        4. Resolve preview path for each result via the library.
        5. Fail fast if any preview is missing.
        6. Assign deterministic candidate keys C1…Cn.
        7. Build VisualRerankBrief.
        8. Call VisionReranker ONCE with all candidates.
        9. Validate exact candidate coverage.
        10. Compute visual scores in application code.
        11. Sort by visual_score descending; tie-break by hybrid rank ascending.
        12. Return VisionRerankResult.

        Raises
        ------
        ValueError
            For out-of-range candidate_k.
        RuntimeError
            If a preview is missing or candidate coverage is invalid.
        """
        if not (_MIN_CANDIDATE_K <= candidate_k <= _MAX_CANDIDATE_K):
            raise ValueError(
                f"candidate_k must be between {_MIN_CANDIDATE_K} and {_MAX_CANDIDATE_K}; "
                f"got {candidate_k}"
            )

        # Run hybrid retrieval with the requested candidate count.
        hybrid_request = SlideRetrievalRequest(
            query_text=request.query_text,
            slide_function=request.slide_function,
            primary_communication_job=request.primary_communication_job,
            preferred_visual_archetypes=list(request.preferred_visual_archetypes),
            storyline_roles=list(request.storyline_roles),
            density=request.density,
            required_content_elements=list(request.required_content_elements),
            top_k=candidate_k,
            strict_slide_function=request.strict_slide_function,
        )
        hybrid_results = self._searcher.search(hybrid_request)

        # Resolve preview paths — fail before calling Claude if any are missing.
        candidates: list[VisualCandidateInput] = []
        for i, result in enumerate(hybrid_results, 1):
            record = self._library.get_slide(result.slide_id)
            if record is None:
                raise RuntimeError(
                    f"Slide {result.slide_id} returned by hybrid search but not "
                    "found in library.  Run 'index' to sync."
                )
            if record.preview_path is None:
                raise RuntimeError(
                    f"Slide {result.slide_id} (slide #{result.slide_number}) has no "
                    "preview path.  Run 'index' with preview rendering enabled."
                )
            preview = Path(record.preview_path)
            if not preview.exists():
                raise RuntimeError(
                    f"Preview file not found for slide {result.slide_id} "
                    f"(slide #{result.slide_number}): {preview}"
                )
            candidates.append(
                VisualCandidateInput(
                    candidate_key=f"C{i}",
                    slide_id=result.slide_id,
                    deck_id=result.deck_id,
                    slide_number=result.slide_number,
                    preview_path=preview,
                    hybrid_rank=result.rank,
                    hybrid_score=result.hybrid_score,
                    semantic_score=result.semantic_score,
                )
            )

        brief = build_visual_rerank_brief(request)

        # Single vision call with all candidates.
        model_output = self._reranker.assess(brief, candidates)

        # Validate exact coverage.
        expected_keys = {c.candidate_key for c in candidates}
        model_output.validate_coverage(expected_keys)

        # Compute scores and sort.
        candidate_by_key = {c.candidate_key: c for c in candidates}
        scored: list[tuple[float, VisualCandidateInput, object]] = []
        for assessment in model_output.assessments:
            candidate = candidate_by_key[assessment.candidate_key]
            score = compute_visual_score(assessment, self._weights)
            scored.append((score, candidate, assessment))

        scored.sort(key=lambda t: (-t[0], t[1].hybrid_rank))

        ranked: list[VisionRankedCandidate] = []
        for vision_rank, (score, candidate, assessment) in enumerate(scored, 1):
            ranked.append(
                VisionRankedCandidate(
                    vision_rank=vision_rank,
                    candidate_key=candidate.candidate_key,
                    slide_id=candidate.slide_id,
                    slide_number=candidate.slide_number,
                    visual_score=score,
                    communication_structure_fit=assessment.communication_structure_fit,
                    content_capacity_fit=assessment.content_capacity_fit,
                    visual_hierarchy=assessment.visual_hierarchy,
                    argument_flow=assessment.argument_flow,
                    density_fit=assessment.density_fit,
                    original_hybrid_rank=candidate.hybrid_rank,
                    hybrid_score=candidate.hybrid_score,
                    semantic_score=candidate.semantic_score,
                    rationale=assessment.rationale,
                    strengths=assessment.strengths,
                    limitations=assessment.limitations,
                )
            )

        return VisionRerankResult(
            selected_slide_id=ranked[0].slide_id,
            selected_slide_number=ranked[0].slide_number,
            vision_rerank_version=VISION_RERANK_VERSION,
            prompt_version=VISION_RERANK_PROMPT_VERSION,
            ranked_candidates=ranked,
        )
