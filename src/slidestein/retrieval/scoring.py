"""Hybrid retrieval scoring functions and weight configuration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)


@dataclass(frozen=True)
class HybridRetrievalWeights:
    """Weights for each scoring dimension.

    Attribute names use the canonical consulting-vocabulary terms.

    Invariants (enforced on construction):
    - every weight is finite
    - every weight is >= 0
    - weights sum to approximately 1.0 (within 1e-6)

    Dynamic renormalization is applied during scoring when some dimensions
    are absent — the denominator is the sum of weights for active dimensions.
    """

    semantic: float = 0.55
    communication_job: float = 0.20
    visual_archetype: float = 0.10
    slide_function: float = 0.05
    storyline_role: float = 0.05
    density: float = 0.05

    def __post_init__(self) -> None:
        weights = [
            self.semantic,
            self.communication_job,
            self.visual_archetype,
            self.slide_function,
            self.storyline_role,
            self.density,
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


DEFAULT_WEIGHTS = HybridRetrievalWeights()


def semantic_score(distance: float) -> float:
    """Convert cosine distance (lower=better) to a similarity score in [0.0, 1.0]."""
    return min(1.0, max(0.0, 1.0 - distance))


def function_fit(
    requested: Optional[SlideFunction], candidate: str
) -> Optional[float]:
    """Score slide_function match.

    Returns None when no slide_function was requested (dimension excluded from scoring).
    """
    if requested is None:
        return None
    return 1.0 if candidate == requested.value else 0.0


def job_fit(
    requested: Optional[CommunicationJob],
    candidate_primary: str,
    candidate_secondary: str,
) -> Optional[float]:
    """Score communication job match.

    Primary match → 1.0, secondary match → 0.5, miss → 0.0.
    Returns None when no job was requested.
    """
    if requested is None:
        return None
    req_val = requested.value
    if candidate_primary == req_val:
        return 1.0
    secondary_list = [s.strip() for s in candidate_secondary.split(",") if s.strip()]
    if req_val in secondary_list:
        return 0.5
    return 0.0


def archetype_fit(
    preferred: Optional[list[VisualArchetype]], candidate: str
) -> Optional[float]:
    """Score visual archetype match against a preferred list.

    Returns None when preferred is None or empty (dimension excluded from scoring).
    Returns 1.0 if candidate is in the preferred set, else 0.0.
    """
    if not preferred:
        return None
    return 1.0 if candidate in {a.value for a in preferred} else 0.0


def role_fit(
    requested: Optional[list[StorylineRole]], candidate_roles: str
) -> Optional[float]:
    """Score storyline role overlap.

    |requested ∩ candidate| / |requested|, naturally in [0, 1].
    Returns None when requested is None or empty.
    """
    if not requested:
        return None
    req_set = {r.value for r in requested}
    candidate_set = {s.strip() for s in candidate_roles.split(",") if s.strip()}
    overlap = req_set & candidate_set
    return len(overlap) / len(req_set)


def density_fit(
    requested: Optional[DensityLevel], candidate: str
) -> Optional[float]:
    """Score density match.

    Returns None when no density was requested.
    """
    if requested is None:
        return None
    return 1.0 if candidate == requested.value else 0.0


def compute_hybrid_score(
    sem_score: float,
    f_fit: Optional[float],
    j_fit: Optional[float],
    a_fit: Optional[float],
    r_fit: Optional[float],
    d_fit: Optional[float],
    weights: HybridRetrievalWeights = DEFAULT_WEIGHTS,
) -> float:
    """Compute the final hybrid score with dynamic weight renormalization.

    Dimensions with a None score are excluded from the weighted sum AND from the
    denominator.  A query with only query_text (all structured dimensions None)
    produces a score equal to the semantic score.

    Parameters
    ----------
    sem_score:
        Semantic similarity score — always present (= semantic_score(distance)).
    f_fit, j_fit, a_fit, r_fit, d_fit:
        Scores for function, job, archetype, role, density.  None = not requested.
    weights:
        Weight configuration.  Defaults to HybridRetrievalWeights defaults.

    Returns
    -------
    float
        Normalized hybrid score in [0, 1].
    """
    active = [(sem_score, weights.semantic)]
    if f_fit is not None:
        active.append((f_fit, weights.slide_function))
    if j_fit is not None:
        active.append((j_fit, weights.communication_job))
    if a_fit is not None:
        active.append((a_fit, weights.visual_archetype))
    if r_fit is not None:
        active.append((r_fit, weights.storyline_role))
    if d_fit is not None:
        active.append((d_fit, weights.density))

    total_weight = sum(w for _, w in active)
    if total_weight == 0.0:
        return 0.0
    return sum(s * w for s, w in active) / total_weight
