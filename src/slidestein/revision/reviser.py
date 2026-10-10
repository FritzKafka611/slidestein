"""ContentReviser Protocol for M9 (v1.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.drafting.models import SlideContentDraft
    from slidestein.revision.models import ContentRevisionModelOutput


@runtime_checkable
class ContentReviser(Protocol):
    def revise(
        self,
        brief: "ConsultingSlideBrief",
        source_material: Optional[str],
        slot_specs: list[dict],
        target_keys: list[str],
        current_draft: "SlideContentDraft",
        revision_feedback: list[dict],
    ) -> "ContentRevisionModelOutput": ...
