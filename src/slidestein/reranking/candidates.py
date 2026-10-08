"""VisualCandidateInput — provider-independent candidate representation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VisualCandidateInput:
    """One candidate slide passed to the vision reranker.

    Candidate keys are deterministic: C1, C2, C3, ...
    They are the ONLY identifiers the vision model is allowed to return.
    No taxonomy labels or hybrid scores are included here — those are
    intentionally withheld from the vision model to ensure an independent
    structural judgement.
    """

    candidate_key: str
    slide_id: str
    deck_id: str
    slide_number: int
    preview_path: Path

    hybrid_rank: int
    hybrid_score: float
    semantic_score: float
