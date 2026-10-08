"""VisionReranker — provider-independent protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from slidestein.reranking.brief import VisualRerankBrief
from slidestein.reranking.candidates import VisualCandidateInput
from slidestein.reranking.rubric import VisualRerankModelOutput


@runtime_checkable
class VisionReranker(Protocol):
    """Provider-independent interface for vision-based candidate reranking.

    Implementations must make exactly ONE model call containing all candidates.
    """

    def assess(
        self,
        brief: VisualRerankBrief,
        candidates: list[VisualCandidateInput],
    ) -> VisualRerankModelOutput:
        """Assess all candidates in a single model call.

        Parameters
        ----------
        brief:
            The communication need derived from the retrieval request.
        candidates:
            All candidate slides to evaluate (keys C1…Cn).

        Returns
        -------
        VisualRerankModelOutput
            Raw model output with one VisualCandidateAssessment per candidate.
        """
        ...
