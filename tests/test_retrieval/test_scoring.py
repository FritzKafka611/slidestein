"""Tests for hybrid retrieval scoring functions and HybridRetrievalWeights."""

from __future__ import annotations

import math

import pytest

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)
from slidestein.retrieval.scoring import (
    DEFAULT_WEIGHTS,
    HybridRetrievalWeights,
    archetype_fit,
    compute_hybrid_score,
    density_fit,
    function_fit,
    job_fit,
    role_fit,
    semantic_score,
)


# ---------------------------------------------------------------------------
# HybridRetrievalWeights — defaults
# ---------------------------------------------------------------------------


class TestHybridRetrievalWeights:
    def test_default_weights(self) -> None:
        w = HybridRetrievalWeights()
        assert w.semantic == 0.55
        assert w.communication_job == 0.20
        assert w.visual_archetype == 0.10
        assert w.slide_function == 0.05
        assert w.storyline_role == 0.05
        assert w.density == 0.05

    def test_weights_sum_to_one(self) -> None:
        w = HybridRetrievalWeights()
        total = (
            w.semantic + w.communication_job + w.visual_archetype
            + w.slide_function + w.storyline_role + w.density
        )
        assert abs(total - 1.0) < 1e-9

    def test_is_frozen(self) -> None:
        w = HybridRetrievalWeights()
        with pytest.raises(Exception):
            w.semantic = 0.9  # type: ignore[misc]

    def test_custom_valid_weights(self) -> None:
        w = HybridRetrievalWeights(
            semantic=0.9,
            communication_job=0.05,
            visual_archetype=0.02,
            slide_function=0.01,
            storyline_role=0.01,
            density=0.01,
        )
        assert w.semantic == 0.9


# ---------------------------------------------------------------------------
# HybridRetrievalWeights — validation
# ---------------------------------------------------------------------------


class TestHybridRetrievalWeightsValidation:
    def test_defaults_are_valid(self) -> None:
        # Must not raise
        HybridRetrievalWeights()

    def test_negative_semantic_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            HybridRetrievalWeights(
                semantic=-0.1,
                communication_job=0.60,
                visual_archetype=0.20,
                slide_function=0.10,
                storyline_role=0.10,
                density=0.10,
            )

    def test_negative_job_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            HybridRetrievalWeights(
                semantic=0.60,
                communication_job=-0.05,
                visual_archetype=0.20,
                slide_function=0.10,
                storyline_role=0.10,
                density=0.05,
            )

    def test_sum_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="sum"):
            HybridRetrievalWeights(
                semantic=0.50,
                communication_job=0.15,
                visual_archetype=0.05,
                slide_function=0.05,
                storyline_role=0.05,
                density=0.05,
            )  # sum = 0.85

    def test_sum_above_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="sum"):
            HybridRetrievalWeights(
                semantic=0.60,
                communication_job=0.25,
                visual_archetype=0.10,
                slide_function=0.05,
                storyline_role=0.05,
                density=0.05,
            )  # sum = 1.10

    def test_nan_weight_rejected(self) -> None:
        with pytest.raises(ValueError):
            HybridRetrievalWeights(
                semantic=float("nan"),
                communication_job=0.20,
                visual_archetype=0.10,
                slide_function=0.05,
                storyline_role=0.05,
                density=0.05,
            )

    def test_inf_weight_rejected(self) -> None:
        with pytest.raises(ValueError):
            HybridRetrievalWeights(
                semantic=float("inf"),
                communication_job=0.20,
                visual_archetype=0.10,
                slide_function=0.05,
                storyline_role=0.05,
                density=0.05,
            )


# ---------------------------------------------------------------------------
# semantic_score
# ---------------------------------------------------------------------------


