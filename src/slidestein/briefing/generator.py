"""SlideBriefGenerator — provider-independent protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from slidestein.briefing.brief import ConsultingSlideBrief


@runtime_checkable
class SlideBriefGenerator(Protocol):
    """Protocol for generating a ConsultingSlideBrief from a natural-language request."""

    def generate(self, user_request: str) -> ConsultingSlideBrief: ...
