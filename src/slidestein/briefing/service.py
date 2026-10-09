"""SlideIntentService — orchestrates brief generation and retrieval request mapping."""

from __future__ import annotations

from slidestein.briefing.adapter import brief_to_retrieval_request
from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.briefing.generator import SlideBriefGenerator
from slidestein.retrieval.request import SlideRetrievalRequest


class SlideIntentService:
    """Translates natural-language requests into structured retrieval inputs.

    Composes two steps:
      1. understand() — calls the LLM provider once to produce a ConsultingSlideBrief
      2. to_retrieval_request() — deterministically maps the brief to a SlideRetrievalRequest

    The two steps are intentionally separate so callers can inspect the brief
    before committing to retrieval.
    """

    def __init__(self, generator: SlideBriefGenerator) -> None:
        self._generator = generator

    def understand(self, user_request: str) -> ConsultingSlideBrief:
        """Generate a ConsultingSlideBrief from a natural-language request.

        Raises
        ------
        SlideBriefGenerationError
            If user_request is blank or if the provider call fails.
        """
        from slidestein.briefing.providers.sap_aicore import SlideBriefGenerationError  # noqa: PLC0415

        if not user_request.strip():
            raise SlideBriefGenerationError("user_request must not be blank")

        return self._generator.generate(user_request)

    def to_retrieval_request(
        self,
        brief: ConsultingSlideBrief,
        top_k: int = 5,
    ) -> SlideRetrievalRequest:
        """Deterministically map a brief to a SlideRetrievalRequest. No LLM call."""
        return brief_to_retrieval_request(brief, top_k=top_k)
