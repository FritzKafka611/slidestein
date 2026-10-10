"""Shared fixtures for test_revision."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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
    ManagerReviewIssue,
    ManagerReviewResult,
)
from slidestein.revision.models import RevisionRequest
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Brief helpers
# ---------------------------------------------------------------------------


def make_brief(
    original_request: str = "Create a digital transformation summary slide.",
    key_message: str = "Digital transformation drives efficiency.",
) -> ConsultingSlideBrief:
    return ConsultingSlideBrief(
        original_request=original_request,
        key_message=key_message,
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SUMMARISE,
    )


# ---------------------------------------------------------------------------
# Slot + slot_map helpers
# ---------------------------------------------------------------------------


def make_slot(
    slot_id: str = "slot-001",
    shape_id: int = 21,
    shape_path: str = "21",
    slot_role: SlotRole = SlotRole.TITLE,
    semantic_label: str = "Title",
    y_ratio: float = 0.07,
    x_ratio: float = 0.04,
    max_chars: int = 100,
    max_lines: int = 2,
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        editable=True,
        confidence=0.95,
        current_text="Placeholder text",
        geometry={
            "x": int(x_ratio * 12195175),
            "y": int(y_ratio * 6858000),
            "width": int(0.88 * 12195175),
            "height": int(0.09 * 6858000),
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
            make_slot(slot_id="slot-001", shape_id=21, shape_path="21",
                      slot_role=SlotRole.TITLE, semantic_label="Title",
                      y_ratio=0.07, x_ratio=0.04, max_chars=100, max_lines=2),
            make_slot(slot_id="slot-002", shape_id=22, shape_path="22",
                      slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
                      y_ratio=0.25, x_ratio=0.04, max_chars=300, max_lines=6),
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
# Draft helpers
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
    assignments = [
        make_assignment(
            slot_id="slot-001", shape_id=21, shape_path="21",
            slot_role=SlotRole.TITLE, semantic_label="Title",
            text="Digital Transformation Drives Efficiency",
            max_chars=100, max_lines=2,
        ),
        make_assignment(
            slot_id="slot-002", shape_id=22, shape_path="22",
            slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
            text="Channel 1, Channel 2, Channel 3.",
            max_chars=300, max_lines=6,
        ),
    ]
    return SlideContentDraft(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        brief_key_message=brief_key_message,
        assignments=assignments,
        drafting_summary="Test draft.",
        is_complete=True,
    )


# ---------------------------------------------------------------------------
# ManagerReviewResult helpers
# ---------------------------------------------------------------------------

_DEFAULT_DIMENSION = DimensionAssessment(score=4, rationale="Adequate.")


def make_manager_review(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    recommendation: str = "approve",
    issues: Optional[list[ManagerReviewIssue]] = None,
    factual_flags: Optional[list[ManagerReviewIssue]] = None,
) -> ManagerReviewResult:
    return ManagerReviewResult(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        recommendation=recommendation,  # type: ignore[arg-type]
        average_score=4.0,
        answer_first_title=_DEFAULT_DIMENSION,
        core_message_clarity=_DEFAULT_DIMENSION,
        vertical_logic=_DEFAULT_DIMENSION,
        exhibit_title_consistency=_DEFAULT_DIMENSION,
        mece_structure=_DEFAULT_DIMENSION,
        content_density=_DEFAULT_DIMENSION,
        issues=issues or [],
        factual_flags=factual_flags or [],
        executive_summary="The slide effectively addresses the brief.",
    )


# ---------------------------------------------------------------------------
# VisualQAResult helpers
# ---------------------------------------------------------------------------

_DEFAULT_VISUAL_DIM = VisualDimensionAssessment(score=4, rationale="Good.")


def make_visual_qa(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    slide_number: int = 2,
    recommendation: str = "pass",
    issues: Optional[list[VisualQAIssue]] = None,
    text_fit_score: int = 4,
    visual_hierarchy_score: int = 4,
    alignment_score: int = 4,
    balance_score: int = 4,
    typography_score: int = 4,
    readability_score: int = 4,
) -> VisualQAResult:
    return VisualQAResult(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        resolved_generated_slide_number=slide_number,
        recommendation=recommendation,  # type: ignore[arg-type]
        text_fit_and_clipping=VisualDimensionAssessment(score=text_fit_score, rationale="Fits."),
        visual_hierarchy=VisualDimensionAssessment(score=visual_hierarchy_score, rationale="Clear."),
        alignment_and_spacing=VisualDimensionAssessment(score=alignment_score, rationale="Aligned."),
        balance_and_whitespace=VisualDimensionAssessment(score=balance_score, rationale="Balanced."),
        typography_and_style_consistency=VisualDimensionAssessment(score=typography_score, rationale="Consistent."),
        overall_readability=VisualDimensionAssessment(score=readability_score, rationale="Readable."),
        average_score=round((text_fit_score + visual_hierarchy_score + alignment_score + balance_score + typography_score + readability_score) / 6, 4),
        issues=issues or [],
        executive_summary="Visual QA complete.",
        generated_render_path="outputs/m9/generated.png",
        template_render_path="outputs/m9/template.png",
        overlay_render_path="outputs/m9/overlay.png",
    )


# ---------------------------------------------------------------------------
# RevisionRequest builder
# ---------------------------------------------------------------------------


def make_revision_request(
    slide_id: str = "slide-test-001",
    deck_id: str = "deck-abc123",
    manager_recommendation: str = "approve",
    visual_recommendation: str = "pass",
    m7_issues: Optional[list[ManagerReviewIssue]] = None,
    m8_issues: Optional[list[VisualQAIssue]] = None,
    source_material: Optional[str] = "Test source material for revision.",
    template_pptx: Optional[Path] = Path("data/test_decks/sample_consulting_deck.pptx"),
    output_pptx: Optional[Path] = Path("outputs/m9/revised_test_output.pptx"),
) -> RevisionRequest:
    brief = make_brief()
    draft = make_complete_draft(slide_id=slide_id, deck_id=deck_id)
    slot_map = make_slot_map(slide_id=slide_id, deck_id=deck_id)
    manager_review = make_manager_review(
        slide_id=slide_id, deck_id=deck_id,
        recommendation=manager_recommendation, issues=m7_issues,
    )
    visual_qa = make_visual_qa(
        slide_id=slide_id, deck_id=deck_id,
        recommendation=visual_recommendation, issues=m8_issues,
    )
    return RevisionRequest(
        brief=brief,
        draft=draft,
        slot_map=slot_map,
        manager_review=manager_review,
        visual_qa=visual_qa,
        source_material=source_material,
        template_pptx=template_pptx,
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
def revision_request():
    return make_revision_request()
