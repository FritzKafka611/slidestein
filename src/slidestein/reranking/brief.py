"""VisualRerankBrief — provider-independent communication need derived from SlideRetrievalRequest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)
from slidestein.retrieval.request import SlideRetrievalRequest


@dataclass(frozen=True)
class VisualRerankBrief:
    """Provider-independent representation of the communication need for vision reranking.

    Derived deterministically from a SlideRetrievalRequest.  Contains only what was
    present in the original request — no LLM inference, no new information.
    """

    query_text: str
    slide_function: Optional[SlideFunction]
    primary_communication_job: Optional[CommunicationJob]
    preferred_visual_archetypes: tuple[VisualArchetype, ...]
    storyline_roles: tuple[StorylineRole, ...]
    density: Optional[DensityLevel]
    required_content_elements: tuple[str, ...]


def build_visual_rerank_brief(request: SlideRetrievalRequest) -> VisualRerankBrief:
    """Build a VisualRerankBrief deterministically from a SlideRetrievalRequest."""
    return VisualRerankBrief(
        query_text=request.query_text,
        slide_function=request.slide_function,
        primary_communication_job=request.primary_communication_job,
        preferred_visual_archetypes=tuple(request.preferred_visual_archetypes),
        storyline_roles=tuple(request.storyline_roles),
        density=request.density,
        required_content_elements=tuple(request.required_content_elements),
    )
