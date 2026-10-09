"""Tests for ManagerReviewService — end-to-end with mock reviewer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.review.errors import ManagerReviewError
from slidestein.review.models import (
    ManagerReviewIssue,
    ManagerReviewRequest,
)
from slidestein.review.providers.sap_aicore import ManagerReviewGenerationError
from slidestein.review.service import ManagerReviewService
from tests.test_review.conftest import (
    make_brief,
    make_complete_draft,
    make_factual_flag,
    make_model_output,
    make_slot_map,
)


def _make_service(mock_output=None):
    reviewer = MagicMock()
    reviewer.review.return_value = mock_output or make_model_output()
    return ManagerReviewService(reviewer=reviewer), reviewer


def test_happy_path_reviewer_called_once() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    svc.review(req)
    reviewer.review.assert_called_once()


def test_average_score_computed_correctly() -> None:
    # Scores: 5, 3, 4, 2, 5, 3 → sum=22 → avg=22/6≈3.6667
    output = make_model_output(
        recommendation="revise",
        scores={
            "answer_first_title": 5,
            "core_message_clarity": 3,
            "vertical_logic": 4,
            "exhibit_title_consistency": 2,
            "mece_structure": 5,
            "content_density": 3,
        },
    )
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert result.average_score == pytest.approx(22 / 6, abs=1e-4)


def test_average_score_all_fives() -> None:
    output = make_model_output(
        scores={k: 5 for k in [
            "answer_first_title", "core_message_clarity", "vertical_logic",
            "exhibit_title_consistency", "mece_structure", "content_density",
        ]},
    )
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert result.average_score == 5.0


def test_six_dimensions_copied_to_result() -> None:
    svc, _ = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert result.answer_first_title.score == 4
    assert result.core_message_clarity.score == 4
    assert result.vertical_logic.score == 4
    assert result.exhibit_title_consistency.score == 4
    assert result.mece_structure.score == 4
    assert result.content_density.score == 4


def test_issues_propagated() -> None:
    issue = ManagerReviewIssue(
        severity="major", category="mece_structure",
        issue="Overlap.", recommendation="Fix overlap.",
    )
    output = make_model_output(issues=[issue])
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert len(result.issues) == 1
    assert result.issues[0].severity == "major"


def test_factual_flags_propagated() -> None:
    flag = make_factual_flag("Unverified claim about revenue.")
    output = make_model_output(factual_flags=[flag])
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert len(result.factual_flags) == 1
    assert "Unverified claim about revenue." in result.factual_flags[0].issue


def test_factual_flags_are_manager_review_issue_objects() -> None:
    flag = make_factual_flag()
    output = make_model_output(factual_flags=[flag])
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert isinstance(result.factual_flags[0], ManagerReviewIssue)
    assert result.factual_flags[0].category == "factual_grounding"


def test_executive_summary_propagated() -> None:
    output = make_model_output(executive_summary="Excellent strategic clarity.")
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert result.executive_summary == "Excellent strategic clarity."


def test_result_has_slide_identity() -> None:
    svc, _ = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    result = svc.review(req)
    assert result.slide_id == "slide-test"
    assert result.slide_number == 2
    assert result.deck_id is None


def test_generation_error_propagates_unmodified() -> None:
    reviewer = MagicMock()
    reviewer.review.side_effect = ManagerReviewGenerationError("API call failed")
    svc = ManagerReviewService(reviewer=reviewer)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    with pytest.raises(ManagerReviewGenerationError, match="API call failed"):
        svc.review(req)


def test_unknown_slot_key_in_issue_raises_review_error() -> None:
    issue = ManagerReviewIssue(
        severity="minor", category="content_density",
        slot_keys=["K999"], issue="x", recommendation="y",
    )
    output = make_model_output(issues=[issue])
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    with pytest.raises(ManagerReviewError, match="K999"):
        svc.review(req)


def test_unknown_slot_key_in_factual_flag_raises_review_error() -> None:
    flag = make_factual_flag(slot_keys=["K999"])
    output = make_model_output(factual_flags=[flag])
    svc, _ = _make_service(mock_output=output)
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    with pytest.raises(ManagerReviewError, match="K999"):
        svc.review(req)


def test_source_material_none_passed_to_reviewer() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map(), source_material=None)
    svc.review(req)
    call_args = reviewer.review.call_args
    assert call_args[0][1] is None


def test_source_material_text_passed_to_reviewer() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material="Revenue data here.",
    )
    svc.review(req)
    call_args = reviewer.review.call_args
    assert call_args[0][1] == "Revenue data here."


def test_slot_review_specs_contains_correct_actions() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    svc.review(req)
    specs = reviewer.review.call_args[0][2]
    actions = {s["key"]: s["action"] for s in specs}
    assert all(v == "replace" for v in actions.values())


def test_slot_review_specs_include_capacity_data() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    svc.review(req)
    specs = reviewer.review.call_args[0][2]
    for spec in specs:
        assert "character_count" in spec
        assert "capacity_characters" in spec
        assert "capacity_utilization" in spec
        assert "explicit_line_count" in spec
        assert "max_lines_estimate" in spec


def test_group_descriptions_passed_to_reviewer() -> None:
    svc, reviewer = _make_service()
    req = ManagerReviewRequest(brief=make_brief(), draft=make_complete_draft(), slot_map=make_slot_map())
    svc.review(req)
    # 4th positional arg is group_descriptions
    call_args = reviewer.review.call_args
    group_descs = call_args[0][3]
    assert isinstance(group_descs, list)