class TestSemanticScore:
    def test_zero_distance_gives_one(self) -> None:
        assert semantic_score(0.0) == 1.0

    def test_one_distance_gives_zero(self) -> None:
        assert semantic_score(1.0) == 0.0

    def test_half_distance_gives_half(self) -> None:
        assert abs(semantic_score(0.5) - 0.5) < 1e-9

    def test_negative_distance_clamped_to_one(self) -> None:
        # Slightly negative numerical distances are clamped to 1.0
        assert semantic_score(-0.1) == 1.0

    def test_large_distance_clamped_to_zero(self) -> None:
        assert semantic_score(1.5) == 0.0

    def test_result_always_in_unit_interval(self) -> None:
        for d in [-1.0, -0.1, 0.0, 0.37, 0.55, 1.0, 1.5, 2.0]:
            s = semantic_score(d)
            assert 0.0 <= s <= 1.0, f"semantic_score({d}) = {s} not in [0, 1]"

    def test_typical_values(self) -> None:
        assert abs(semantic_score(0.37) - 0.63) < 1e-9
        assert abs(semantic_score(0.55) - 0.45) < 1e-9


# ---------------------------------------------------------------------------
# function_fit
# ---------------------------------------------------------------------------


class TestFunctionFit:
    def test_none_requested_returns_none(self) -> None:
        assert function_fit(None, "content") is None

    def test_exact_match_returns_one(self) -> None:
        assert function_fit(SlideFunction.CONTENT, "content") == 1.0

    def test_mismatch_returns_zero(self) -> None:
        assert function_fit(SlideFunction.CONTENT, "cover") == 0.0

    def test_section_divider_match(self) -> None:
        assert function_fit(SlideFunction.SECTION_DIVIDER, "section_divider") == 1.0

    def test_empty_candidate_mismatch(self) -> None:
        assert function_fit(SlideFunction.CONTENT, "") == 0.0


# ---------------------------------------------------------------------------
# job_fit
# ---------------------------------------------------------------------------


class TestJobFit:
    def test_none_requested_returns_none(self) -> None:
        assert job_fit(None, "summarise", "") is None

    def test_primary_match_returns_one(self) -> None:
        assert job_fit(CommunicationJob.SUMMARISE, "summarise", "") == 1.0

    def test_secondary_match_returns_half(self) -> None:
        assert job_fit(CommunicationJob.SUMMARISE, "explain", "summarise,show_timeline") == 0.5

    def test_miss_returns_zero(self) -> None:
        assert job_fit(CommunicationJob.SUMMARISE, "explain", "show_timeline") == 0.0

    def test_primary_takes_priority_over_secondary(self) -> None:
        assert job_fit(CommunicationJob.SUMMARISE, "summarise", "summarise") == 1.0

    def test_empty_secondary_no_match(self) -> None:
        assert job_fit(CommunicationJob.SUMMARISE, "explain", "") == 0.0

    def test_secondary_with_spaces_parsed(self) -> None:
        assert job_fit(CommunicationJob.EXPLAIN, "summarise", "explain, show_timeline") == 0.5


# ---------------------------------------------------------------------------
# archetype_fit
# ---------------------------------------------------------------------------


class TestArchetypeFit:
    def test_none_preferred_returns_none(self) -> None:
        assert archetype_fit(None, "table") is None

    def test_empty_list_returns_none(self) -> None:
        assert archetype_fit([], "table") is None

    def test_match_returns_one(self) -> None:
        assert archetype_fit([VisualArchetype.TABLE], "table") == 1.0

    def test_mismatch_returns_zero(self) -> None:
        assert archetype_fit([VisualArchetype.TABLE], "roadmap") == 0.0

    def test_match_in_multi_archetype_list(self) -> None:
        assert archetype_fit(
            [VisualArchetype.TABLE, VisualArchetype.ROADMAP], "roadmap"
        ) == 1.0

    def test_no_match_in_multi_archetype_list(self) -> None:
        assert archetype_fit(
            [VisualArchetype.TABLE, VisualArchetype.ROADMAP], "title"
        ) == 0.0


# ---------------------------------------------------------------------------
# role_fit
# ---------------------------------------------------------------------------


