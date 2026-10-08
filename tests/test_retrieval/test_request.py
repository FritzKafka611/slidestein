"""Tests for SlideRetrievalRequest and build_enriched_query."""

from __future__ import annotations

import pytest

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)
from slidestein.retrieval.request import SlideRetrievalRequest, build_enriched_query


# ---------------------------------------------------------------------------
# SlideRetrievalRequest — construction
# ---------------------------------------------------------------------------


class TestSlideRetrievalRequestConstruction:
    def test_minimal_construction(self) -> None:
        req = SlideRetrievalRequest(query_text="find a cover slide")
        assert req.query_text == "find a cover slide"
        assert req.slide_function is None
        assert req.primary_communication_job is None
        assert req.preferred_visual_archetypes == []
        assert req.storyline_roles == []
        assert req.density is None
        assert req.required_content_elements == []
        assert req.top_k == 5
        assert req.strict_slide_function is False

    def test_full_construction(self) -> None:
        req = SlideRetrievalRequest(
            query_text="governance table",
            slide_function=SlideFunction.CONTENT,
            primary_communication_job=CommunicationJob.SUMMARISE,
            preferred_visual_archetypes=[VisualArchetype.TABLE],
            storyline_roles=[StorylineRole.CONTEXT],
            density=DensityLevel.HIGH,
            required_content_elements=["participants", "frequency"],
            top_k=10,
            strict_slide_function=True,
        )
        assert req.slide_function == SlideFunction.CONTENT
        assert req.primary_communication_job == CommunicationJob.SUMMARISE
        assert req.preferred_visual_archetypes == [VisualArchetype.TABLE]
        assert req.storyline_roles == [StorylineRole.CONTEXT]
        assert req.density == DensityLevel.HIGH
        assert req.required_content_elements == ["participants", "frequency"]
        assert req.top_k == 10
        assert req.strict_slide_function is True

    def test_is_frozen(self) -> None:
        req = SlideRetrievalRequest(query_text="test")
        with pytest.raises(Exception):
            req.query_text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validation — query_text
# ---------------------------------------------------------------------------


class TestQueryTextValidation:
    def test_blank_query_raises(self) -> None:
        with pytest.raises(Exception, match="blank"):
            SlideRetrievalRequest(query_text="   ")

    def test_empty_query_raises(self) -> None:
        with pytest.raises(Exception):
            SlideRetrievalRequest(query_text="")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(Exception):
            SlideRetrievalRequest(query_text="\n\t  ")

    def test_single_word_accepted(self) -> None:
        req = SlideRetrievalRequest(query_text="timeline")
        assert req.query_text == "timeline"


# ---------------------------------------------------------------------------
# Validation — top_k
# ---------------------------------------------------------------------------


class TestTopKValidation:
    def test_top_k_zero_raises(self) -> None:
        with pytest.raises(Exception):
            SlideRetrievalRequest(query_text="test", top_k=0)

    def test_top_k_negative_raises(self) -> None:
        with pytest.raises(Exception):
            SlideRetrievalRequest(query_text="test", top_k=-1)

    def test_top_k_one_accepted(self) -> None:
        req = SlideRetrievalRequest(query_text="test", top_k=1)
        assert req.top_k == 1


# ---------------------------------------------------------------------------
# Validation — strict_slide_function
# ---------------------------------------------------------------------------


class TestStrictSlideFunctionValidation:
    def test_strict_without_function_raises(self) -> None:
        with pytest.raises(Exception, match="strict_slide_function"):
            SlideRetrievalRequest(query_text="test", strict_slide_function=True)

    def test_strict_with_function_accepted(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            slide_function=SlideFunction.CONTENT,
            strict_slide_function=True,
        )
        assert req.strict_slide_function is True


