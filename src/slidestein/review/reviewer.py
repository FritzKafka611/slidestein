"""ManagerReviewer Protocol — implemented by provider classes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.review.models import ManagerReviewModelOutput


@runtime_checkable
class ManagerReviewer(Protocol):
    def review(
        self,
        brief: "ConsultingSlideBrief",
        source_material: Optional[str],
        slot_review_specs: list[dict],
        group_descriptions: Optional[list[dict]] = None,
    ) -> "ManagerReviewModelOutput": ...