class TestRoleFit:
    def test_none_requested_returns_none(self) -> None:
        assert role_fit(None, "context,plan") is None

    def test_empty_list_returns_none(self) -> None:
        assert role_fit([], "context") is None

    def test_full_overlap_returns_one(self) -> None:
        assert role_fit(
            [StorylineRole.CONTEXT, StorylineRole.PLAN], "context,plan"
        ) == 1.0

    def test_partial_overlap_returns_fraction(self) -> None:
        result = role_fit([StorylineRole.CONTEXT, StorylineRole.PLAN], "context")
        assert abs(result - 0.5) < 1e-9

    def test_no_overlap_returns_zero(self) -> None:
        assert role_fit([StorylineRole.DIAGNOSIS], "context,plan") == 0.0

    def test_single_role_match_returns_one(self) -> None:
        assert role_fit([StorylineRole.CONTEXT], "context") == 1.0

    def test_candidate_superset_of_requested_returns_one(self) -> None:
        assert role_fit(
            [StorylineRole.CONTEXT], "context,plan,diagnosis"
        ) == 1.0


# ---------------------------------------------------------------------------
# density_fit
# ---------------------------------------------------------------------------


class TestDensityFit:
    def test_none_requested_returns_none(self) -> None:
        assert density_fit(None, "high") is None

    def test_match_returns_one(self) -> None:
        assert density_fit(DensityLevel.HIGH, "high") == 1.0

    def test_mismatch_returns_zero(self) -> None:
        assert density_fit(DensityLevel.HIGH, "low") == 0.0

    def test_medium_match(self) -> None:
        assert density_fit(DensityLevel.MEDIUM, "medium") == 1.0


# ---------------------------------------------------------------------------
# compute_hybrid_score — renormalization
# ---------------------------------------------------------------------------


class TestComputeHybridScore:
    def test_query_text_only_equals_semantic(self) -> None:
        score = compute_hybrid_score(0.7, None, None, None, None, None)
        assert abs(score - 0.7) < 1e-9

    def test_all_ones_returns_one(self) -> None:
        score = compute_hybrid_score(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        assert abs(score - 1.0) < 1e-9

    def test_all_zeros_returns_zero(self) -> None:
        score = compute_hybrid_score(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert score == 0.0

    def test_semantic_plus_job_renormalized(self) -> None:
        w = DEFAULT_WEIGHTS
        expected = (0.8 * w.semantic + 1.0 * w.communication_job) / (w.semantic + w.communication_job)
        result = compute_hybrid_score(0.8, None, 1.0, None, None, None)
        assert abs(result - expected) < 1e-9

    def test_semantic_plus_function_renormalized(self) -> None:
        w = DEFAULT_WEIGHTS
        expected = (0.6 * w.semantic + 0.0 * w.slide_function) / (w.semantic + w.slide_function)
        result = compute_hybrid_score(0.6, 0.0, None, None, None, None)
        assert abs(result - expected) < 1e-9

    def test_high_semantic_job_match_beats_low_semantic_job_miss(self) -> None:
        high_match = compute_hybrid_score(0.8, None, 1.0, None, None, None)
        low_miss = compute_hybrid_score(0.9, None, 0.0, None, None, None)
        assert high_match > low_miss

    def test_custom_weights(self) -> None:
        w = HybridRetrievalWeights(
            semantic=0.9, communication_job=0.05, visual_archetype=0.02,
            slide_function=0.01, storyline_role=0.01, density=0.01,
        )
        score = compute_hybrid_score(0.5, None, 1.0, None, None, None, w)
        expected = (0.5 * 0.9 + 1.0 * 0.05) / (0.9 + 0.05)
        assert abs(score - expected) < 1e-9

    def test_renormalization_excludes_none_dimensions(self) -> None:
        w = DEFAULT_WEIGHTS
        score = compute_hybrid_score(1.0, None, None, 1.0, None, 1.0)
        expected = (
            1.0 * w.semantic + 1.0 * w.visual_archetype + 1.0 * w.density
        ) / (w.semantic + w.visual_archetype + w.density)
        assert abs(score - expected) < 1e-9
