"""Tests for VisualRerankBrief and build_visual_rerank_brief."""

from __future__ import annotations

import pytest

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)
from slidestein.reranking.brief import VisualRerankBrief, build_visual_rerank_brief
from slidestein.reranking.candidates import VisualCandidateInput
from slidestein.retrieval.request import SlideRetrievalRequest


class TestVisualRerankBrief:
    def test_build_from_minimal_request(self) -> None:
        req = SlideRetrievalRequest(query_text="roadmap")
        brief = build_visual_rerank_brief(req)
        assert brief.query_text == "roadmap"
        assert brief.slide_function is None
        assert brief.primary_communication_job is None
        assert brief.preferred_visual_archetypes == ()
        assert brief.storyline_roles == ()
        assert brief.density is None
        assert brief.required_content_elements == ()

    def test_build_from_full_request(self) -> None:
        req = SlideRetrievalRequest(
            query_text="timeline roadmap",
            slide_function=SlideFunction.CONTENT,
            primary_communication_job=CommunicationJob.SHOW_TIMELINE,
            preferred_visual_archetypes=[VisualArchetype.ROADMAP],
            storyline_roles=[StorylineRole.PLAN],
            density=DensityLevel.HIGH,
            required_content_elements=["milestones", "owners"],
        )
        brief = build_visual_rerank_brief(req)
        assert brief.query_text == "timeline roadmap"
        assert brief.slide_function == SlideFunction.CONTENT
        assert brief.primary_communication_job == CommunicationJob.SHOW_TIMELINE
        assert brief.preferred_visual_archetypes == (VisualArchetype.ROADMAP,)
        assert brief.storyline_roles == (StorylineRole.PLAN,)
        assert brief.density == DensityLevel.HIGH
        assert brief.required_content_elements == ("milestones", "owners")

    def test_brief_is_frozen(self) -> None:
        req = SlideRetrievalRequest(query_text="test")
        brief = build_visual_rerank_brief(req)
        with pytest.raises(Exception):
            brief.query_text = "changed"  # type: ignore[misc]

    def test_brief_is_deterministic(self) -> None:
        req = SlideRetrievalRequest(query_text="same query")
        assert build_visual_rerank_brief(req) == build_visual_rerank_brief(req)

    def test_archetypes_are_tuple(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            preferred_visual_archetypes=[VisualArchetype.TABLE, VisualArchetype.ROADMAP],
        )
        brief = build_visual_rerank_brief(req)
        assert isinstance(brief.preferred_visual_archetypes, tuple)

    def test_required_elements_are_tuple(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["team", "objective"],
        )
        brief = build_visual_rerank_brief(req)
        assert isinstance(brief.required_content_elements, tuple)
        assert brief.required_content_elements == ("team", "objective")

    def test_no_llm_or_new_information(self) -> None:
        req = SlideRetrievalRequest(
            query_text="governance",
            primary_communication_job=CommunicationJob.SUMMARISE,
        )
        brief = build_visual_rerank_brief(req)
        assert brief.query_text == req.query_text
        assert brief.primary_communication_job == req.primary_communication_job
