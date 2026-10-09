"""Deterministic adapter: ConsultingSlideBrief -> SlideRetrievalRequest."""

from __future__ import annotations

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.retrieval.request import SlideRetrievalRequest


def brief_to_retrieval_request(
    brief: ConsultingSlideBrief,
    top_k: int = 5,
) -> SlideRetrievalRequest:
    """Map a ConsultingSlideBrief to a SlideRetrievalRequest deterministically.

    Field mapping:
        original_request  -> query_text   (NOT key_message; preserves user wording for semantic retrieval)
        slide_function    -> slide_function
        primary_communication_job -> primary_communication_job
        storyline_roles   -> storyline_roles
        preferred_visual_archetypes -> preferred_visual_archetypes
        density           -> density
        required_content_elements -> required_content_elements

    NOT forwarded to SlideRetrievalRequest (M5.1 gap — no corresponding field):
        secondary_communication_jobs  (persisted in brief for future use)
    """
    return SlideRetrievalRequest(
        query_text=brief.original_request,
        slide_function=brief.slide_function,
        primary_communication_job=brief.primary_communication_job,
        storyline_roles=list(brief.storyline_roles),
        preferred_visual_archetypes=list(brief.preferred_visual_archetypes),
        density=brief.density,
        required_content_elements=list(brief.required_content_elements),
        top_k=top_k,
    )
