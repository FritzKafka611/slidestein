"""Tests for SemanticSlideSearch.

Uses mocks for EmbeddingProvider and SlideVectorStore.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.retrieval.search import SemanticSlideSearch, SlideSearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_provider(vec: list[float] | None = None) -> MagicMock:
    provider = MagicMock()
    provider.embed_query.return_value = vec if vec is not None else [0.1, 0.2, 0.3, 0.4]
    return provider


def _row(
    slide_id: str = "s1",
    deck_id: str = "deck-01",
    slide_number: int = 1,
    distance: float = 0.05,
    job: str = "summarise",
    func: str = "content",
    archetype: str = "structured_one_pager",
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
        "visual_archetype": archetype,
        "density": density,
        "description": desc,
    }


def _mock_store(rows: list[dict]) -> MagicMock:
    store = MagicMock()
    store.search_cosine.return_value = rows
    return store


def _search(rows: list[dict], query: str = "test query", top_k: int = 5) -> list[SlideSearchResult]:
    provider = _mock_provider()
    store = _mock_store(rows)
    return SemanticSlideSearch(provider, store).search(query, top_k=top_k)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_blank_query_raises_value_error(self) -> None:
        searcher = SemanticSlideSearch(_mock_provider(), _mock_store([]))
        with pytest.raises(ValueError, match="blank"):
            searcher.search("   ")

    def test_empty_query_raises_value_error(self) -> None:
        searcher = SemanticSlideSearch(_mock_provider(), _mock_store([]))
        with pytest.raises(ValueError, match="blank"):
            searcher.search("")

    def test_zero_top_k_raises_value_error(self) -> None:
        searcher = SemanticSlideSearch(_mock_provider(), _mock_store([]))
        with pytest.raises(ValueError, match="top_k"):
            searcher.search("query", top_k=0)

    def test_negative_top_k_raises_value_error(self) -> None:
        searcher = SemanticSlideSearch(_mock_provider(), _mock_store([]))
        with pytest.raises(ValueError, match="top_k"):
            searcher.search("query", top_k=-1)


# ---------------------------------------------------------------------------
# Basic results
# ---------------------------------------------------------------------------


class TestBasicResults:
    def test_empty_store_returns_empty_list(self) -> None:
        results = _search([])
        assert results == []

    def test_returns_slide_search_results(self) -> None:
        results = _search([_row()])
        assert all(isinstance(r, SlideSearchResult) for r in results)

    def test_result_count_matches_row_count(self) -> None:
        results = _search([_row(slide_id=f"s{i}") for i in range(3)])
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_ranks_are_one_indexed(self) -> None:
        results = _search([_row(slide_id="a"), _row(slide_id="b")])
        assert [r.rank for r in results] == [1, 2]

    def test_order_follows_store_order(self) -> None:
        """Store returns rows pre-sorted by cosine distance; search preserves order."""
        rows = [
            _row(slide_id="closest", distance=0.01),
            _row(slide_id="middle", distance=0.20),
            _row(slide_id="farthest", distance=0.40),
        ]
        results = _search(rows)
        assert results[0].slide_id == "closest"
        assert results[1].slide_id == "middle"
        assert results[2].slide_id == "farthest"


# ---------------------------------------------------------------------------
# top_k passed to store
# ---------------------------------------------------------------------------


class TestTopK:
    def test_top_k_passed_to_store(self) -> None:
        provider = _mock_provider()
        store = _mock_store([])
        SemanticSlideSearch(provider, store).search("query", top_k=3)
        store.search_cosine.assert_called_once()
        _, kwargs = store.search_cosine.call_args
        assert kwargs.get("top_k") == 3 or store.search_cosine.call_args[0][1] == 3


# ---------------------------------------------------------------------------
# primary_communication_job mapping
# ---------------------------------------------------------------------------


class TestJobMapping:
    def test_non_empty_job_string_preserved(self) -> None:
        results = _search([_row(job="summarise")])
        assert results[0].primary_communication_job == "summarise"

    def test_empty_job_string_maps_to_none(self) -> None:
        results = _search([_row(job="")])
        assert results[0].primary_communication_job is None

    def test_none_job_value_maps_to_none(self) -> None:
        row = _row()
        row["primary_communication_job"] = None
        results = _search([row])
        assert results[0].primary_communication_job is None


# ---------------------------------------------------------------------------
# active_only forwarded to store
# ---------------------------------------------------------------------------


class TestActiveOnly:
    def test_active_only_true_by_default(self) -> None:
        provider = _mock_provider()
        store = _mock_store([])
        SemanticSlideSearch(provider, store).search("query")
        _, kwargs = store.search_cosine.call_args
        # active_only must be True (passed as kwarg or positional)
        active_only = kwargs.get("active_only", store.search_cosine.call_args[0][2] if len(store.search_cosine.call_args[0]) > 2 else True)
        assert active_only is True


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


class TestFieldMapping:
    def test_all_fields_mapped(self) -> None:
        results = _search([_row(
            slide_id="s42",
            deck_id="deck-99",
            slide_number=5,
            distance=0.123,
            func="section_divider",
            archetype="title",
            density="low",
            desc="A section break.",
        )])
        r = results[0]
        assert r.slide_id == "s42"
        assert r.deck_id == "deck-99"
        assert r.slide_number == 5
        assert abs(r.distance - 0.123) < 1e-6
        assert r.slide_function == "section_divider"
        assert r.visual_archetype == "title"
        assert r.density == "low"
        assert r.description == "A section break."
