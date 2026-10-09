"""Unit tests for brief_to_retrieval_request adapter."""

from __future__ import annotations

import pytest

from slidestein.briefing.adapter import brief_to_retrieval_request
from slidestein.briefing.brief import ConsultingSlideBrief
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
        original_request="Show the workstream roadmap over 12 weeks",
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


# ---------------------------------------------------------------------------
# Field mapping tests
# ---------------------------------------------------------------------------

class TestFieldMapping:
    def test_original_request_maps_to_query_text(self):
        b = _content_brief()
        rr = brief_to_retrieval_request(b)
        assert rr.query_text == b.original_request

    def test_key_message_not_used_as_query_text(self):
        b = _content_brief()
        rr = brief_to_retrieval_request(b)
        assert rr.query_text != b.key_message

    def test_slide_function_maps(self):
        b = _content_brief(slide_function=SlideFunction.CONTENT)
        rr = brief_to_retrieval_request(b)
        assert rr.slide_function == SlideFunction.CONTENT

    def test_primary_communication_job_maps(self):
        b = _content_brief(primary_communication_job=CommunicationJob.COMPARE)
        rr = brief_to_retrieval_request(b)
        assert rr.primary_communication_job == CommunicationJob.COMPARE

    def test_primary_communication_job_none_for_non_content(self):
        b = _cover_brief()
        rr = brief_to_retrieval_request(b)
        assert rr.primary_communication_job is None

    def test_storyline_roles_map(self):
        b = _content_brief(
            storyline_roles=[StorylineRole.SITUATION, StorylineRole.COMPLICATION]
        )
        rr = brief_to_retrieval_request(b)
        assert rr.storyline_roles == [StorylineRole.SITUATION, StorylineRole.COMPLICATION]

    def test_preferred_visual_archetypes_map(self):
        b = _content_brief(
            preferred_visual_archetypes=[VisualArchetype.ROADMAP, VisualArchetype.TIMELINE]
        )
        rr = brief_to_retrieval_request(b)
        assert rr.preferred_visual_archetypes == [VisualArchetype.ROADMAP, VisualArchetype.TIMELINE]

    def test_density_maps(self):
        b = _content_brief(density=DensityLevel.HIGH)
        rr = brief_to_retrieval_request(b)
        assert rr.density == DensityLevel.HIGH

    def test_density_none_maps(self):
        b = _content_brief(density=None)
        rr = brief_to_retrieval_request(b)
        assert rr.density is None

    def test_required_content_elements_map(self):
        b = _content_brief(required_content_elements=["five workstreams", "12-week timeline"])
        rr = brief_to_retrieval_request(b)
        assert rr.required_content_elements == ["five workstreams", "12-week timeline"]

    def test_default_top_k_is_5(self):
        b = _content_brief()
        rr = brief_to_retrieval_request(b)
        assert rr.top_k == 5

    def test_top_k_parameter_respected(self):
        b = _content_brief()
        rr = brief_to_retrieval_request(b, top_k=10)
        assert rr.top_k == 10

    def test_secondary_communication_jobs_not_in_retrieval_request(self):
        b = _content_brief(
            secondary_communication_jobs=[CommunicationJob.SUMMARISE]
        )
        rr = brief_to_retrieval_request(b)
        assert not hasattr(rr, "secondary_communication_jobs")

    def test_non_content_brief_maps_correctly(self):
        b = _cover_brief()
        rr = brief_to_retrieval_request(b)
        assert rr.slide_function == SlideFunction.COVER
        assert rr.primary_communication_job is None
        assert rr.query_text == b.original_request

    def test_empty_lists_map_to_empty(self):
        b = _content_brief(storyline_roles=[], preferred_visual_archetypes=[], required_content_elements=[])
        rr = brief_to_retrieval_request(b)
        assert rr.storyline_roles == []
        assert rr.preferred_visual_archetypes == []
        assert rr.required_content_elements == []