# ---------------------------------------------------------------------------
# Deduplication — archetypes and roles
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_archetypes_deduped(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            preferred_visual_archetypes=[
                VisualArchetype.TABLE, VisualArchetype.TABLE, VisualArchetype.ROADMAP
            ],
        )
        assert req.preferred_visual_archetypes == [VisualArchetype.TABLE, VisualArchetype.ROADMAP]

    def test_roles_deduped(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            storyline_roles=[StorylineRole.CONTEXT, StorylineRole.CONTEXT, StorylineRole.PLAN],
        )
        assert req.storyline_roles == [StorylineRole.CONTEXT, StorylineRole.PLAN]

    def test_single_archetype_preserved(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            preferred_visual_archetypes=[VisualArchetype.TABLE],
        )
        assert req.preferred_visual_archetypes == [VisualArchetype.TABLE]

    def test_all_duplicate_archetypes_becomes_single(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            preferred_visual_archetypes=[VisualArchetype.TABLE, VisualArchetype.TABLE],
        )
        assert req.preferred_visual_archetypes == [VisualArchetype.TABLE]

    def test_empty_archetypes_remains_empty(self) -> None:
        req = SlideRetrievalRequest(query_text="test", preferred_visual_archetypes=[])
        assert req.preferred_visual_archetypes == []

    def test_empty_roles_remains_empty(self) -> None:
        req = SlideRetrievalRequest(query_text="test", storyline_roles=[])
        assert req.storyline_roles == []


# ---------------------------------------------------------------------------
# required_content_elements — normalization
# ---------------------------------------------------------------------------


class TestRequiredContentElementsNormalization:
    def test_spec_example(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=[
                " Team ",
                "team",
                "DELIVERABLES",
                "deliverables ",
                "Risks",
            ],
        )
        assert req.required_content_elements == ["Team", "DELIVERABLES", "Risks"]

    def test_whitespace_stripped(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["  participants  "],
        )
        assert req.required_content_elements == ["participants"]

    def test_blank_elements_removed(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["team", "", "   ", "objective"],
        )
        assert req.required_content_elements == ["team", "objective"]

    def test_case_insensitive_dedup_preserves_first(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["TEAM", "team", "Team"],
        )
        assert req.required_content_elements == ["TEAM"]

    def test_order_preserved(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["gamma", "alpha", "beta"],
        )
        assert req.required_content_elements == ["gamma", "alpha", "beta"]

    def test_empty_list_remains_empty(self) -> None:
        req = SlideRetrievalRequest(query_text="test", required_content_elements=[])
        assert req.required_content_elements == []

    def test_all_blank_becomes_empty(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["  ", "\t", ""],
        )
        assert req.required_content_elements == []


# ---------------------------------------------------------------------------
# build_enriched_query
# ---------------------------------------------------------------------------


class TestBuildEnrichedQuery:
    def test_no_elements_returns_query_unchanged(self) -> None:
        req = SlideRetrievalRequest(query_text="find a roadmap slide")
        assert build_enriched_query(req) == "find a roadmap slide"

    def test_with_elements_has_required_content_header(self) -> None:
        req = SlideRetrievalRequest(
            query_text="governance table",
            required_content_elements=["participants"],
        )
        result = build_enriched_query(req)
        assert "Required content:" in result

    def test_query_text_first_line(self) -> None:
        req = SlideRetrievalRequest(
            query_text="governance table",
            required_content_elements=["participants"],
        )
        result = build_enriched_query(req)
        assert result.startswith("governance table\n")

    def test_blank_line_separates_query_from_section(self) -> None:
        req = SlideRetrievalRequest(
            query_text="governance table",
            required_content_elements=["participants"],
        )
        result = build_enriched_query(req)
        assert "\n\nRequired content:" in result

    def test_single_element_appended(self) -> None:
        req = SlideRetrievalRequest(
            query_text="governance table",
            required_content_elements=["participants"],
        )
        result = build_enriched_query(req)
        assert "- participants" in result

    def test_multiple_elements_as_bullets(self) -> None:
        req = SlideRetrievalRequest(
            query_text="workstream one-pager",
            required_content_elements=["team", "objective", "deliverables"],
        )
        result = build_enriched_query(req)
        assert "Required content:" in result
        assert "- team" in result
        assert "- objective" in result
        assert "- deliverables" in result

    def test_exact_format_with_multiple_elements(self) -> None:
        req = SlideRetrievalRequest(
            query_text="workstreams",
            required_content_elements=["team", "objective", "deliverables"],
        )
        expected = (
            "workstreams\n"
            "\n"
            "Required content:\n"
            "- team\n"
            "- objective\n"
            "- deliverables"
        )
        assert build_enriched_query(req) == expected

    def test_element_order_preserved_in_output(self) -> None:
        req = SlideRetrievalRequest(
            query_text="test",
            required_content_elements=["alpha", "beta", "gamma"],
        )
        result = build_enriched_query(req)
        alpha_pos = result.index("- alpha")
        beta_pos = result.index("- beta")
        gamma_pos = result.index("- gamma")
        assert alpha_pos < beta_pos < gamma_pos
