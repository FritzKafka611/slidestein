"""VisionRerankResult — the fully explainable vision reranking output."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VisionRankedCandidate:
    """One candidate in the vision-ranked result."""

    vision_rank: int
    candidate_key: str
    slide_id: str
    slide_number: int

    visual_score: float

    communication_structure_fit: int
    content_capacity_fit: int
    visual_hierarchy: int
    argument_flow: int
    density_fit: int

    original_hybrid_rank: int
    hybrid_score: float
    semantic_score: float

    rationale: str
    strengths: list[str]
    limitations: list[str]


@dataclass
class VisionRerankResult:
    """Complete output from VisionSlideRerankService.rerank()."""

    selected_slide_id: str
    selected_slide_number: int
    vision_rerank_version: str
    prompt_version: str

    ranked_candidates: list[VisionRankedCandidate]
