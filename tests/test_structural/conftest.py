"""Shared fixtures for test_structural."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.domain.models import CommunicationJob, SlideFunction
from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.qa.models import (
    VisualDimensionAssessment,
    VisualQAIssue,
    VisualQAResult,
)
from slidestein.review.models import (
    DimensionAssessment,
    ManagerReviewResult,
)
from slidestein.revision.models import RevisionPlan, RevisionRoute
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole
from slidestein.structural.models import StructuralRecoveryRequest


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


def make_brief(
    key_message: str = "Digital transformation drives efficiency.",
) -> ConsultingSlideBrief:
    return ConsultingSlideBrief(
        original_request="Create a digital transformation summary slide.",
        key_message=key_message,
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SUMMARISE,
    )


# ---------------------------------------------------------------------------
# Slot / slot_map
# ---------------------------------------------------------------------------


def make_slot(
    slot_id: str = "slot-001",
    shape_id: int = 21,
    shape_path: str = "21",
    slot_role: SlotRole = SlotRole.TITLE,
    semantic_label: str = "Title",
    y_ratio: float = 0.07,
    x_ratio: float = 0.04,
    x_emu: int = 457200,
    y_emu: int = 457200,
    w_emu: int = 10972800,
    h_emu: int = 685800,
    max_chars: int = 100,
    max_lines: int = 2,
    editable: bool = True,
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        editable=editable,
        confidence=0.95,
        current_text="Placeholder text",
        geometry={
            "x": x_emu,
            "y": y_emu,
            "width": w_emu,
            "height": h_emu,
            "x_ratio": x_ratio,
            "y_ratio": y_ratio,
            "width_ratio": 0.88,
            "height_ratio": 0.09,
        },
        capacity=SlotCapacity(
            max_characters_estimate=max_chars,
            max_lines_estimate=max_lines,
            current_character_count=18,
            current_line_count=1,
            relative_capacity="medium",
        ),
    )


def make_slot_map(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    slots: Optional[list[TemplateSlot]] = None,
) -> TemplateSlotMap:
    if slots is None:
        slots = [
            make_slot(
                slot_id="slot-001", shape_id=21, shape_path="21",
                slot_role=SlotRole.TITLE, semantic_label="Title",
                x_emu=457200, y_emu=457200, w_emu=10972800, h_emu=685800,
                y_ratio=0.07, x_ratio=0.04,
            ),
            make_slot(
                slot_id="slot-002", shape_id=22, shape_path="22",
                slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
                x_emu=457200, y_emu=1143000, w_emu=10972800, h_emu=4572000,
                y_ratio=0.25, x_ratio=0.04, max_chars=300, max_lines=6,
            ),
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
# Draft
# ---------------------------------------------------------------------------


def make_assignment(
    slot_id: str,
    shape_id: int,
    shape_path: str,
    slot_role: SlotRole,
    semantic_label: str,
    text: str = "Sample text content.",
    max_chars: int = 100,
    max_lines: int = 2,
    action: SlotDraftAction = SlotDraftAction.REPLACE,
) -> SlotDraftAssignment:
    char_count = len(text) if action == SlotDraftAction.REPLACE else 0
    utilization = round(char_count / max_chars, 4) if max_chars > 0 else 0.0
    return SlotDraftAssignment(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        action=action,
        text=text if action == SlotDraftAction.REPLACE else None,
        capacity_characters=max_chars,
        capacity_utilization=utilization,
        max_lines_estimate=max_lines,
    )


def make_complete_draft(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    brief_key_message: str = "Digital transformation drives efficiency.",
) -> SlideContentDraft:
    return SlideContentDraft(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        brief_key_message=brief_key_message,
        assignments=[
            make_assignment(
                "slot-001", 21, "21", SlotRole.TITLE, "Title",
                text="Digital Transformation Drives Efficiency",
            ),
            make_assignment(
                "slot-002", 22, "22", SlotRole.BODY_TEXT, "Body",
                text="Channel 1, Channel 2, Channel 3.",
                max_chars=300, max_lines=6,
            ),
        ],
        drafting_summary="Test draft.",
        is_complete=True,
    )


# ---------------------------------------------------------------------------
# ManagerReviewResult
# ---------------------------------------------------------------------------

_DEFAULT_DIM = DimensionAssessment(score=4, rationale="Adequate.")


def make_manager_review(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    recommendation: str = "approve",
) -> ManagerReviewResult:
    return ManagerReviewResult(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        recommendation=recommendation,  # type: ignore[arg-type]
        average_score=4.0,
        answer_first_title=_DEFAULT_DIM,
        core_message_clarity=_DEFAULT_DIM,
        vertical_logic=_DEFAULT_DIM,
        exhibit_title_consistency=_DEFAULT_DIM,
        mece_structure=_DEFAULT_DIM,
        content_density=_DEFAULT_DIM,
        executive_summary="The slide effectively addresses the brief.",
    )


# ---------------------------------------------------------------------------
# VisualQAResult
# ---------------------------------------------------------------------------

_DEFAULT_VISUAL_DIM = VisualDimensionAssessment(score=4, rationale="Good.")


def make_visual_qa(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    recommendation: str = "pass",
    issues: Optional[list[VisualQAIssue]] = None,
) -> VisualQAResult:
    return VisualQAResult(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        resolved_generated_slide_number=slide_number,
        recommendation=recommendation,  # type: ignore[arg-type]
        text_fit_and_clipping=_DEFAULT_VISUAL_DIM,
        visual_hierarchy=_DEFAULT_VISUAL_DIM,
        alignment_and_spacing=_DEFAULT_VISUAL_DIM,
        balance_and_whitespace=VisualDimensionAssessment(score=2, rationale="Poor."),
        typography_and_style_consistency=_DEFAULT_VISUAL_DIM,
        overall_readability=_DEFAULT_VISUAL_DIM,
        average_score=3.5,
        issues=issues or [],
        executive_summary="Visual QA complete.",
        generated_render_path="outputs/m10/generated.png",
        template_render_path="outputs/m10/template.png",
        overlay_render_path="outputs/m10/overlay.png",
    )


# ---------------------------------------------------------------------------
# RevisionPlan
# ---------------------------------------------------------------------------


def make_m9_plan(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    route: RevisionRoute = RevisionRoute.TEMPLATE_RESELECTION,
) -> RevisionPlan:
    return RevisionPlan(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        route=route,
        reasons=["Material balance_and_whitespace issue."],
        requires_model_call=(route != RevisionRoute.FINALIZE),
    )


# ---------------------------------------------------------------------------
# StructuralRecoveryRequest
# ---------------------------------------------------------------------------


def make_recovery_request(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    template_pptx: Optional[Path] = None,
    generated_pptx: Optional[Path] = None,
    output_pptx: Optional[Path] = None,
    m9_route: RevisionRoute = RevisionRoute.TEMPLATE_RESELECTION,
    vqa_issues: Optional[list[VisualQAIssue]] = None,
) -> StructuralRecoveryRequest:
    return StructuralRecoveryRequest(
        brief=make_brief(),
        source_material="Source material for testing.",
        current_draft=make_complete_draft(
            slide_id=slide_id, deck_id=deck_id, slide_number=slide_number
        ),
        current_slot_map=make_slot_map(
            slide_id=slide_id, deck_id=deck_id, slide_number=slide_number
        ),
        manager_review=make_manager_review(
            slide_id=slide_id, deck_id=deck_id, slide_number=slide_number
        ),
        visual_qa=make_visual_qa(
            slide_id=slide_id, deck_id=deck_id, slide_number=slide_number,
            issues=vqa_issues,
        ),
        m9_plan=make_m9_plan(
            slide_id=slide_id, deck_id=deck_id, slide_number=slide_number,
            route=m9_route,
        ),
        template_pptx=template_pptx or Path("data/test_decks/template.pptx"),
        generated_pptx=generated_pptx or Path("data/test_decks/generated.pptx"),
        output_pptx=output_pptx,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def brief():
    return make_brief()


@pytest.fixture
def slot_map():
    return make_slot_map()


@pytest.fixture
def complete_draft():
    return make_complete_draft()


@pytest.fixture
def manager_approve():
    return make_manager_review(recommendation="approve")


@pytest.fixture
def visual_pass():
    return make_visual_qa(recommendation="pass")


@pytest.fixture
def m9_plan_reselect():
    return make_m9_plan(route=RevisionRoute.TEMPLATE_RESELECTION)


@pytest.fixture
def recovery_request():
    return make_recovery_request()
