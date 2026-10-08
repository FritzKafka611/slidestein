"""Vision reranking rubric: weights, assessment model, output model, score computation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionRerankWeights:
    """Fixed weights for the five visual rubric dimensions.

    Invariants (enforced on construction):
    - every weight is finite
    - every weight is >= 0
    - weights sum to approximately 1.0 (within 1e-6)
    """

    communication_structure_fit: float = 0.30
    content_capacity_fit: float = 0.25
    visual_hierarchy: float = 0.20
    argument_flow: float = 0.15
    density_fit: float = 0.10

    def __post_init__(self) -> None:
        weights = [
            self.communication_structure_fit,
            self.content_capacity_fit,
            self.visual_hierarchy,
            self.argument_flow,
            self.density_fit,
        ]
        for w in weights:
            if not math.isfinite(w):
                raise ValueError(f"All weights must be finite; got {w!r}")
            if w < 0:
                raise ValueError(f"All weights must be >= 0; got {w!r}")
        total = sum(weights)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Weights must sum to approximately 1.0; got {total!r}"
            )


DEFAULT_VISION_WEIGHTS = VisionRerankWeights()


# ---------------------------------------------------------------------------
# Pydantic output models (parsed from Claude's JSON response)
# ---------------------------------------------------------------------------


class VisualCandidateAssessment(BaseModel):
    """Claude's assessment of one candidate slide."""

    candidate_key: str

    communication_structure_fit: int = Field(ge=1, le=5)
    content_capacity_fit: int = Field(ge=1, le=5)
    visual_hierarchy: int = Field(ge=1, le=5)
    argument_flow: int = Field(ge=1, le=5)
    density_fit: int = Field(ge=1, le=5)

    rationale: str
    strengths: list[str]
    limitations: list[str]


class VisualRerankModelOutput(BaseModel):
    """The full structured output from the vision model."""

    assessments: list[VisualCandidateAssessment]

    @model_validator(mode="after")
    def check_no_duplicate_keys(self) -> "VisualRerankModelOutput":
        keys = [a.candidate_key for a in self.assessments]
        seen: set[str] = set()
        dups = [k for k in keys if k in seen or seen.add(k)]  # type: ignore[func-returns-value]
        if dups:
            raise ValueError(f"Duplicate candidate keys in model output: {dups}")
        return self

    def validate_coverage(self, expected_keys: set[str]) -> None:
        """Raise ValueError if assessments do not exactly match expected_keys."""
        actual_keys = {a.candidate_key for a in self.assessments}
        if actual_keys == expected_keys:
            return
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        parts: list[str] = []
        if missing:
            parts.append(f"missing candidates: {sorted(missing)}")
        if extra:
            parts.append(f"unknown candidates: {sorted(extra)}")
        raise ValueError(f"Invalid candidate coverage — {'; '.join(parts)}")


# ---------------------------------------------------------------------------
# Score computation (application-side, not delegated to the model)
# ---------------------------------------------------------------------------


def compute_visual_score(
    assessment: VisualCandidateAssessment,
    weights: VisionRerankWeights = DEFAULT_VISION_WEIGHTS,
) -> float:
    """Compute visual_score in [0.2, 1.0] from integer rubric scores 1..5.

    Formula:
        weighted_average = sum(score_i * weight_i)
        visual_score = weighted_average / 5

    Practically reachable range: 0.2 (all 1s) .. 1.0 (all 5s).
    0.0 is mathematically outside the reachable range for valid integer scores.
    """
    raw = (
        assessment.communication_structure_fit * weights.communication_structure_fit
        + assessment.content_capacity_fit * weights.content_capacity_fit
        + assessment.visual_hierarchy * weights.visual_hierarchy
        + assessment.argument_flow * weights.argument_flow
        + assessment.density_fit * weights.density_fit
    )
    return raw / 5.0
