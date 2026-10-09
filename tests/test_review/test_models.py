"""Tests for review/models.py — domain model validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.review.models import (
    DimensionAssessment,
    ManagerReviewIssue,
    ManagerReviewModelOutput,
    ManagerReviewRequest,
)
from tests.test_review.conftest import make_factual_flag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dim(score: int = 4, rationale: str = "Looks good.") -> DimensionAssessment:
    return DimensionAssessment(score=score, rationale=rationale)


def _valid_output() -> dict:
    dim = {"score": 4, "rationale": "Good."}
    return {
        "recommendation": "approve",
        "answer_first_title": dim,
        "core_message_clarity": dim,
        "vertical_logic": dim,
        "exhibit_title_consistency": dim,
        "mece_structure": dim,
        "content_density": dim,
        "executive_summary": "Overall a solid draft.",
    }


# ---------------------------------------------------------------------------
# DimensionAssessment
# ---------------------------------------------------------------------------


def test_dimension_score_1_accepted() -> None:
    d = DimensionAssessment(score=1, rationale="Poor.")
    assert d.score == 1


def test_dimension_score_5_accepted() -> None:
    d = DimensionAssessment(score=5, rationale="Excellent.")
    assert d.score == 5


def test_dimension_score_3_accepted() -> None:
    d = DimensionAssessment(score=3, rationale="Adequate.")
    assert d.score == 3


def test_dimension_score_0_rejected() -> None:
    with pytest.raises(ValidationError, match="score must be between 1 and 5"):
        DimensionAssessment(score=0, rationale="x")


def test_dimension_score_6_rejected() -> None:
    with pytest.raises(ValidationError, match="score must be between 1 and 5"):
        DimensionAssessment(score=6, rationale="x")


def test_dimension_blank_rationale_rejected() -> None:
    with pytest.raises(ValidationError, match="rationale must not be blank"):
        DimensionAssessment(score=3, rationale="   ")


def test_dimension_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        DimensionAssessment(score=3, rationale="x", extra_field="bad")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ManagerReviewIssue
# ---------------------------------------------------------------------------


def test_issue_critical_accepted() -> None:
    issue = ManagerReviewIssue(
        severity="critical",
        category="answer_first_title",
        issue="Title is purely descriptive.",
        recommendation="Rewrite as an insight statement.",
    )
    assert issue.severity == "critical"


def test_issue_major_accepted() -> None:
    issue = ManagerReviewIssue(
        severity="major",
        category="mece_structure",
        issue="Overlap in buckets 2 and 3.",
        recommendation="Merge or reframe.",
    )
    assert issue.severity == "major"


def test_issue_minor_accepted() -> None:
    issue = ManagerReviewIssue(
        severity="minor",
        category="content_density",
        issue="One bullet is slightly redundant.",
        recommendation="Remove the redundant bullet.",
    )
    assert issue.severity == "minor"


def test_issue_invalid_severity_rejected() -> None:
    with pytest.raises(ValidationError):
        ManagerReviewIssue(
            severity="blocker",  # type: ignore[arg-type]
            category="mece_structure",
            issue="x",
            recommendation="x",
        )


def test_issue_invalid_category_rejected() -> None:
    with pytest.raises(ValidationError):
        ManagerReviewIssue(
            severity="major",
            category="unknown_dim",  # type: ignore[arg-type]
            issue="x",
            recommendation="x",
        )


def test_issue_factual_grounding_category_accepted() -> None:
    issue = ManagerReviewIssue(
        severity="major",
        category="factual_grounding",
        issue="Claim not in source material.",
        recommendation="Remove or cite source.",
    )
    assert issue.category == "factual_grounding"


def test_issue_blank_issue_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        ManagerReviewIssue(
            severity="minor",
            category="content_density",
            issue="",
            recommendation="Fix it.",
        )


def test_issue_blank_recommendation_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        ManagerReviewIssue(
            severity="minor",
            category="content_density",
            issue="Problem.",
            recommendation="  ",
        )


def test_issue_slot_keys_default_empty() -> None:
    issue = ManagerReviewIssue(
        severity="minor",
        category="content_density",
        issue="Too long.",
        recommendation="Trim.",
    )
    assert issue.slot_keys == []


def test_issue_slot_keys_accepted() -> None:
    issue = ManagerReviewIssue(
        severity="major",
        category="core_message_clarity",
        slot_keys=["K1", "K3"],
        issue="Conflicting messages.",
        recommendation="Align K1 and K3.",
    )
    assert issue.slot_keys == ["K1", "K3"]


# ---------------------------------------------------------------------------
# ManagerReviewModelOutput — factual_flags as list[ManagerReviewIssue]
# ---------------------------------------------------------------------------


def test_model_output_valid_approve() -> None:
    data = _valid_output()
    output = ManagerReviewModelOutput.model_validate(data)
    assert output.recommendation == "approve"


def test_model_output_valid_revise() -> None:
    data = _valid_output()
    data["recommendation"] = "revise"
    output = ManagerReviewModelOutput.model_validate(data)
    assert output.recommendation == "revise"


def test_model_output_invalid_recommendation() -> None:
    data = _valid_output()
    data["recommendation"] = "reject"
    with pytest.raises(ValidationError):
        ManagerReviewModelOutput.model_validate(data)


def test_model_output_blank_executive_summary_rejected() -> None:
    data = _valid_output()
    data["executive_summary"] = ""
    with pytest.raises(ValidationError, match="executive_summary must not be blank"):
        ManagerReviewModelOutput.model_validate(data)


def test_model_output_extra_fields_forbidden() -> None:
    data = _valid_output()
    data["surprise_field"] = "bad"
    with pytest.raises(ValidationError):
        ManagerReviewModelOutput.model_validate(data)


def test_model_output_issues_default_empty() -> None:
    output = ManagerReviewModelOutput.model_validate(_valid_output())
    assert output.issues == []


def test_model_output_factual_flags_default_empty() -> None:
    output = ManagerReviewModelOutput.model_validate(_valid_output())
    assert output.factual_flags == []


def test_factual_flags_must_be_grounding_category() -> None:
    """factual_flags item with category != factual_grounding is rejected."""
    data = _valid_output()
    data["factual_flags"] = [
        {
            "severity": "minor",
            "category": "core_message_clarity",  # wrong
            "slot_keys": [],
            "issue": "Some issue.",
            "recommendation": "Fix it.",
        }
    ]
    with pytest.raises(ValidationError, match="factual_grounding"):
        ManagerReviewModelOutput.model_validate(data)


def test_factual_flags_grounding_category_accepted() -> None:
    """factual_flags item with category=factual_grounding is accepted."""
    data = _valid_output()
    data["factual_flags"] = [
        {
            "severity": "major",
            "category": "factual_grounding",
            "slot_keys": ["K1"],
            "issue": "Claim not supported by source.",
            "recommendation": "Remove or cite.",
        }
    ]
    output = ManagerReviewModelOutput.model_validate(data)
    assert len(output.factual_flags) == 1
    assert output.factual_flags[0].category == "factual_grounding"


def test_factual_flags_is_manager_review_issue_type() -> None:
    """factual_flags items are ManagerReviewIssue objects, not strings."""
    data = _valid_output()
    data["factual_flags"] = [
        {
            "severity": "minor",
            "category": "factual_grounding",
            "slot_keys": [],
            "issue": "Metric not in source.",
            "recommendation": "Remove.",
        }
    ]
    output = ManagerReviewModelOutput.model_validate(data)
    from slidestein.review.models import ManagerReviewIssue
    assert isinstance(output.factual_flags[0], ManagerReviewIssue)


# ---------------------------------------------------------------------------
# ManagerReviewRequest
# ---------------------------------------------------------------------------


def test_request_does_not_reject_incomplete_draft(
    make_complete_review_request,
) -> None:
    """ManagerReviewRequest accepts is_complete=False — service validates, not model."""
    req = make_complete_review_request(is_complete=False)
    assert req.draft.is_complete is False


def test_request_accepts_complete_draft(make_complete_review_request) -> None:
    req = make_complete_review_request(is_complete=True)
    assert req.draft.is_complete is True
