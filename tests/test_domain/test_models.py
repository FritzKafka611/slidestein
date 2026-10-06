"""Tests for domain models — serialisation, validation, and enum coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from slidestein.domain.models import (
    CommunicationJob,
    ContentSlot,
    ContentSlotType,
    DraftedContent,
    GeneratedSlide,
    ReviewDimension,
    ReviewResult,
    SelectedSlide,
    SlideBrief,
    SlideCandidate,
    SlideMetadata,
    StorylineRole,
    UserRequest,
    VisualArchetype,
)


def _make_brief() -> SlideBrief:
    return SlideBrief(
        key_message="Revenue is declining due to customer churn",
        communication_job=CommunicationJob.CONVINCE,
        storyline_role=StorylineRole.COMPLICATION,
        required_content_elements=["churn rate trend", "revenue impact"],
        preferred_visual_archetypes=[VisualArchetype.BAR_CHART, VisualArchetype.WATERFALL],
        source_request="Show that we're losing revenue because customers are leaving",
    )


def _make_metadata(tmp_path: Path) -> SlideMetadata:
    return SlideMetadata(
        slide_id="abc123",
        template_path=tmp_path / "template.pptx",
        archetype=VisualArchetype.BAR_CHART,
        communication_jobs=[CommunicationJob.INFORM, CommunicationJob.CONVINCE],
        content_slots=[
            ContentSlot(
                slot_id="ph_0",
                slot_type=ContentSlotType.TITLE,
                placeholder_name="Title 1",
            )
        ],
        description="Bar chart template",
        tags=["finance", "trend"],
    )


class TestSlideBrief:
    def test_roundtrip_json(self):
        brief = _make_brief()
        restored = SlideBrief.model_validate_json(brief.model_dump_json())
        assert restored == brief

    def test_roundtrip_dict(self):
        brief = _make_brief()
        restored = SlideBrief.model_validate(brief.model_dump())
        assert restored == brief

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            SlideBrief(
                communication_job=CommunicationJob.INFORM,
                storyline_role=StorylineRole.SITUATION,
                required_content_elements=[],
                preferred_visual_archetypes=[],
                source_request="x",
                # key_message is missing
            )


class TestContentSlot:
    def test_defaults_are_none(self):
        slot = ContentSlot(
            slot_id="ph_0",
            slot_type=ContentSlotType.TITLE,
            placeholder_name="Title 1",
        )
        assert slot.value is None
        assert slot.max_chars is None

    def test_with_value(self):
        slot = ContentSlot(
            slot_id="ph_1",
            slot_type=ContentSlotType.BODY,
            placeholder_name="Content Placeholder 2",
            max_chars=200,
            value="Our revenue declined 15% QoQ.",
        )
        assert slot.value == "Our revenue declined 15% QoQ."
        assert slot.max_chars == 200


class TestSlideMetadata:
    def test_roundtrip_json(self, tmp_path):
        metadata = _make_metadata(tmp_path)
        restored = SlideMetadata.model_validate_json(metadata.model_dump_json())
        assert restored.slide_id == metadata.slide_id
        assert restored.archetype == metadata.archetype
        assert len(restored.content_slots) == 1

    def test_tags_default_empty(self, tmp_path):
        metadata = SlideMetadata(
            slide_id="x",
            template_path=tmp_path / "t.pptx",
            archetype=VisualArchetype.TITLE_ONLY,
            communication_jobs=[CommunicationJob.INFORM],
            content_slots=[],
            description="minimal",
        )
        assert metadata.tags == []


class TestSlideCandidate:
    def test_score_bounds(self, tmp_path):
        metadata = _make_metadata(tmp_path)
        candidate = SlideCandidate(
            metadata=metadata,
            similarity_score=0.9,
            job_fit_score=0.8,
            structural_capacity_score=0.7,
            archetype_score=1.0,
            combined_score=0.85,
        )
        assert 0.0 <= candidate.combined_score <= 1.0

    def test_score_out_of_bounds_raises(self, tmp_path):
        metadata = _make_metadata(tmp_path)
        with pytest.raises(ValidationError):
            SlideCandidate(
                metadata=metadata,
                similarity_score=1.5,  # > 1.0
                job_fit_score=0.5,
                structural_capacity_score=0.5,
                archetype_score=0.5,
                combined_score=0.5,
            )


class TestReviewResult:
    def test_approved_result(self):
        review = ReviewResult(
            answer_first_title=ReviewDimension(passed=True, note=""),
            core_message_clarity=ReviewDimension(passed=True, note=""),
            vertical_logic=ReviewDimension(passed=True, note=""),
            exhibit_title_consistency=ReviewDimension(passed=True, note=""),
            mece_structure=ReviewDimension(passed=True, note=""),
            content_density="appropriate",
            approved=True,
        )
        assert review.approved is True
        assert review.revision_instructions is None

    def test_failed_result_has_instructions(self):
        review = ReviewResult(
            answer_first_title=ReviewDimension(passed=False, note="Title is not answer-first"),
            core_message_clarity=ReviewDimension(passed=True, note=""),
            vertical_logic=ReviewDimension(passed=True, note=""),
            exhibit_title_consistency=ReviewDimension(passed=True, note=""),
            mece_structure=ReviewDimension(passed=True, note=""),
            content_density="too_dense",
            approved=False,
            revision_instructions="Rewrite title to lead with the conclusion.",
        )
        assert review.approved is False
        assert "title" in (review.revision_instructions or "")


class TestUserRequest:
    def test_basic(self):
        req = UserRequest(text="Show revenue trend by region")
        assert req.text == "Show revenue trend by region"
