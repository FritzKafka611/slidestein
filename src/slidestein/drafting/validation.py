"""Shared draft / slot-map identity validation helper.

Used by M7 (ManagerReviewService) and M8 (VisualQAService) to enforce
identical identity semantics.  Raises an exception built by the caller's
error_factory so each service retains its own error type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from slidestein.drafting.models import SlideContentDraft
    from slidestein.slots.models import TemplateSlotMap


def validate_draft_slot_map_identity(
    draft: "SlideContentDraft",
    slot_map: "TemplateSlotMap",
    error_factory: Callable[[str], Exception],
) -> None:
    """Validate draft/slot-map identity: IDs, dimensions, per-slot shape identity.

    Checks:
    - draft.slide_id == slot_map.slide_id
    - draft.deck_id == slot_map.deck_id (when both set)
    - draft.slide_number == slot_map.slide_number
    - no duplicate slot_id in draft.assignments
    - every slot in slot_map has exactly one assignment (matching shape_id,
      shape_path, slot_role)
    - no assignments reference slot_ids absent from slot_map

    Raises the exception returned by error_factory on the first failure found.
    """
    if draft.slide_id != slot_map.slide_id:
        raise error_factory(
            f"draft.slide_id {draft.slide_id!r} does not match "
            f"slot_map.slide_id {slot_map.slide_id!r}"
        )

    if draft.deck_id is not None and slot_map.deck_id is not None:
        if draft.deck_id != slot_map.deck_id:
            raise error_factory(
                f"draft.deck_id {draft.deck_id!r} does not match "
                f"slot_map.deck_id {slot_map.deck_id!r}"
            )

    if draft.slide_number != slot_map.slide_number:
        raise error_factory(
            f"draft.slide_number {draft.slide_number} does not match "
            f"slot_map.slide_number {slot_map.slide_number}"
        )

    # Build assignment lookup — detect duplicates
    assignments_by_slot_id: dict = {}
    for a in draft.assignments:
        if a.slot_id in assignments_by_slot_id:
            raise error_factory(
                f"Duplicate assignment for slot_id {a.slot_id!r} in draft"
            )
        assignments_by_slot_id[a.slot_id] = a

    # Every slot must have exactly one assignment with matching identity
    for slot in slot_map.slots:
        assignment = assignments_by_slot_id.get(slot.slot_id)
        if assignment is None:
            raise error_factory(
                f"No assignment found for slot_id {slot.slot_id!r} "
                f"(label={slot.semantic_label!r}) in draft. "
                "Every slot in the slot_map must have exactly one "
                "corresponding assignment."
            )
        if assignment.shape_id != slot.shape_id:
            raise error_factory(
                f"Assignment for slot_id {slot.slot_id!r} has "
                f"shape_id={assignment.shape_id} but slot has "
                f"shape_id={slot.shape_id}"
            )
        if assignment.shape_path != slot.shape_path:
            raise error_factory(
                f"Assignment for slot_id {slot.slot_id!r} has "
                f"shape_path={assignment.shape_path!r} but slot has "
                f"shape_path={slot.shape_path!r}"
            )
        if assignment.slot_role != slot.slot_role:
            raise error_factory(
                f"Assignment for slot_id {slot.slot_id!r} has "
                f"slot_role={assignment.slot_role.value!r} but slot has "
                f"slot_role={slot.slot_role.value!r}"
            )

    # No extra assignments (assignments with slot_id not in slot map)
    slot_ids_in_map = {s.slot_id for s in slot_map.slots}
    for a in draft.assignments:
        if a.slot_id not in slot_ids_in_map:
            raise error_factory(
                f"Assignment references slot_id {a.slot_id!r} which is "
                "not present in the slot_map"
            )
