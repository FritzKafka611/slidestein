"""Unit tests for ConsultingSlideBrief and SlideBriefModelOutput domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.briefing.brief import (
    ConsultingSlideBrief,
    SlideBriefModelOutput,
    _normalize_string_list,
)
from slidestein.briefing.versions import SLIDE_BRIEF_SCHEMA_VERSION
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_brief(**kwargs) -> ConsultingSlideBrief:
    defaults = dict(
        original_request="Show the workstream roadmap",
        key_message="Five workstreams delivered over 12 weeks with milestones.",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SHOW_TIMELINE,
    )
    defaults.update(kwargs)
    return ConsultingSlideBrief(**defaults)


def _cover_brief(**kwargs) -> ConsultingSlideBrief:
    defaults = dict(
        original_request="I need a cover slide for the project kickoff.",
        key_message="Project kickoff presentation cover slide.",
        slide_function=SlideFunction.COVER,
        primary_communication_job=None,
    )
    defaults.update(kwargs)
    return ConsultingSlideBrief(**defaults)


def _model_output(**kwargs) -> SlideBriefModelOutput:
    defaults = dict(
        key_message="Five workstreams delivered over 12 weeks with milestones.",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SHOW_TIMELINE,
    )
    defaults.update(kwargs)
    return SlideBriefModelOutput(**defaults)


# ---------------------------------------------------------------------------
# Valid briefs
# ---------------------------------------------------------------------------

class TestValidBriefs:
    def test_content_brief_accepted(self):
        b = _content_brief()
        assert b.slide_function == SlideFunction.CONTENT
        assert b.primary_communication_job == CommunicationJob.SHOW_TIMELINE

    def test_cover_brief_accepted(self):
        b = _cover_brief()
        assert b.slide_function == SlideFunction.COVER
        assert b.primary_communication_job is None
        assert b.secondary_communication_jobs == []

    def test_section_divider_brief_accepted(self):
        b = ConsultingSlideBrief(
            original_request="Add a section break for the analysis phase.",
            key_message="Analysis phase begins here.",
            slide_function=SlideFunction.SECTION_DIVIDER,
            primary_communication_job=None,
        )
        assert b.slide_function == SlideFunction.SECTION_DIVIDER

    def test_closing_brief_accepted(self):
        b = ConsultingSlideBrief(
            original_request="Close the deck with a Q&A invitation.",
            key_message="Thank you — questions welcome.",
            slide_function=SlideFunction.CLOSING,
            primary_communication_job=None,
        )
        assert b.slide_function == SlideFunction.CLOSING

    def test_schema_version_defaults_to_constant(self):
        b = _content_brief()
        assert b.schema_version == SLIDE_BRIEF_SCHEMA_VERSION

    def test_schema_version_settable_at_construction(self):
        b = ConsultingSlideBrief(
            schema_version="2.0",
            original_request="Show the workstream roadmap",
            key_message="Five workstreams.",
            slide_function=SlideFunction.CONTENT,
            primary_communication_job=CommunicationJob.SHOW_TIMELINE,
        )
        assert b.schema_version == "2.0"

    def test_optional_fields_have_sane_defaults(self):
        b = _content_brief()
        assert b.secondary_communication_jobs == []
        assert b.storyline_roles == []
        assert b.required_content_elements == []
        assert b.preferred_visual_archetypes == []
        assert b.density is None
        assert b.assumptions == []
        assert b.open_questions == []

    def test_all_optional_fields_accepted(self):
        b = ConsultingSlideBrief(
            original_request="Complex slide request",
            key_message="The project delivers in three phases.",
            slide_function=SlideFunction.CONTENT,
            primary_communication_job=CommunicationJob.SHOW_PROCESS,
            secondary_communication_jobs=[CommunicationJob.SHOW_TIMELINE],
            storyline_roles=[StorylineRole.SITUATION, StorylineRole.COMPLICATION],
            required_content_elements=["three phases", "milestones"],
            preferred_visual_archetypes=[VisualArchetype.ROADMAP, VisualArchetype.TIMELINE],
            density=DensityLevel.MEDIUM,
            assumptions=["Assumed implementation stage."],
            open_questions=["How many phases are needed?"],
        )
        assert b.primary_communication_job == CommunicationJob.SHOW_PROCESS
        assert CommunicationJob.SHOW_TIMELINE in b.secondary_communication_jobs


# ---------------------------------------------------------------------------
# Application ownership of original_request and schema_version
# ---------------------------------------------------------------------------

class TestApplicationOwnership:
    def test_original_request_always_equals_application_input(self):
        request = "My exact slide request"
        b = ConsultingSlideBrief(
            original_request=request,
            key_message="A key message.",
            slide_function=SlideFunction.CONTENT,
            primary_communication_job=CommunicationJob.SUMMARISE,
        )
        assert b.original_request == request

    def test_model_output_cannot_supply_original_request(self):
        # SlideBriefModelOutput has no original_request field;
        # passing it triggers extra="forbid"
        with pytest.raises(ValidationError):
            SlideBriefModelOutput(
                key_message="Key message.",
                slide_function=SlideFunction.CONTENT,
                primary_communication_job=CommunicationJob.SUMMARISE,
                original_request="injected",  # type: ignore[call-arg]
            )

    def test_model_output_cannot_supply_schema_version(self):
        with pytest.raises(ValidationError):
            SlideBriefModelOutput(
                key_message="Key message.",
                slide_function=SlideFunction.CONTENT,
                primary_communication_job=CommunicationJob.SUMMARISE,
                schema_version="99.9",  # type: ignore[call-arg]
            )

    def test_schema_version_always_comes_from_application(self):
        b = ConsultingSlideBrief(
            schema_version=SLIDE_BRIEF_SCHEMA_VERSION,
            original_request="Test request",
            key_message="A key message.",
            slide_function=SlideFunction.CONTENT,
            primary_communication_job=CommunicationJob.SUMMARISE,
        )
        assert b.schema_version == SLIDE_BRIEF_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Strict extra="forbid" policies
# ---------------------------------------------------------------------------

class TestStrictExtraForbid:
    def test_consulting_slide_brief_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            ConsultingSlideBrief(
                original_request="A request",
                key_message="A message.",
                slide_function=SlideFunction.CONTENT,
                primary_communication_job=CommunicationJob.COMPARE,
                hallucinated_field="unexpected",  # type: ignore[call-arg]
            )

    def test_model_output_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            SlideBriefModelOutput(
                key_message="A message.",
                slide_function=SlideFunction.CONTENT,
                primary_communication_job=CommunicationJob.COMPARE,
                unknown_field="unexpected",  # type: ignore[call-arg]
            )

    def test_model_output_valid_exact_output_accepted(self):
        out = _model_output()
        assert out.slide_function == SlideFunction.CONTENT


# ---------------------------------------------------------------------------
# Blank field rejections
# ---------------------------------------------------------------------------

class TestBlankFieldRejections:
    def test_blank_original_request_rejected(self):
        with pytest.raises(ValidationError, match="original_request"):
            _content_brief(original_request="   ")

    def test_empty_original_request_rejected(self):
        with pytest.raises(ValidationError):
            _content_brief(original_request="")

    def test_blank_key_message_rejected(self):
        with pytest.raises(ValidationError, match="key_message"):
            _content_brief(key_message="   ")

    def test_empty_key_message_rejected(self):
        with pytest.raises(ValidationError):
            _content_brief(key_message="")


# ---------------------------------------------------------------------------
# Cross-field validation
# ---------------------------------------------------------------------------

class TestCrossFieldValidation:
    def test_content_with_null_primary_job_rejected(self):
        with pytest.raises(ValidationError, match="primary_communication_job"):
            ConsultingSlideBrief(
                original_request="Show a comparison.",
                key_message="Two options compared side by side.",
                slide_function=SlideFunction.CONTENT,
                primary_communication_job=None,
            )

    def test_cover_with_non_null_primary_job_rejected(self):
        with pytest.raises(ValidationError, match="primary_communication_job"):
            ConsultingSlideBrief(
                original_request="Cover slide.",
                key_message="Cover.",
                slide_function=SlideFunction.COVER,
                primary_communication_job=CommunicationJob.COMPARE,
            )

    def test_section_divider_with_non_null_primary_job_rejected(self):
        with pytest.raises(ValidationError):
            ConsultingSlideBrief(
                original_request="Section break.",
                key_message="New section.",
                slide_function=SlideFunction.SECTION_DIVIDER,
                primary_communication_job=CommunicationJob.SUMMARISE,
            )

    def test_closing_with_non_null_primary_job_rejected(self):
        with pytest.raises(ValidationError):
            ConsultingSlideBrief(
                original_request="Closing slide.",
                key_message="Thanks.",
                slide_function=SlideFunction.CLOSING,
                primary_communication_job=CommunicationJob.RECOMMEND,
            )

    def test_non_content_with_secondary_jobs_rejected(self):
        with pytest.raises(ValidationError, match="secondary_communication_jobs"):
            ConsultingSlideBrief(
                original_request="Cover slide.",
                key_message="Cover.",
                slide_function=SlideFunction.COVER,
                primary_communication_job=None,
                secondary_communication_jobs=[CommunicationJob.COMPARE],
            )

    def test_primary_in_secondary_rejected(self):
        with pytest.raises(ValidationError, match="secondary_communication_jobs"):
            ConsultingSlideBrief(
                original_request="Show comparison and process.",
                key_message="Two approaches compared.",
                slide_function=SlideFunction.CONTENT,
                primary_communication_job=CommunicationJob.COMPARE,
                secondary_communication_jobs=[CommunicationJob.COMPARE],
            )


# ---------------------------------------------------------------------------
# Silent deduplication
# ---------------------------------------------------------------------------

class TestSilentDeduplication:
    def test_duplicate_secondary_jobs_silently_deduped(self):
        b = _content_brief(
            secondary_communication_jobs=[
                CommunicationJob.COMPARE,
                CommunicationJob.COMPARE,
                CommunicationJob.SUMMARISE,
            ]
        )
        assert b.secondary_communication_jobs == [
            CommunicationJob.COMPARE,
            CommunicationJob.SUMMARISE,
        ]

    def test_duplicate_storyline_roles_silently_deduped(self):
        b = _content_brief(
            storyline_roles=[StorylineRole.SITUATION, StorylineRole.SITUATION, StorylineRole.COMPLICATION]
        )
        assert b.storyline_roles == [StorylineRole.SITUATION, StorylineRole.COMPLICATION]

    def test_duplicate_preferred_archetypes_silently_deduped(self):
        b = _content_brief(
            preferred_visual_archetypes=[VisualArchetype.ROADMAP, VisualArchetype.ROADMAP]
        )
        assert b.preferred_visual_archetypes == [VisualArchetype.ROADMAP]


# ---------------------------------------------------------------------------
# String list normalization
# ---------------------------------------------------------------------------

class TestStringListNormalization:
    def test_required_content_strips_whitespace(self):
        b = _content_brief(required_content_elements=["  five workstreams  ", "12-week timeline"])
        assert b.required_content_elements[0] == "five workstreams"

    def test_required_content_removes_blanks(self):
        b = _content_brief(required_content_elements=["five workstreams", "  ", "milestones"])
        assert "" not in b.required_content_elements
        assert "   " not in b.required_content_elements
        assert len(b.required_content_elements) == 2

    def test_required_content_case_insensitive_dedup(self):
        b = _content_brief(required_content_elements=["Milestones", "milestones", "MILESTONES"])
        assert b.required_content_elements == ["Milestones"]

    def test_required_content_preserves_first_spelling(self):
        b = _content_brief(required_content_elements=["Milestones", "milestones"])
        assert b.required_content_elements[0] == "Milestones"

    def test_assumptions_normalization(self):
        b = _content_brief(assumptions=["  Assumed implementation.  ", "", "Assumed implementation."])
        assert b.assumptions == ["Assumed implementation."]

    def test_open_questions_normalization(self):
        b = _content_brief(open_questions=["How many phases?", "  ", "How many phases?"])
        assert b.open_questions == ["How many phases?"]


# ---------------------------------------------------------------------------
# _normalize_string_list helper — including casefold regression
# ---------------------------------------------------------------------------

class TestNormalizeStringList:
    def test_empty_input(self):
        assert _normalize_string_list([]) == []

    def test_strips_whitespace(self):
        assert _normalize_string_list(["  hello  "]) == ["hello"]

    def test_removes_blank_strings(self):
        assert _normalize_string_list(["a", "  ", "b"]) == ["a", "b"]

    def test_case_insensitive_dedup_preserves_first(self):
        assert _normalize_string_list(["Apple", "apple", "APPLE"]) == ["Apple"]

    def test_preserves_order(self):
        result = _normalize_string_list(["c", "a", "b"])
        assert result == ["c", "a", "b"]

    def test_casefold_unicode_dedup(self):
        # "Straße".casefold() == "strasse" and "STRASSE".casefold() == "strasse"
        # so both fold to the same key.  lower() would NOT collapse this pair
        # because "Straße".lower() == "straße" != "strasse".
        result = _normalize_string_list(["Straße", "STRASSE"])
        assert result == ["Straße"]

    def test_casefold_dedup_does_not_collapse_distinct_words(self):
        result = _normalize_string_list(["Alpha", "Beta"])
        assert result == ["Alpha", "Beta"]
