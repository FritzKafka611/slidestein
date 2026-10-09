"""Tests for writeback/models.py — PowerPointWritebackRequest validators."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole
from slidestein.writeback.models import (
    PowerPointWritebackRequest,
    PowerPointWritebackResult,
    WritebackOperation,
    WritebackPlan,
    WritebackReceipt,
)
from slidestein.writeback.versions import WRITEBACK_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLOT_ID = "slot-title"
_SLIDE_ID = "slide-001"
_SLIDE_NUMBER = 2


def _make_slot(
    slot_id: str = _SLOT_ID,
    shape_id: int = 7,
    shape_path: str = "7",
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        editable=True,
        confidence=0.9,
        current_text="Placeholder title",
        geometry={"x_ratio": 0.05, "y_ratio": 0.04, "width_ratio": 0.9, "height_ratio": 0.1},
        capacity=SlotCapacity(
            max_characters_estimate=120,
            max_lines_estimate=2,
            current_character_count=17,
            current_line_count=1,
            relative_capacity="medium",
        ),
    )


def _make_slot_map(
    slide_id: str = _SLIDE_ID,
    slide_number: int = _SLIDE_NUMBER,
    deck_id: str | None = "deck-abc",
    slots: list[TemplateSlot] | None = None,
) -> TemplateSlotMap:
    if slots is None:
        slots = [_make_slot()]
    return TemplateSlotMap(
        slide_id=slide_id,
        slide_number=slide_number,
        deck_id=deck_id,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots,
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Test slot map.",
        slot_analysis_input_fingerprint="fp-test",
    )


def _make_assignment(
    slot_id: str = _SLOT_ID,
    shape_id: int = 7,
    shape_path: str = "7",
    action: SlotDraftAction = SlotDraftAction.REPLACE,
    text: str | None = "Draft title",
) -> SlotDraftAssignment:
    return SlotDraftAssignment(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        action=action,
        text=text,
        capacity_characters=120,
        capacity_utilization=0.1,
        max_lines_estimate=2,
    )


def _make_draft(
    slide_id: str = _SLIDE_ID,
    slide_number: int = _SLIDE_NUMBER,
    deck_id: str | None = "deck-abc",
    assignments: list[SlotDraftAssignment] | None = None,
    is_complete: bool = True,
) -> SlideContentDraft:
    if assignments is None:
        assignments = [_make_assignment()]
    return SlideContentDraft(
        slide_id=slide_id,
        slide_number=slide_number,
        deck_id=deck_id,
        brief_key_message="Key message for testing.",
        assignments=assignments,
        drafting_summary="Test draft.",
        is_complete=is_complete,
    )


def _make_request(
    source_pptx: Path = Path("/data/source.pptx"),
    output_pptx: Path = Path("/data/output.pptx"),
    overwrite: bool = False,
) -> PowerPointWritebackRequest:
    return PowerPointWritebackRequest(
        draft=_make_draft(),
        slot_map=_make_slot_map(),
        source_pptx=source_pptx,
        output_pptx=output_pptx,
        overwrite=overwrite,
    )


# ---------------------------------------------------------------------------
# PowerPointWritebackRequest — output path safety
# ---------------------------------------------------------------------------


def test_request_source_and_output_differ() -> None:
    req = _make_request(
        source_pptx=Path("/data/source.pptx"),
        output_pptx=Path("/data/output.pptx"),
    )
    assert req.source_pptx != req.output_pptx


def test_request_same_source_and_output_rejected(tmp_path: Path) -> None:
    same = tmp_path / "deck.pptx"
    same.touch()
    with pytest.raises(ValidationError, match="must be different"):
        _make_request(source_pptx=same, output_pptx=same)


def test_request_overwrite_default_false() -> None:
    req = _make_request()
    assert req.overwrite is False


def test_request_overwrite_true_accepted() -> None:
    req = _make_request(
        source_pptx=Path("/data/source.pptx"),
        output_pptx=Path("/data/output.pptx"),
        overwrite=True,
    )
    assert req.overwrite is True


def test_request_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        PowerPointWritebackRequest(  # type: ignore[call-arg]
            draft=_make_draft(),
            slot_map=_make_slot_map(),
            source_pptx=Path("/data/source.pptx"),
            output_pptx=Path("/data/output.pptx"),
            unknown_field="x",
        )


# ---------------------------------------------------------------------------
# WritebackOperation dataclass
# ---------------------------------------------------------------------------


def test_writeback_operation_fields() -> None:
    op = WritebackOperation(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        action=SlotDraftAction.REPLACE,
        text="hello",
    )
    assert op.slot_id == "s1"
    assert op.shape_id == 7
    assert op.shape_path == "7"
    assert op.action == SlotDraftAction.REPLACE
    assert op.text == "hello"


def test_writeback_operation_clear_text_none() -> None:
    op = WritebackOperation(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        action=SlotDraftAction.CLEAR,
        text=None,
    )
    assert op.text is None


# ---------------------------------------------------------------------------
# WritebackPlan dataclass
# ---------------------------------------------------------------------------


def test_writeback_plan_fields() -> None:
    op = WritebackOperation(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        action=SlotDraftAction.REPLACE,
        text="hello",
    )
    plan = WritebackPlan(
        schema_version=WRITEBACK_SCHEMA_VERSION,
        slide_id="slide-001",
        deck_id="deck-abc",
        slide_number=2,
        resolved_slide_number=2,
        native_slide_id=256,
        source_pptx=Path("/data/source.pptx"),
        output_pptx=Path("/data/output.pptx"),
        operations=[op],
        replacement_count=1,
        clear_count=0,
        before_structure_fingerprint="abcdef01",
    )
    assert plan.schema_version == WRITEBACK_SCHEMA_VERSION
    assert plan.slide_id == "slide-001"
    assert plan.replacement_count == 1
    assert plan.clear_count == 0
    assert plan.before_structure_fingerprint == "abcdef01"
    assert plan.resolved_slide_number == 2
    assert plan.native_slide_id == 256


def test_writeback_plan_format_fp_default() -> None:
    op = WritebackOperation(
        slot_id="s1", shape_id=7, shape_path="7",
        action=SlotDraftAction.REPLACE, text="hello",
    )
    plan = WritebackPlan(
        schema_version=WRITEBACK_SCHEMA_VERSION, slide_id="slide-001",
        deck_id=None, slide_number=2, resolved_slide_number=2, native_slide_id=None,
        source_pptx=Path("/data/source.pptx"), output_pptx=Path("/data/output.pptx"),
        operations=[op], replacement_count=1, clear_count=0,
        before_structure_fingerprint="fp",
    )
    assert plan.before_format_fingerprint == ""
    assert plan.before_deck_native_ids == []
    assert plan.before_deck_structure == {}


# ---------------------------------------------------------------------------
# WritebackReceipt dataclass
# ---------------------------------------------------------------------------


def test_writeback_receipt_verified_true() -> None:
    r = WritebackReceipt(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        action="replace",
        expected_text="hello",
        verified_text="hello",
        verified=True,
    )
    assert r.verified is True


def test_writeback_receipt_verified_false() -> None:
    r = WritebackReceipt(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        action="replace",
        expected_text="hello",
        verified_text="wrong",
        verified=False,
    )
    assert r.verified is False


# ---------------------------------------------------------------------------
# PowerPointWritebackResult
# ---------------------------------------------------------------------------


def test_result_schema_version_default() -> None:
    result = PowerPointWritebackResult(
        source_pptx="/data/source.pptx",
        output_pptx="/data/output.pptx",
        slide_id="slide-001",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=1,
        clear_count=0,
        applied_assignments=[],
        verification_passed=True,
    )
    assert result.schema_version == WRITEBACK_SCHEMA_VERSION


def test_result_warnings_default_empty() -> None:
    result = PowerPointWritebackResult(
        source_pptx="/data/source.pptx",
        output_pptx="/data/output.pptx",
        slide_id="slide-001",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=1,
        clear_count=0,
        applied_assignments=[],
        verification_passed=True,
    )
    assert result.warnings == []


def test_result_new_verification_fields_default_true() -> None:
    result = PowerPointWritebackResult(
        source_pptx="/data/source.pptx",
        output_pptx="/data/output.pptx",
        slide_id="slide-001",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=1,
        clear_count=0,
        applied_assignments=[],
        verification_passed=True,
    )
    assert result.source_currentness_verified is True
    assert result.target_structure_verified is True
    assert result.non_target_structure_verified is True
    assert result.native_slide_id is None


def test_result_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        PowerPointWritebackResult(  # type: ignore[call-arg]
            source_pptx="/data/source.pptx",
            output_pptx="/data/output.pptx",
            slide_id="slide-001",
            slide_number=2,
            resolved_slide_number=2,
            replacement_count=1,
            clear_count=0,
            applied_assignments=[],
            verification_passed=True,
            unknown_field="x",
        )


def test_result_serialises_to_json() -> None:
    import json

    result = PowerPointWritebackResult(
        source_pptx="/data/source.pptx",
        output_pptx="/data/output.pptx",
        slide_id="slide-001",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=3,
        clear_count=1,
        applied_assignments=[{"slot_id": "s1", "verified": True}],
        verification_passed=True,
        before_structure_fingerprint="aabbccdd",
        after_structure_fingerprint="aabbccdd",
    )
    data = json.loads(result.model_dump_json())
    assert data["schema_version"] == WRITEBACK_SCHEMA_VERSION
    assert data["replacement_count"] == 3
    assert data["before_structure_fingerprint"] == "aabbccdd"
    assert data["verification_passed"] is True
