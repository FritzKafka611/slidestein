"""Tests for draft ↔ slot-map identity validation in ManagerReviewService (M7 v1.1).

All tests assert reviewer.review() is NEVER called when identity mismatches
are detected — rejection happens before the provider.

Also covers M7 finalization contract hygiene:
  - draft.brief_key_message == brief.key_message
  - defensive NEEDS_INPUT gate
  - group member integrity
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.review.errors import ManagerReviewError
from slidestein.review.models import ManagerReviewRequest
from slidestein.review.service import ManagerReviewService
from slidestein.slots.models import SlotGroup, TemplateSlotMap
from slidestein.slots.roles import SlotRole
from tests.test_review.conftest import (
    make_assignment,
    make_brief,
    make_complete_draft,
    make_model_output,
    make_slot,
    make_slot_map,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service():
    reviewer = MagicMock()
    reviewer.review.return_value = make_model_output()
    return ManagerReviewService(reviewer=reviewer), reviewer


def _make_draft_with_assignments(
    slide_id: str = "slide-test",
    slide_number: int = 2,
    deck_id=None,
    assignments=None,
    brief_key_message: str = "Digital cost reduction should target top-3 channels.",
) -> SlideContentDraft:
    if assignments is None:
        assignments = [
            make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                            slot_role=SlotRole.TITLE),
            make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                            slot_role=SlotRole.BODY_TEXT,
                            text="Body text here."),
        ]
    return SlideContentDraft(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        brief_key_message=brief_key_message,
        assignments=assignments,
        drafting_summary="Draft summary.",
        is_complete=True,
    )


def _make_slot_map_with_slots(
    slide_id: str = "slide-test",
    slide_number: int = 2,
    deck_id=None,
    slots=None,
) -> TemplateSlotMap:
    if slots is None:
        slots = [
            make_slot(slot_id="slot-001", shape_id=7, shape_path="7",
                      slot_role=SlotRole.TITLE),
            make_slot(slot_id="slot-002", shape_id=8, shape_path="8",
                      slot_role=SlotRole.BODY_TEXT),
        ]
    return TemplateSlotMap(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots,
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Test.",
        slot_analysis_input_fingerprint="fp",
    )


# ---------------------------------------------------------------------------
# Happy path — identity-matched pair
# ---------------------------------------------------------------------------


def test_identity_matched_pair_reviewer_called_once() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=_make_draft_with_assignments(),
        slot_map=_make_slot_map_with_slots(),
    )
    svc.review(req)
    reviewer.review.assert_called_once()


# ---------------------------------------------------------------------------
# slide_id mismatch
# ---------------------------------------------------------------------------


def test_slide_id_mismatch_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=_make_draft_with_assignments(slide_id="slide-AAA"),
        slot_map=_make_slot_map_with_slots(slide_id="slide-BBB"),
    )
    with pytest.raises(ManagerReviewError, match="slide_id"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# deck_id mismatch (when both present)
# ---------------------------------------------------------------------------


def test_deck_id_mismatch_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=_make_draft_with_assignments(deck_id="deck-A"),
        slot_map=_make_slot_map_with_slots(deck_id="deck-B"),
    )
    with pytest.raises(ManagerReviewError, match="deck_id"):
        svc.review(req)
    reviewer.review.assert_not_called()


def test_deck_id_both_none_does_not_raise() -> None:
    """When both deck_ids are None, identity validation skips the deck_id check."""
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=_make_draft_with_assignments(deck_id=None),
        slot_map=_make_slot_map_with_slots(deck_id=None),
    )
    svc.review(req)
    reviewer.review.assert_called_once()


def test_deck_id_one_none_does_not_raise() -> None:
    """When one deck_id is None, validation is skipped — not an error."""
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=_make_draft_with_assignments(deck_id="deck-X"),
        slot_map=_make_slot_map_with_slots(deck_id=None),
    )
    svc.review(req)
    reviewer.review.assert_called_once()


# ---------------------------------------------------------------------------
# slide_number mismatch
# ---------------------------------------------------------------------------


def test_slide_number_mismatch_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=_make_draft_with_assignments(slide_number=3),
        slot_map=_make_slot_map_with_slots(slide_number=7),
    )
    with pytest.raises(ManagerReviewError, match="slide_number"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Missing assignment for slot
# ---------------------------------------------------------------------------


def test_missing_assignment_raises_before_reviewer() -> None:
    """slot-002 has no assignment — must raise, not silently treat as clear."""
    svc, reviewer = _make_service()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                        slot_role=SlotRole.TITLE),
        # slot-002 intentionally omitted
    ]
    draft = SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft.",
        is_complete=True,
    )
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=draft,
        slot_map=_make_slot_map_with_slots(),
    )
    with pytest.raises(ManagerReviewError, match="slot-002"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Extra assignment not in slot map
# ---------------------------------------------------------------------------


def test_extra_assignment_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    # Add a third assignment for a slot not in the map
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                        slot_role=SlotRole.TITLE),
        make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Body text."),
        make_assignment(slot_id="slot-999", shape_id=99, shape_path="99",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Extra assignment."),
    ]
    draft = SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft.",
        is_complete=True,
    )
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=draft,
        slot_map=_make_slot_map_with_slots(),
    )
    with pytest.raises(ManagerReviewError, match="slot-999"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# shape_id mismatch
# ---------------------------------------------------------------------------


def test_shape_id_mismatch_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=999, shape_path="7",
                        slot_role=SlotRole.TITLE),  # wrong shape_id
        make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Body."),
    ]
    draft = SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft.",
        is_complete=True,
    )
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=draft,
        slot_map=_make_slot_map_with_slots(),
    )
    with pytest.raises(ManagerReviewError, match="shape_id"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# shape_path mismatch
# ---------------------------------------------------------------------------


def test_shape_path_mismatch_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=7, shape_path="99/7",
                        slot_role=SlotRole.TITLE),  # wrong shape_path
        make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Body."),
    ]
    draft = SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft.",
        is_complete=True,
    )
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=draft,
        slot_map=_make_slot_map_with_slots(),
    )
    with pytest.raises(ManagerReviewError, match="shape_path"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# slot_role mismatch
# ---------------------------------------------------------------------------


def test_slot_role_mismatch_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                        slot_role=SlotRole.BODY_TEXT),  # wrong role (should be TITLE)
        make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Body."),
    ]
    draft = SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft.",
        is_complete=True,
    )
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=draft,
        slot_map=_make_slot_map_with_slots(),
    )
    with pytest.raises(ManagerReviewError, match="slot_role"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Duplicate assignment
# ---------------------------------------------------------------------------


def test_duplicate_assignment_raises_before_reviewer() -> None:
    svc, reviewer = _make_service()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                        slot_role=SlotRole.TITLE),
        make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                        slot_role=SlotRole.TITLE,
                        text="Duplicate title."),
        make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Body."),
    ]
    draft = SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft.",
        is_complete=True,
    )
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=draft,
        slot_map=_make_slot_map_with_slots(),
    )
    with pytest.raises(ManagerReviewError, match="Duplicate"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# is_complete=False fires before identity check
# ---------------------------------------------------------------------------


def test_incomplete_draft_raises_before_identity_check() -> None:
    """is_complete=False gate fires before identity validation."""
    svc, reviewer = _make_service()
    # Draft only has slot-001 (is_complete=False) — would also fail identity,
    # but the is_complete check should fire first.
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(is_complete=False),
        slot_map=make_slot_map(),
    )
    with pytest.raises(ManagerReviewError, match="is_complete"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# draft.brief_key_message == brief.key_message  (M7 finalization item 1)
# ---------------------------------------------------------------------------


def test_brief_key_message_match_accepted() -> None:
    """Matching brief_key_message: reviewer is called."""
    svc, reviewer = _make_service()
    brief = make_brief(key_message="Digital cost reduction should target top-3 channels.")
    draft = make_complete_draft()  # brief_key_message = same string by default
    req = ManagerReviewRequest(brief=brief, draft=draft, slot_map=make_slot_map())
    svc.review(req)
    reviewer.review.assert_called_once()


def test_brief_key_message_mismatch_raises_before_reviewer() -> None:
    """Mismatched brief_key_message raises ManagerReviewError before reviewer."""
    svc, reviewer = _make_service()
    brief = make_brief(key_message="Different message entirely.")
    draft = make_complete_draft()  # brief_key_message = "Digital cost reduction..."
    req = ManagerReviewRequest(brief=brief, draft=draft, slot_map=make_slot_map())
    with pytest.raises(ManagerReviewError, match="brief_key_message"):
        svc.review(req)
    reviewer.review.assert_not_called()


def test_brief_key_message_mismatch_reviewer_call_count_zero() -> None:
    """Reviewer.review.call_count == 0 when brief_key_message mismatches."""
    svc, reviewer = _make_service()
    brief = make_brief(key_message="A completely different key message.")
    draft = make_complete_draft()
    req = ManagerReviewRequest(brief=brief, draft=draft, slot_map=make_slot_map())
    try:
        svc.review(req)
    except ManagerReviewError:
        pass
    assert reviewer.review.call_count == 0


# ---------------------------------------------------------------------------
# Defensive NEEDS_INPUT gate  (M7 finalization item 2)
# ---------------------------------------------------------------------------


def test_defensive_needs_input_gate_raises_even_when_is_complete_bypassed() -> None:
    """A NEEDS_INPUT assignment in an is_complete=True draft raises ManagerReviewError.

    model_construct() bypasses Pydantic validators — the service must catch this.
    """
    svc, reviewer = _make_service()

    needs_input_assignment = SlotDraftAssignment.model_construct(
        slot_id="slot-001",
        shape_id=7,
        shape_path="7",
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
        missing_information="Missing client name.",
        character_count=0,
        capacity_characters=120,
        capacity_utilization=0.0,
        explicit_line_count=0,
        max_lines_estimate=2,
        group_id=None,
        sequence_index=None,
    )
    good_assignment = SlotDraftAssignment.model_construct(
        slot_id="slot-002",
        shape_id=8,
        shape_path="8",
        slot_role=SlotRole.BODY_TEXT,
        semantic_label="Body",
        action=SlotDraftAction.REPLACE,
        text="Some body content.",
        missing_information=None,
        character_count=18,
        capacity_characters=388,
        capacity_utilization=0.05,
        explicit_line_count=1,
        max_lines_estimate=4,
        group_id=None,
        sequence_index=None,
    )
    # Construct with is_complete=True despite NEEDS_INPUT — bypasses domain validator
    inconsistent_draft = SlideContentDraft.model_construct(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=[needs_input_assignment, good_assignment],
        open_questions=[],
        drafting_summary="Inconsistent draft.",
        is_complete=True,
        schema_version="1.0",
        deck_id=None,
    )
    req = ManagerReviewRequest.model_construct(
        brief=make_brief(),
        draft=inconsistent_draft,
        slot_map=make_slot_map(),
        source_material=None,
    )
    with pytest.raises(ManagerReviewError, match="needs_input"):
        svc.review(req)
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Group member integrity  (M7 finalization item 4)
# ---------------------------------------------------------------------------


def test_group_with_valid_member_slot_ids_accepted() -> None:
    """A group whose member_slot_ids are all in the slot map passes validation."""
    svc, reviewer = _make_service()
    slots = [
        make_slot(slot_id="slot-001", shape_id=7, shape_path="7", slot_role=SlotRole.TITLE),
        make_slot(slot_id="slot-002", shape_id=8, shape_path="8", slot_role=SlotRole.BODY_TEXT),
    ]
    group = SlotGroup(
        group_id="g1",
        group_role="label_content_pair",
        member_slot_ids=["slot-001", "slot-002"],
        sequence_index=0,
        semantic_label="Section 1",
    )
    slot_map = TemplateSlotMap(
        slide_id="slide-test",
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots,
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[group],
        analysis_summary="Test.",
        slot_analysis_input_fingerprint="fp",
    )
    draft = _make_draft_with_assignments()
    req = ManagerReviewRequest(brief=make_brief(), draft=draft, slot_map=slot_map)
    svc.review(req)
    reviewer.review.assert_called_once()


def test_group_with_unknown_member_slot_id_raises_before_reviewer() -> None:
    """A group whose member_slot_id is not in the slot map raises ManagerReviewError."""
    svc, reviewer = _make_service()
    slots = [
        make_slot(slot_id="slot-001", shape_id=7, shape_path="7", slot_role=SlotRole.TITLE),
        make_slot(slot_id="slot-002", shape_id=8, shape_path="8", slot_role=SlotRole.BODY_TEXT),
    ]
    group = SlotGroup(
        group_id="g1",
        group_role="label_content_pair",
        member_slot_ids=["slot-001", "slot-UNKNOWN"],  # slot-UNKNOWN not in slot map
        sequence_index=0,
        semantic_label="Section 1",
    )
    slot_map = TemplateSlotMap(
        slide_id="slide-test",
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots,
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[group],
        analysis_summary="Test.",
        slot_analysis_input_fingerprint="fp",
    )
    draft = _make_draft_with_assignments()
    req = ManagerReviewRequest(brief=make_brief(), draft=draft, slot_map=slot_map)
    with pytest.raises(ManagerReviewError, match="slot-UNKNOWN"):
        svc.review(req)
    reviewer.review.assert_not_called()
