"""Tests for SlideSemanticProfileV2, SlideFunction, and parse_semantic_profile_json.

Covers:
- SlideFunction enum values
- Valid V2 profiles (content / navigational variants)
- Cross-field validation (content+null, non-content+job, non-content+secondary)
- structured_one_pager archetype
- parse_semantic_profile_json dispatcher (V1, V2, unknown version)
- ClassificationRecord profile field accepts both string and object
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.domain.models import (
    ClassificationRecord,
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    SlideSemanticProfile,
    SlideSemanticProfileV1,
    SlideSemanticProfileV2,
    StorylineRole,
    VisualArchetype,
    parse_semantic_profile_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _v2_content(**overrides) -> SlideSemanticProfileV2:
    kwargs = dict(
        slide_id="test-slide-v2",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SUMMARISE,
        storyline_roles=[StorylineRole.PLAN],
        visual_archetype=VisualArchetype.STRUCTURED_ONE_PAGER,
        structural_pattern="Five-section one-pager with labeled rows.",
        density=DensityLevel.HIGH,
        description="A workstream charter summarising scope and milestones.",
        best_for=["program governance", "initiative charters"],
        not_for=["quantitative analysis"],
    )
    kwargs.update(overrides)
    return SlideSemanticProfileV2(**kwargs)


def _v2_nav(func: SlideFunction, **overrides) -> SlideSemanticProfileV2:
    kwargs = dict(
        slide_id="test-nav",
        slide_function=func,
        primary_communication_job=None,
        secondary_communication_jobs=[],
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.TITLE,
        structural_pattern="Minimal section divider with centred title.",
        density=DensityLevel.LOW,
        description="Section divider for structured decks.",
        best_for=["deck structure"],
        not_for=["detailed content"],
    )
    kwargs.update(overrides)
    return SlideSemanticProfileV2(**kwargs)


# ---------------------------------------------------------------------------
# 1. SlideFunction enum
# ---------------------------------------------------------------------------

class TestSlideFunction:
    def test_all_values_present(self) -> None:
        values = {f.value for f in SlideFunction}
        assert values == {"content", "cover", "section_divider", "closing"}

    def test_content_value(self) -> None:
        assert SlideFunction.CONTENT.value == "content"

    def test_section_divider_value(self) -> None:
        assert SlideFunction.SECTION_DIVIDER.value == "section_divider"

    def test_cover_value(self) -> None:
        assert SlideFunction.COVER.value == "cover"

    def test_closing_value(self) -> None:
        assert SlideFunction.CLOSING.value == "closing"


# ---------------------------------------------------------------------------
# 2. Valid V2 profiles
# ---------------------------------------------------------------------------

class TestValidV2Profiles:
    def test_content_profile_roundtrip(self) -> None:
        profile = _v2_content()
        restored = SlideSemanticProfileV2.model_validate_json(profile.model_dump_json())
        assert restored == profile

    def test_schema_version_defaults_to_2(self) -> None:
        assert _v2_content().schema_version == "2.0"

    def test_section_divider_null_job(self) -> None:
        p = _v2_nav(SlideFunction.SECTION_DIVIDER)
        assert p.primary_communication_job is None
        assert p.secondary_communication_jobs == []

    def test_cover_null_job(self) -> None:
        p = _v2_nav(SlideFunction.COVER)
        assert p.primary_communication_job is None

    def test_closing_null_job(self) -> None:
        p = _v2_nav(SlideFunction.CLOSING)
        assert p.primary_communication_job is None

    def test_content_with_secondary_jobs(self) -> None:
        p = _v2_content(secondary_communication_jobs=[CommunicationJob.EXPLAIN])
        assert CommunicationJob.EXPLAIN in p.secondary_communication_jobs

    def test_structured_one_pager_archetype_accepted(self) -> None:
        p = _v2_content(visual_archetype=VisualArchetype.STRUCTURED_ONE_PAGER)
        assert p.visual_archetype == VisualArchetype.STRUCTURED_ONE_PAGER


# ---------------------------------------------------------------------------
# 3. Cross-field validation
# ---------------------------------------------------------------------------

class TestV2CrossFieldValidation:
    def test_content_with_null_job_raises(self) -> None:
        with pytest.raises(ValidationError, match="primary_communication_job"):
            _v2_content(primary_communication_job=None)

    def test_section_divider_with_job_raises(self) -> None:
        with pytest.raises(ValidationError, match="null"):
            _v2_nav(
                SlideFunction.SECTION_DIVIDER,
                primary_communication_job=CommunicationJob.SHOW_TIMELINE,
            )

    def test_cover_with_job_raises(self) -> None:
        with pytest.raises(ValidationError, match="null"):
            _v2_nav(
                SlideFunction.COVER,
                primary_communication_job=CommunicationJob.SUMMARISE,
            )

    def test_closing_with_job_raises(self) -> None:
        with pytest.raises(ValidationError, match="null"):
            _v2_nav(
                SlideFunction.CLOSING,
                primary_communication_job=CommunicationJob.SUMMARISE,
            )

    def test_cover_with_secondary_jobs_raises(self) -> None:
        with pytest.raises(ValidationError, match="empty"):
            _v2_nav(
                SlideFunction.COVER,
                secondary_communication_jobs=[CommunicationJob.SUMMARISE],
            )

    def test_content_secondary_duplicates_primary_raises(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _v2_content(
                primary_communication_job=CommunicationJob.SUMMARISE,
                secondary_communication_jobs=[CommunicationJob.SUMMARISE],
            )

    def test_blank_slide_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="slide_id"):
            _v2_content(slide_id="")

    def test_empty_storyline_roles_raises(self) -> None:
        with pytest.raises(ValidationError):
            _v2_content(storyline_roles=[])


# ---------------------------------------------------------------------------
# 4. parse_semantic_profile_json dispatcher
# ---------------------------------------------------------------------------

class TestParseSemanticProfileJson:
    def test_v1_json_returns_v1_type(self) -> None:
        v1 = SlideSemanticProfile(
            slide_id="s1",
            primary_communication_job=CommunicationJob.EXPLAIN,
            storyline_roles=[StorylineRole.CONTEXT],
            visual_archetype=VisualArchetype.TITLE,
            structural_pattern="Cover slide.",
            density=DensityLevel.LOW,
            description="A cover slide.",
        )
        result = parse_semantic_profile_json(v1.model_dump_json())
        assert isinstance(result, SlideSemanticProfile)
        assert result.schema_version == "1.0"

    def test_v2_json_returns_v2_type(self) -> None:
        v2 = _v2_content()
        result = parse_semantic_profile_json(v2.model_dump_json())
        assert isinstance(result, SlideSemanticProfileV2)
        assert result.schema_version == "2.0"

    def test_v2_nav_json_roundtrips(self) -> None:
        v2 = _v2_nav(SlideFunction.SECTION_DIVIDER)
        result = parse_semantic_profile_json(v2.model_dump_json())
        assert isinstance(result, SlideSemanticProfileV2)
        assert result.primary_communication_job is None

    def test_unknown_version_raises(self) -> None:
        bad = '{"schema_version": "9.9", "slide_id": "x"}'
        with pytest.raises(ValueError, match="9.9"):
            parse_semantic_profile_json(bad)

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid profile JSON"):
            parse_semantic_profile_json("{not valid json")

    def test_v1_alias_is_slide_semantic_profile(self) -> None:
        assert SlideSemanticProfileV1 is SlideSemanticProfile


# ---------------------------------------------------------------------------
# 5. ClassificationRecord profile field
# ---------------------------------------------------------------------------

class TestClassificationRecordProfile:
    def _base_record(self, profile):
        return ClassificationRecord(
            slide_id="s1",
            classification_version="2.0",
            model="test-model",
            prompt_version="2.0",
            input_fingerprint="abc123",
            profile=profile,
        )

    def test_accepts_v2_object(self) -> None:
        v2 = _v2_content()
        rec = self._base_record(v2)
        assert isinstance(rec.profile, SlideSemanticProfileV2)

    def test_accepts_v1_object(self) -> None:
        v1 = SlideSemanticProfile(
            slide_id="s1",
            primary_communication_job=CommunicationJob.EXPLAIN,
            storyline_roles=[StorylineRole.CONTEXT],
            visual_archetype=VisualArchetype.TITLE,
            structural_pattern="p",
            density=DensityLevel.LOW,
            description="d",
        )
        rec = self._base_record(v1)
        assert isinstance(rec.profile, SlideSemanticProfile)

    def test_accepts_v2_json_string(self) -> None:
        v2 = _v2_content()
        rec = self._base_record(v2.model_dump_json())
        assert isinstance(rec.profile, SlideSemanticProfileV2)

    def test_accepts_v1_json_string(self) -> None:
        v1_json = (
            '{"schema_version": "1.0", "slide_id": "s1", '
            '"primary_communication_job": "explain", '
            '"storyline_roles": ["context"], '
            '"visual_archetype": "title", '
            '"structural_pattern": "p", '
            '"density": "low", "description": "d"}'
        )
        rec = self._base_record(v1_json)
        assert isinstance(rec.profile, SlideSemanticProfile)
