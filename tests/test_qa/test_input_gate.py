"""Input gate tests for VisualQAService (M8)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.qa.errors import VisualQAError
from slidestein.qa.models import VisualQARequest
from slidestein.qa.service import VisualQAService
from slidestein.slots.roles import SlotRole
from tests.test_qa.conftest import (
    make_assignment,
    make_complete_draft,
    make_native_check,
    make_slot,
    make_slot_map,
    make_visual_model_output,
)


def _make_service(reviewer=None, renderer=None, overlay_builder=None, native_inspector=None):
    if reviewer is None:
        reviewer = MagicMock()
        reviewer.review.return_value = make_visual_model_output()
    if renderer is None:
        renderer = MagicMock()
    if overlay_builder is None:
        overlay_builder = MagicMock()
    if native_inspector is None:
        inspector = MagicMock()
        inspector.inspect.return_value = [make_native_check()]
        native_inspector = inspector
    return VisualQAService(
        reviewer=reviewer,
        renderer=renderer,
        overlay_builder=overlay_builder,
        native_inspector=native_inspector,
    )


def _make_request(draft=None, slot_map=None, tmp_path=None):
    if draft is None:
        draft = make_complete_draft()
    if slot_map is None:
        slot_map = make_slot_map()
    if tmp_path is None:
        tmp_path = Path("/tmp/test")
    return VisualQARequest(
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
        draft=draft,
        slot_map=slot_map,
    )


# ---------------------------------------------------------------------------
# Completeness gate
# ---------------------------------------------------------------------------


def test_incomplete_draft_raises_before_any_call(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    draft = make_complete_draft(is_complete=False)
    # Build a complete-looking 1-slot draft with NEEDS_INPUT
    assignments = [
        SlotDraftAssignment(
            slot_id="slot-001",
            shape_id=21,
            shape_path="21",
            slot_role=SlotRole.TITLE,
            semantic_label="Title",
            action=SlotDraftAction.NEEDS_INPUT,
            text=None,
            missing_information="Need client.",
            capacity_characters=100,
            capacity_utilization=0.0,
            max_lines_estimate=2,
        )
    ]
    draft_incomplete = SlideContentDraft(
        slide_id="slide-test-001",
        slide_number=2,
        brief_key_message="msg",
        assignments=assignments,
        drafting_summary="s",
        is_complete=False,
    )

    request = _make_request(draft=draft_incomplete, tmp_path=tmp_path)

    with pytest.raises(VisualQAError, match="is_complete"):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


def test_needs_input_assignment_raises_even_with_is_complete_bypassed(tmp_path):
    """model_construct() can bypass domain invariant; defensive gate catches it."""
    from pydantic import BaseModel
    from slidestein.qa.models import VisualQARequest as VQAReq

    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot = make_slot()
    slot_map = make_slot_map()

    needs_input_assignment = SlotDraftAssignment.model_construct(
        slot_id="slot-001",
        shape_id=21,
        shape_path="21",
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
        capacity_characters=100,
        capacity_utilization=0.0,
        max_lines_estimate=2,
    )
    # Bypass domain invariant on draft
    draft_bypassed = SlideContentDraft.model_construct(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        brief_key_message="msg",
        assignments=[needs_input_assignment, make_assignment(slot_id="slot-002", shape_id=22, shape_path="22", slot_role=SlotRole.BODY_TEXT)],
        drafting_summary="s",
        is_complete=True,  # bypassed — inconsistent
    )
    request = VQAReq.model_construct(
        template_pptx=tmp_path / "t.pptx",
        generated_pptx=tmp_path / "g.pptx",
        draft=draft_bypassed,
        slot_map=slot_map,
    )

    with pytest.raises(VisualQAError, match="needs_input"):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Identity gate
# ---------------------------------------------------------------------------


def test_slide_id_mismatch_raises_before_provider(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot_map = make_slot_map(slide_id="slide-A")
    draft = make_complete_draft(slide_id="slide-B")
    request = _make_request(draft=draft, slot_map=slot_map, tmp_path=tmp_path)

    with pytest.raises(VisualQAError, match="slide_id"):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


def test_slide_number_mismatch_raises_before_provider(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot_map = make_slot_map(slide_number=2)
    draft = make_complete_draft(slide_number=5)
    request = _make_request(draft=draft, slot_map=slot_map, tmp_path=tmp_path)

    with pytest.raises(VisualQAError, match="slide_number"):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


def test_shape_id_mismatch_raises_before_provider(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot_map = make_slot_map()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=999, shape_path="21",
                        slot_role=SlotRole.TITLE),  # wrong shape_id
        make_assignment(slot_id="slot-002", shape_id=22, shape_path="22",
                        slot_role=SlotRole.BODY_TEXT),
    ]
    draft = make_complete_draft(assignments=assignments)
    request = _make_request(draft=draft, slot_map=slot_map, tmp_path=tmp_path)

    with pytest.raises(VisualQAError, match="shape_id"):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


def test_missing_assignment_raises_before_provider(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot_map = make_slot_map()
    # Only provide one assignment for a two-slot slot map
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=21, shape_path="21",
                        slot_role=SlotRole.TITLE),
    ]
    draft = SlideContentDraft.model_construct(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        brief_key_message="msg",
        assignments=assignments,
        drafting_summary="s",
        is_complete=True,
    )
    request = _make_request(draft=draft, slot_map=slot_map, tmp_path=tmp_path)

    with pytest.raises(VisualQAError):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


def test_unknown_slot_id_in_assignment_raises_before_provider(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot_map = make_slot_map()
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=21, shape_path="21",
                        slot_role=SlotRole.TITLE),
        make_assignment(slot_id="slot-002", shape_id=22, shape_path="22",
                        slot_role=SlotRole.BODY_TEXT),
        make_assignment(slot_id="slot-UNKNOWN", shape_id=99, shape_path="99",
                        slot_role=SlotRole.BODY_TEXT),
    ]
    draft = SlideContentDraft.model_construct(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        brief_key_message="msg",
        assignments=assignments,
        drafting_summary="s",
        is_complete=True,
    )
    request = _make_request(draft=draft, slot_map=slot_map, tmp_path=tmp_path)

    with pytest.raises(VisualQAError, match="slot-UNKNOWN"):
        service.review(request, tmp_path / "artifacts")

    reviewer.review.assert_not_called()


def test_complete_consistent_input_reaches_provider(tmp_path, monkeypatch):
    """A fully consistent request reaches the Vision reviewer."""
    reviewer = MagicMock()
    reviewer.review.return_value = make_visual_model_output()
    renderer = MagicMock()
    overlay_builder = MagicMock()
    native_inspector = MagicMock()
    native_inspector.inspect.return_value = [make_native_check()]

    service = VisualQAService(
        reviewer=reviewer,
        renderer=renderer,
        overlay_builder=overlay_builder,
        native_inspector=native_inspector,
    )

    # Patch out stable slide resolution so we don't need real PPTXs
    monkeypatch.setattr(
        "slidestein.qa.service.resolve_slide_by_stable_id",
        lambda pptx, deck_id, slide_id: (2, 256),
    )

    # Patch out IO that requires real PPTX files (step 5b and 5c)
    default_live_geos = {
        "K1": {"x_ratio": 0.04, "y_ratio": 0.07, "width_ratio": 0.88, "height_ratio": 0.09},
        "K2": {"x_ratio": 0.04, "y_ratio": 0.25, "width_ratio": 0.88, "height_ratio": 0.09},
    }
    default_text_map = {
        "21": "Digital transformation drives efficiency.",
        "22": "Channel 1, Channel 2, Channel 3.",
    }

    monkeypatch.setattr(
        "slidestein.qa.service.read_live_slot_geometries",
        lambda pptx, slide_num, key_map: default_live_geos,
    )
    monkeypatch.setattr(
        "slidestein.qa.service.read_shape_text",
        lambda pptx, slide_num, path: default_text_map.get(path),
    )
    monkeypatch.setattr(
        "slidestein.qa.service.normalize_readback",
        lambda x: x,
    )

    slot_map = make_slot_map()
    draft = make_complete_draft()

    request = VisualQARequest(
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
        draft=draft,
        slot_map=slot_map,
    )

    artifacts_dir = tmp_path / "artifacts"
    service.review(request, artifacts_dir)

    reviewer.review.assert_called_once()
