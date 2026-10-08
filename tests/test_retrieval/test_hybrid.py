"""Tests for HybridSlideSearch and HybridSlideSearchResult."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)
from slidestein.retrieval.hybrid import HybridSlideSearch, HybridSlideSearchResult
from slidestein.retrieval.request import SlideRetrievalRequest
from slidestein.retrieval.scoring import HybridRetrievalWeights


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_provider(vec: list[float] | None = None) -> MagicMock:
    provider = MagicMock()
    provider.embed_query.return_value = vec if vec is not None else [0.1] * 10
    return provider


def _row(
    slide_id: str = "s1",
    deck_id: str = "deck-01",
    slide_number: int = 1,
    distance: float = 0.40,
    func: str = "content",
    job: str = "summarise",
    secondary_jobs: str = "",
    archetype: str = "structured_one_pager",
    roles: str = "context,plan",
    density: str = "high",
    desc: str = "A slide.",
) -> dict:
    return {
        "slide_id": slide_id,
        "deck_id": deck_id,
        "slide_number": slide_number,
        "_distance": distance,
        "slide_function": func,
        "primary_communication_job": job,
        "secondary_communication_jobs": secondary_jobs,
        "storyline_roles": roles,
        "visual_archetype": archetype,
        "density": density,
        "description": desc,
    }


def _mock_store(rows: list[dict]) -> MagicMock:
    store = MagicMock()
    store.search_cosine.return_value = rows
    return store


def _search(
    rows: list[dict],
    request: SlideRetrievalRequest | None = None,
    weights: HybridRetrievalWeights | None = None,
) -> list[HybridSlideSearchResult]:
    if request is None:
        request = SlideRetrievalRequest(query_text="test query")
    provider = _mock_provider()
    store = _mock_store(rows)
    searcher = HybridSlideSearch(provider=provider, store=store, weights=weights)
    return searcher.search(request)


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------


class TestHybridSearchBasic:
    def test_empty_store_returns_empty(self) -> None:
        results = _search([])
        assert results == []

    def test_returns_list_of_results(self) -> None:
        results = _search([_row()])
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], HybridSlideSearchResult)

    def test_rank_starts_at_one(self) -> None:
        results = _search([_row("s1"), _row("s2", slide_number=2)])
        assert results[0].rank == 1

    def test_ranks_are_sequential(self) -> None:
        results = _search([_row(f"s{i}", slide_number=i) for i in range(1, 4)])
        assert [r.rank for r in results] == [1, 2, 3]

    def test_top_k_limits_results(self) -> None:
        req = SlideRetrievalRequest(query_text="test", top_k=2)
        rows = [_row(f"s{i}", slide_number=i, distance=0.1 * i) for i in range(1, 6)]
        results = _search(rows, request=req)
        assert len(results) == 2

    def test_candidate_pool_requested_from_store(self) -> None:
        req = SlideRetrievalRequest(query_text="test", top_k=3)
        provider = _mock_provider()
        store = _mock_store([])
        HybridSlideSearch(provider=provider, store=store).search(req)
        call_kwargs = store.search_cosine.call_args
        # candidate_k = max(3 * 5, 25) = 25
        assert call_kwargs[1]["top_k"] == 25 or call_kwargs[0][1] == 25

    def test_candidate_pool_minimum_25(self) -> None:
        req = SlideRetrievalRequest(query_text="test", top_k=1)
        provider = _mock_provider()
        store = _mock_store([])
        HybridSlideSearch(provider=provider, store=store).search(req)
        call_kwargs = store.search_cosine.call_args
        used_k = call_kwargs[1].get("top_k") or call_kwargs[0][1]
        assert used_k >= 25


# ---------------------------------------------------------------------------
# Query-text-only parity (M4.2 §20 regression)
# ---------------------------------------------------------------------------


class TestQueryTextOnlyParity:
    def test_query_text_only_ranking_matches_semantic_order(self) -> None:
        """With no structured dimensions, hybrid rank must equal semantic rank."""
        rows = [
            _row("s1", distance=0.30, slide_number=1),
            _row("s2", distance=0.45, slide_number=2),
            _row("s3", distance=0.60, slide_number=3),
        ]
        req = SlideRetrievalRequest(query_text="any query")
        results = _search(rows, request=req)
        # Should be ordered s1 > s2 > s3 (same as ascending distance)
        assert [r.slide_id for r in results] == ["s1", "s2", "s3"]

    def test_query_text_only_scores_equal_semantic_score(self) -> None:
        """Hybrid score == semantic score when no structured dimensions requested."""
        rows = [_row("s1", distance=0.40)]
        req = SlideRetrievalRequest(query_text="any query")
        results = _search(rows, request=req)
        r = results[0]
        assert abs(r.hybrid_score - r.semantic_score) < 1e-9
        assert abs(r.semantic_score - (1.0 - 0.40)) < 1e-9

    def test_all_fit_fields_none_for_text_only(self) -> None:
        rows = [_row("s1")]
        req = SlideRetrievalRequest(query_text="any query")
        results = _search(rows, request=req)
        r = results[0]
        assert r.slide_function_fit is None
        assert r.communication_job_fit is None
        assert r.visual_archetype_fit is None
        assert r.storyline_role_fit is None
        assert r.density_fit is None


# ---------------------------------------------------------------------------
# Job scoring
# ---------------------------------------------------------------------------


class TestJobScoring:
    def test_primary_job_match_boosts_rank(self) -> None:
        rows = [
            _row("s_nomatch", distance=0.30, job="explain", slide_number=1),
            _row("s_match", distance=0.45, job="summarise", slide_number=2),
        ]
        req = SlideRetrievalRequest(query_text="test", primary_communication_job=CommunicationJob.SUMMARISE)
        results = _search(rows, request=req)
        # s_match has lower semantic score but job match should flip ranking
        assert results[0].slide_id == "s_match"

    def test_secondary_job_match_partial_boost(self) -> None:
        rows = [
            _row("s_primary", distance=0.40, job="summarise", secondary_jobs="", slide_number=1),
            _row("s_secondary", distance=0.40, job="explain", secondary_jobs="summarise", slide_number=2),
        ]
        req = SlideRetrievalRequest(query_text="test", primary_communication_job=CommunicationJob.SUMMARISE)
        results = _search(rows, request=req)
        # Primary match > secondary match at same distance
        assert results[0].slide_id == "s_primary"
        assert results[1].slide_id == "s_secondary"

    def test_job_fit_returned_in_result(self) -> None:
        rows = [_row("s1", job="summarise")]
        req = SlideRetrievalRequest(query_text="test", primary_communication_job=CommunicationJob.SUMMARISE)
        results = _search(rows, request=req)
        assert results[0].communication_job_fit == 1.0


# ---------------------------------------------------------------------------
# Strict function filter
# ---------------------------------------------------------------------------


class TestStrictFunctionFilter:
    def test_strict_filter_excludes_nonmatching(self) -> None:
        rows = [
            _row("s_cover", func="cover", slide_number=1, distance=0.30),
            _row("s_content", func="content", slide_number=2, distance=0.45),
        ]
        req = SlideRetrievalRequest(
            query_text="test",
            slide_function=SlideFunction.CONTENT,
            strict_slide_function=True,
        )
        results = _search(rows, request=req)
        assert all(r.slide_function == "content" for r in results)
        assert len(results) == 1

    def test_non_strict_keeps_all(self) -> None:
        rows = [
            _row("s_cover", func="cover", slide_number=1, distance=0.30),
            _row("s_content", func="content", slide_number=2, distance=0.45),
        ]
        req = SlideRetrievalRequest(
            query_text="test",
            slide_function=SlideFunction.CONTENT,
            strict_slide_function=False,
        )
        results = _search(rows, request=req)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Archetype scoring
# ---------------------------------------------------------------------------


class TestArchetypeScoring:
    def test_archetype_match_boosts_score(self) -> None:
        rows = [
            _row("s_nomatch", archetype="structured_one_pager", distance=0.30, slide_number=1),
            _row("s_match", archetype="table", distance=0.45, slide_number=2),
        ]
        req = SlideRetrievalRequest(
            query_text="test", preferred_visual_archetypes=[VisualArchetype.TABLE]
        )
        results = _search(rows, request=req)
        assert results[0].slide_id == "s_match"

    def test_archetype_fit_populated(self) -> None:
        rows = [_row("s1", archetype="table")]
        req = SlideRetrievalRequest(query_text="test", preferred_visual_archetypes=[VisualArchetype.TABLE])
        results = _search(rows, request=req)
        assert results[0].visual_archetype_fit == 1.0


# ---------------------------------------------------------------------------
# Role scoring
# ---------------------------------------------------------------------------


class TestRoleScoring:
    def test_full_role_overlap_higher_score(self) -> None:
        # s_partial: context only (role_fit=0.5), closer semantically (dist=0.40)
        # s_full: context+plan (role_fit=1.0), slightly farther (dist=0.41)
        # With default weights role=0.05, semantic=0.55:
        # s_partial hybrid = (0.60*0.55 + 0.5*0.05) / (0.55+0.05) = 0.5917
        # s_full    hybrid = (0.59*0.55 + 1.0*0.05) / (0.55+0.05) = 0.6242 → wins
        rows = [
            _row("s_partial", roles="context", distance=0.40, slide_number=1),
            _row("s_full", roles="context,plan", distance=0.41, slide_number=2),
        ]
        req = SlideRetrievalRequest(
            query_text="test",
            storyline_roles=[StorylineRole.CONTEXT, StorylineRole.PLAN],
        )
        results = _search(rows, request=req)
        assert results[0].slide_id == "s_full"

    def test_role_fit_populated(self) -> None:
        rows = [_row("s1", roles="context,plan")]
        req = SlideRetrievalRequest(
            query_text="test",
            storyline_roles=[StorylineRole.CONTEXT, StorylineRole.PLAN],
        )
        results = _search(rows, request=req)
        assert results[0].storyline_role_fit == 1.0


# ---------------------------------------------------------------------------
# Density scoring
# ---------------------------------------------------------------------------


class TestDensityScoring:
    def test_density_match_fit_one(self) -> None:
        rows = [_row("s1", density="high")]
        req = SlideRetrievalRequest(query_text="test", density=DensityLevel.HIGH)
        results = _search(rows, request=req)
        assert results[0].density_fit == 1.0

    def test_density_mismatch_fit_zero(self) -> None:
        rows = [_row("s1", density="low")]
        req = SlideRetrievalRequest(query_text="test", density=DensityLevel.HIGH)
        results = _search(rows, request=req)
        assert results[0].density_fit == 0.0


# ---------------------------------------------------------------------------
# Result fields
# ---------------------------------------------------------------------------


class TestResultFields:
    def test_slide_metadata_populated(self) -> None:
        rows = [_row("slide-001", deck_id="deck-99", slide_number=7, distance=0.42,
                     func="content", job="explain", archetype="title",
                     roles="context", density="low", desc="Test description")]
        req = SlideRetrievalRequest(query_text="test")
        results = _search(rows, request=req)
        r = results[0]
        assert r.slide_id == "slide-001"
        assert r.deck_id == "deck-99"
        assert r.slide_number == 7
        assert abs(r.semantic_distance - 0.42) < 1e-9
        assert r.slide_function == "content"
        assert r.primary_communication_job == "explain"
        assert r.visual_archetype == "title"
        assert r.storyline_roles == "context"
        assert r.density == "low"
        assert r.description == "Test description"

    def test_secondary_jobs_populated(self) -> None:
        rows = [_row("s1", secondary_jobs="show_timeline,explain")]
        req = SlideRetrievalRequest(query_text="test")
        results = _search(rows, request=req)
        assert results[0].secondary_communication_jobs == "show_timeline,explain"


# ---------------------------------------------------------------------------
# Provider call
# ---------------------------------------------------------------------------


class TestProviderCall:
    def test_provider_called_once_per_search(self) -> None:
        req = SlideRetrievalRequest(query_text="test query")
        provider = _mock_provider()
        store = _mock_store([_row()])
        HybridSlideSearch(provider=provider, store=store).search(req)
        provider.embed_query.assert_called_once()

    def test_enriched_query_used_for_embedding(self) -> None:
        req = SlideRetrievalRequest(
            query_text="base query",
            required_content_elements=["team", "objective"],
        )
        provider = _mock_provider()
        store = _mock_store([])
        HybridSlideSearch(provider=provider, store=store).search(req)
        call_arg = provider.embed_query.call_args[0][0]
        assert "- team" in call_arg
        assert "- objective" in call_arg
