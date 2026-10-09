"""Tests for ManagerReviewResult — schema_version, prompt_version, average_score,
slide identity fields."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from slidestein.review.models import DimensionAssessment, ManagerReviewResult
from slidestein.review.versions import (
    MANAGER_REVIEW_PROMPT_VERSION,
    MANAGER_REVIEW_SCHEMA_VERSION,
)


def _dim(score: int = 4) -> DimensionAssessment:
    return DimensionAssessment(score=score, rationale="OK.")


def _make_result(**kwargs) -> ManagerReviewResult:
    defaults = dict(
        slide_id="slide-test",
        deck_id=None,
        slide_number=2,
        recommendation="approve",
        average_score=4.0,
        answer_first_title=_dim(4),
        core_message_clarity=_dim(4),
        vertical_logic=_dim(4),
        exhibit_title_consistency=_dim(4),
        mece_structure=_dim(4),
        content_density=_dim(4),
        executive_summary="Strong draft overall.",
    )
    defaults.update(kwargs)
    return ManagerReviewResult(**defaults)  # type: ignore[arg-type]


def test_schema_version_default() -> None:
    result = _make_result()
    assert result.schema_version == MANAGER_REVIEW_SCHEMA_VERSION


def test_prompt_version_default() -> None:
    result = _make_result()
    assert result.prompt_version == MANAGER_REVIEW_PROMPT_VERSION


def test_schema_version_is_1_1() -> None:
    assert MANAGER_REVIEW_SCHEMA_VERSION == "1.1"


def test_prompt_version_is_1_1() -> None:
    assert MANAGER_REVIEW_PROMPT_VERSION == "1.1"


def test_average_score_is_float() -> None:
    result = _make_result(average_score=3.5)
    assert isinstance(result.average_score, float)


def test_slide_id_stored() -> None:
    result = _make_result(slide_id="abc-123")
    assert result.slide_id == "abc-123"


def test_slide_number_stored() -> None:
    result = _make_result(slide_number=7)
    assert result.slide_number == 7


def test_deck_id_optional() -> None:
    result = _make_result(deck_id=None)
    assert result.deck_id is None
    result2 = _make_result(deck_id="deck-xyz")
    assert result2.deck_id == "deck-xyz"


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        ManagerReviewResult(  # type: ignore[call-arg]
            slide_id="s",
            slide_number=1,
            recommendation="approve",
            average_score=4.0,
            answer_first_title=_dim(),
            core_message_clarity=_dim(),
            vertical_logic=_dim(),
            exhibit_title_consistency=_dim(),
            mece_structure=_dim(),
            content_density=_dim(),
            executive_summary="Good.",
            unexpected_field="x",
        )


def test_json_round_trip() -> None:
    result = _make_result(average_score=3.6667, slide_id="s-round", slide_number=3)
    data = json.loads(result.model_dump_json())
    assert data["schema_version"] == MANAGER_REVIEW_SCHEMA_VERSION
    assert data["prompt_version"] == MANAGER_REVIEW_PROMPT_VERSION
    assert data["recommendation"] == "approve"
    assert data["average_score"] == pytest.approx(3.6667, abs=1e-4)
    assert data["executive_summary"] == "Strong draft overall."
    assert data["slide_id"] == "s-round"
    assert data["slide_number"] == 3


def test_issues_default_empty() -> None:
    result = _make_result()
    assert result.issues == []


def test_factual_flags_default_empty() -> None:
    result = _make_result()
    assert result.factual_flags == []


def test_recommendation_revise_accepted() -> None:
    result = _make_result(recommendation="revise", average_score=2.5)
    assert result.recommendation == "revise"
