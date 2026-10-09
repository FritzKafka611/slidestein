"""Protocol for content draft generators."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.drafting.analysis_models import ContentDraftModelOutput


@runtime_checkable
class ContentDraftGenerator(Protocol):
    def generate(
        self,
        brief: "ConsultingSlideBrief",
        source_material: str | None,
        slot_specs: list[dict],
        groups_context: list[dict],
    ) -> "ContentDraftModelOutput": ...
