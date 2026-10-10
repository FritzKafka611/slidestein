"""Shared fixtures for test_qa."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.qa.models import (
    NativeCheckStatus,
    NativeCheckType,
    NativeVisualCheck,
    VisualDimensionAssessment,
    VisualQAIssue,
    VisualQAModelOutput,
    VisualQARequest,
)
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Slot helpers
# ---------------------------------------------------------------------------


def make_slot(
    slot_id: str = "slot-001",
    shape_id: int = 21,
    shape_path: str = "21",
    slot_role: SlotRole = SlotRole.TITLE,
    semantic_label: str = "Title",
    y_ratio: float = 0.07,
    x_ratio: float = 0.04,
    width_ratio: float = 0.88,
    height_ratio: float = 0.09,
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        editable=True,
        confidence=0.95,
        current_text="Placeholder title",
        geometry={
            "x": int(x_ratio * 12195175),
            "y": int(y_ratio * 6858000),
            "width": int(width_ratio * 12195175),
            "height": int(height_ratio * 6858000),
            "x_ratio": x_ratio,
            "y_ratio": y_ratio,
            "width_ratio": width_ratio,
            "height_ratio": height_ratio,
        },
        capacity=SlotCapacity(
            max_characters_estimate=100,
            max_lines_estimate=2,
            current_character_count=18,
            current_line_count=1,
            relative_capacity="medium",
        ),
    )


def make_slot_map(
    slide_id: str = "slide-test-001",
    deck_id: Optional[str] = "deck-abc123",
    slide_number: int = 2,
    slots: Optional[list[TemplateSlot]] = None,
) -> TemplateSlotMap:
    if slots is None:
        slots = [
            make_slot(slot_id="slot-001", shape_id=21, shape_path="21",
                      slot_role=SlotRole.TITLE, semantic_label="Title",
                      y_ratio=0.07, x_ratio=0.04),
            make_slot(slot_id="slot-002", shape_id=22, shape_path="22",
                      slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
                      y_ratio=0.25, x_ratio=0.04),
        ]
    return TemplateSlotMap(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        slide_width=12195175,
        slide_height=6858000,
        slots=slots,
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Test slot map.",
        slot_analysis_input_fingerprint="fp-test",
    )


# ---------------------------------------------------------------------------
# Assignment helpers
# ---------------------------------------------------------------------------


def make_assignment(
    slot_id: str = "slot-001",
    shape_id: int = 21,
    shape_path: str = "21",
    slot_role: SlotRole = SlotRole.TITLE,
    semantic_label: str = "Title",
    action: SlotDraftAction = SlotDraftAction.REPLACE,
    text: Optional[str] = "Digital transformation drives efficiency.",
) -> SlotDraftAssignment:
    return SlotDraftAssignment(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        action=action,
        text=text,
        capacity_characters=100,
        capacity_utilization=0.35,
        max_lines_estimate=2,
    )


def make_complete_draft(
    slide_id: str = "slide-test-001",
    deck_id: Optional[str] = "deck-abc123",
    slide_number: int = 2,
    assignments: Optional[list[SlotDraftAssignment]] = None,
    is_complete: bool = True,
) -> SlideContentDraft:
    if assignments is None:
        if is_complete:
            assignments = [
                make_assignment(slot_id="slot-001", shape_id=21, shape_path="21",
                                slot_role=SlotRole.TITLE, semantic_label="Title"),
                make_assignment(slot_id="slot-002", shape_id=22, shape_path="22",
                                slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
                                text="Channel 1, Channel 2, Channel 3."),
            ]
        else:
            assignments = [
                SlotDraftAssignment(
                    slot_id="slot-001",
                    shape_id=21,
                    shape_path="21",
                    slot_role=SlotRole.TITLE,
                    semantic_label="Title",
                    action=SlotDraftAction.NEEDS_INPUT,
                    text=None,
                    missing_information="Need client name.",
                    capacity_characters=100,
                    capacity_utilization=0.0,
                    max_lines_estimate=2,
                )
            ]
    return SlideContentDraft(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        brief_key_message="Digital transformation drives efficiency.",
        assignments=assignments,
        drafting_summary="Test draft.",
        is_complete=is_complete,
    )


# ---------------------------------------------------------------------------
# Model output helper
# ---------------------------------------------------------------------------


def make_visual_model_output(
    recommendation: str = "pass",
    scores: Optional[dict[str, int]] = None,
    issues: Optional[list[VisualQAIssue]] = None,
    executive_summary: str = "The slide renders cleanly and is presentation-ready.",
) -> VisualQAModelOutput:
    if scores is None:
        scores = {
            "text_fit_and_clipping": 5,
            "visual_hierarchy": 4,
            "alignment_and_spacing": 4,
            "balance_and_whitespace": 4,
            "typography_and_style_consistency": 4,
            "overall_readability": 4,
        }
    return VisualQAModelOutput(
        recommendation=recommendation,  # type: ignore[arg-type]
        text_fit_and_clipping=VisualDimensionAssessment(score=scores["text_fit_and_clipping"], rationale="Clean."),
        visual_hierarchy=VisualDimensionAssessment(score=scores["visual_hierarchy"], rationale="Clear hierarchy."),
        alignment_and_spacing=VisualDimensionAssessment(score=scores["alignment_and_spacing"], rationale="Well aligned."),
        balance_and_whitespace=VisualDimensionAssessment(score=scores["balance_and_whitespace"], rationale="Good balance."),
        typography_and_style_consistency=VisualDimensionAssessment(score=scores["typography_and_style_consistency"], rationale="Consistent."),
        overall_readability=VisualDimensionAssessment(score=scores["overall_readability"], rationale="Readable."),
        issues=issues or [],
        executive_summary=executive_summary,
    )


# ---------------------------------------------------------------------------
# Native check helpers
# ---------------------------------------------------------------------------


def make_native_check(
    check_type: NativeCheckType = NativeCheckType.OUTSIDE_SLIDE_BOUNDS,
    slot_key: Optional[str] = "K1",
    status: NativeCheckStatus = NativeCheckStatus.PASS,
    details: str = "Within bounds.",
) -> NativeVisualCheck:
    return NativeVisualCheck(
        check_type=check_type,
        slot_key=slot_key,
        status=status,
        details=details,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def slot_map() -> TemplateSlotMap:
    return make_slot_map()


@pytest.fixture
def complete_draft() -> SlideContentDraft:
    return make_complete_draft()


@pytest.fixture
def mock_reviewer() -> MagicMock:
    reviewer = MagicMock()
    reviewer.review.return_value = make_visual_model_output()
    return reviewer


@pytest.fixture
def mock_renderer() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_overlay_builder() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_native_inspector() -> MagicMock:
    inspector = MagicMock()
    inspector.inspect.return_value = [make_native_check()]
    return inspector
