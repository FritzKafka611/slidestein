"""Shared fixtures for test_review."""

from __future__ import annotations

from typing import Optional

import pytest

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.domain.models import (
    CommunicationJob,
    SlideFunction,
)
from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.review.models import (
    DimensionAssessment,
    ManagerReviewIssue,
    ManagerReviewModelOutput,
    ManagerReviewRequest,
)
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Brief helpers
# ---------------------------------------------------------------------------


def make_brief(key_message: str = "Digital cost reduction should target top-3 channels.") -> ConsultingSlideBrief:
    return ConsultingSlideBrief(
        original_request="Show how digital cost reduction is focused on three channels.",
        key_message=key_message,
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.RECOMMEND,
    )


# ---------------------------------------------------------------------------
# Slot / slot map helpers
# ---------------------------------------------------------------------------


def make_slot(
    slot_id: str = "slot-001",
    shape_id: int = 7,
    shape_path: str = "7",
    slot_role: SlotRole = SlotRole.TITLE,
    semantic_label: str = "Title",
    y_ratio: float = 0.05,
    x_ratio: float = 0.05,
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        editable=True,
        confidence=0.9,
        current_text="Placeholder",
        geometry={
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 50,
            "x_ratio": x_ratio,
            "y_ratio": y_ratio,
            "width_ratio": 0.8,
            "height_ratio": 0.1,
        },
        capacity=SlotCapacity(
            max_characters_estimate=120,
            max_lines_estimate=2,
            current_character_count=10,
            current_line_count=1,
            relative_capacity="medium",
        ),
    )


def make_slot_map(slots: Optional[list[TemplateSlot]] = None) -> TemplateSlotMap:
    if slots is None:
        slots = [
            make_slot(slot_id="slot-001", shape_id=7, shape_path="7", slot_role=SlotRole.TITLE, semantic_label="Title", y_ratio=0.05, x_ratio=0.05),
            make_slot(slot_id="slot-002", shape_id=8, shape_path="8", slot_role=SlotRole.BODY_TEXT, semantic_label="Body", y_ratio=0.2, x_ratio=0.05),
        ]
    return TemplateSlotMap(
        slide_id="slide-test",
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
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
    shape_id: int = 7,
    shape_path: str = "7",
    action: SlotDraftAction = SlotDraftAction.REPLACE,
    text: Optional[str] = "Digital cost reduction focuses on top-3 channels.",
    slot_role: SlotRole = SlotRole.TITLE,
    semantic_label: str = "Title",
) -> SlotDraftAssignment:
    return SlotDraftAssignment(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        slot_role=slot_role,
        semantic_label=semantic_label,
        action=action,
        text=text,
        capacity_characters=120,
        capacity_utilization=0.4,
        max_lines_estimate=2,
    )


def make_complete_draft(
    is_complete: bool = True,
    assignments: Optional[list[SlotDraftAssignment]] = None,
) -> SlideContentDraft:
    if assignments is None:
        if is_complete:
            assignments = [
                make_assignment(slot_id="slot-001", shape_id=7, shape_path="7",
                                slot_role=SlotRole.TITLE, semantic_label="Title"),
                make_assignment(slot_id="slot-002", shape_id=8, shape_path="8",
                                slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
                                text="Channel 1, Channel 2, Channel 3 each save 15% cost."),
            ]
        else:
            # is_complete=False requires at least one NEEDS_INPUT assignment.
            # Only slot-001 — this draft is intentionally NOT identity-matched
            # to the default slot_map (which has 2 slots), but the is_complete
            # check fires before identity validation so tests still pass.
            assignments = [
                SlotDraftAssignment(
                    slot_id="slot-001",
                    shape_id=7,
                    shape_path="7",
                    slot_role=SlotRole.TITLE,
                    semantic_label="Title",
                    action=SlotDraftAction.NEEDS_INPUT,
                    text=None,
                    missing_information="Need the client name.",
                    capacity_characters=120,
                    capacity_utilization=0.0,
                    max_lines_estimate=2,
                )
            ]
    return SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Digital cost reduction should target top-3 channels.",
        assignments=assignments,
        drafting_summary="Draft covering cost reduction across three digital channels.",
        is_complete=is_complete,
    )


# ---------------------------------------------------------------------------
# ManagerReviewModelOutput helper
# ---------------------------------------------------------------------------


def make_factual_flag(
    issue: str = "Metric cannot be verified from source material.",
    recommendation: str = "Remove or provide a source.",
    severity: str = "minor",
    slot_keys: Optional[list[str]] = None,
) -> ManagerReviewIssue:
    return ManagerReviewIssue(
        severity=severity,  # type: ignore[arg-type]
        category="factual_grounding",
        slot_keys=slot_keys or [],
        issue=issue,
        recommendation=recommendation,
    )


def make_model_output(
    recommendation: str = "approve",
    scores: Optional[dict[str, int]] = None,
    issues: Optional[list[ManagerReviewIssue]] = None,
    factual_flags: Optional[list[ManagerReviewIssue]] = None,
    executive_summary: str = "A well-structured slide that clearly supports the key message.",
) -> ManagerReviewModelOutput:
    if scores is None:
        scores = {
            "answer_first_title": 4,
            "core_message_clarity": 4,
            "vertical_logic": 4,
            "exhibit_title_consistency": 4,
            "mece_structure": 4,
            "content_density": 4,
        }
    return ManagerReviewModelOutput(
        recommendation=recommendation,  # type: ignore[arg-type]
        answer_first_title=DimensionAssessment(score=scores["answer_first_title"], rationale="Good insight title."),
        core_message_clarity=DimensionAssessment(score=scores["core_message_clarity"], rationale="Clear argument."),
        vertical_logic=DimensionAssessment(score=scores["vertical_logic"], rationale="Elements support title."),
        exhibit_title_consistency=DimensionAssessment(score=scores["exhibit_title_consistency"], rationale="Exhibit labels align."),
        mece_structure=DimensionAssessment(score=scores["mece_structure"], rationale="No overlaps found."),
        content_density=DimensionAssessment(score=scores["content_density"], rationale="Concise content."),
        issues=issues or [],
        factual_flags=factual_flags or [],
        executive_summary=executive_summary,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_complete_review_request():
    def _make(is_complete: bool = True) -> ManagerReviewRequest:
        return ManagerReviewRequest(
            brief=make_brief(),
            draft=make_complete_draft(is_complete=is_complete),
            slot_map=make_slot_map(),
        )
    return _make


@pytest.fixture
def review_request() -> ManagerReviewRequest:
    return ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(is_complete=True),
        slot_map=make_slot_map(),
    )


@pytest.fixture
def model_output() -> ManagerReviewModelOutput:
    return make_model_output()
