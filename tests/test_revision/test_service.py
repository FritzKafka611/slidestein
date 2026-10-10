"""Tests for ContentRevisionService and BoundedRevisionOrchestrator (v1.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.drafting.models import SlotDraftAction
from slidestein.revision.errors import RevisionError, RevisionExecutionError
from slidestein.revision.models import (
    ContentRevisionModelOutput,
    ContentRevisionResult,
    RevisionChange,
    RevisionPlan,
    RevisionRoute,
)
from slidestein.revision.service import ContentRevisionService
from tests.test_revision.conftest import (
    make_brief,
    make_complete_draft,
    make_slot_map,
)


def make_revision_plan(target_slot_keys: list[str] = None) -> RevisionPlan:
    return RevisionPlan(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        route=RevisionRoute.CONTENT_REVISION,
        reasons=["K1 overflow."],
        target_slot_keys=target_slot_keys or ["K1"],
        requires_model_call=True,
    )


def make_mock_reviser(
    changes: list[dict] | None = None,
    change_summary: str = "Tightened.",
    status: str = "revised",
    blocked_reason: str = "Cannot shorten further.",
) -> MagicMock:
    if status == "blocked":
        output = ContentRevisionModelOutput(
            status="blocked",
            changes=[],
            change_summary=change_summary,
            blocked_reason=blocked_reason,
        )
    else:
        if changes is None:
            changes = [{"key": "K1", "action": "replace", "text": "Short title."}]
        output = ContentRevisionModelOutput(
            status="revised",
            changes=[RevisionChange(**c) for c in changes],
            change_summary=change_summary,
        )
    reviser = MagicMock()
    reviser.revise.return_value = output
    return reviser


# ---------------------------------------------------------------------------
# Happy path — patch application
# ---------------------------------------------------------------------------


def test_service_reviser_called_once():
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    reviser.revise.assert_called_once()


def test_service_returns_content_revision_result():
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    assert isinstance(result, ContentRevisionResult)
    assert result.status == "revised"


def test_service_patch_only_changed_key():
    """Unmentioned K2 text must be preserved exactly."""
    original_k2_text = "Channel 1, Channel 2, Channel 3."
    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": "New title."}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    k2_assignment = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-002")
    assert k2_assignment.text == original_k2_text


def test_service_untouched_assignment_model_dump_identical():
    """Every untouched assignment must have identical model_dump before and after."""
    original_draft = make_complete_draft()
    before_k2 = next(a for a in original_draft.assignments if a.slot_id == "slot-002").model_dump()

    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": "New title."}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=original_draft,
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    after_k2 = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-002").model_dump()
    assert before_k2 == after_k2


def test_service_changed_key_has_new_text():
    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": "New title text."}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    k1_assignment = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-001")
    assert k1_assignment.text == "New title text."
    assert k1_assignment.action == SlotDraftAction.REPLACE


def test_service_result_is_complete():
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    assert result.revised_draft.is_complete is True


def test_service_result_slide_identity_preserved():
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    draft = make_complete_draft(slide_id="slide-xyz", deck_id="deck-123")
    result = svc.revise(
        brief=make_brief(),
        draft=draft,
        slot_map=make_slot_map(slide_id="slide-xyz", deck_id="deck-123"),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    assert result.revised_draft.slide_id == "slide-xyz"
    assert result.revised_draft.deck_id == "deck-123"


def test_service_drafting_summary_mentions_m9():
    reviser = make_mock_reviser(change_summary="Tightened K1.")
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    assert "M9" in result.revised_draft.drafting_summary or \
           "revision" in result.revised_draft.drafting_summary.lower()


def test_service_change_summary_propagated():
    reviser = make_mock_reviser(change_summary="Custom summary text.")
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    assert result.change_summary == "Custom summary text."


def test_service_source_material_passed_to_reviser():
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material="Some source material.",
        revision_plan=make_revision_plan(["K1"]),
    )
    call_kwargs = reviser.revise.call_args
    assert call_kwargs.kwargs.get("source_material") == "Some source material." or \
           (call_kwargs.args and "Some source material." in str(call_kwargs.args))


# ---------------------------------------------------------------------------
# Blocked path
# ---------------------------------------------------------------------------


def test_service_blocked_returns_blocked_result():
    reviser = make_mock_reviser(status="blocked", blocked_reason="Text is already minimal.")
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    assert result.status == "blocked"
    assert result.revised_draft is None
    assert result.blocked_reason == "Text is already minimal."


# ---------------------------------------------------------------------------
# Clear patch semantics
# ---------------------------------------------------------------------------


def test_service_clear_change_produces_clear_assignment():
    """action='clear' → CLEAR assignment with text=None and zeroed metrics."""
    reviser = make_mock_reviser(
        changes=[{"key": "K2", "action": "clear", "text": None}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K2"]),
    )
    k2 = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-002")
    assert k2.action == SlotDraftAction.CLEAR
    assert k2.text is None
    assert k2.character_count == 0
    assert k2.capacity_utilization == 0.0
    assert k2.explicit_line_count == 0


def test_service_clear_preserves_identity_fields():
    """CLEAR must preserve slot_id, shape_id, shape_path, slot_role, semantic_label."""
    original_draft = make_complete_draft()
    original_k2 = next(a for a in original_draft.assignments if a.slot_id == "slot-002")

    reviser = make_mock_reviser(
        changes=[{"key": "K2", "action": "clear", "text": None}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=original_draft,
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K2"]),
    )
    k2 = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-002")
    assert k2.slot_id == original_k2.slot_id
    assert k2.shape_id == original_k2.shape_id
    assert k2.shape_path == original_k2.shape_path
    assert k2.slot_role == original_k2.slot_role
    assert k2.semantic_label == original_k2.semantic_label
    assert k2.capacity_characters == original_k2.capacity_characters
    assert k2.max_lines_estimate == original_k2.max_lines_estimate


# ---------------------------------------------------------------------------
# Capacity validation
# ---------------------------------------------------------------------------


def test_service_rejects_text_exceeding_capacity():
    """Revised text longer than max_chars must raise RevisionError."""
    oversized_text = "X" * 200  # slot-001 max_chars = 100
    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": oversized_text}]
    )
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="exceeds capacity"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=make_revision_plan(["K1"]),
        )


def test_service_rejects_text_exceeding_line_limit():
    """Revised text with too many lines must raise RevisionError."""
    many_lines = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"  # 5 lines, max is 2
    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": many_lines}]
    )
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="line limit"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=make_revision_plan(["K1"]),
        )


def test_service_rejects_change_to_unknown_key():
    reviser = make_mock_reviser(
        changes=[{"key": "K99", "action": "replace", "text": "Something."}]
    )
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="unknown key"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=make_revision_plan(["K99"]),
        )


def test_service_rejects_change_outside_target_scope():
    """Change to K2 when plan targets only K1 must raise RevisionError."""
    reviser = make_mock_reviser(
        changes=[{"key": "K2", "action": "replace", "text": "Outside target."}]
    )
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="outside.*target scope"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=make_revision_plan(["K1"]),  # K1 only
        )


def test_service_rejects_duplicate_key_in_changes():
    reviser = make_mock_reviser(
        changes=[
            {"key": "K1", "action": "replace", "text": "First."},
            {"key": "K1", "action": "replace", "text": "Second."},
        ]
    )
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="duplicate"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=make_revision_plan(["K1"]),
        )


def test_service_accepts_text_at_capacity_boundary():
    """Text exactly at max_chars must NOT raise."""
    exact_text = "A" * 100  # slot-001 max_chars = 100
    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": exact_text}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    k1 = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-001")
    assert k1.capacity_utilization == 1.0


def test_service_capacity_utilization_recalculated():
    """Capacity utilization must be recomputed from new text length."""
    new_text = "A" * 50  # 50 / 100 = 0.5
    reviser = make_mock_reviser(
        changes=[{"key": "K1", "action": "replace", "text": new_text}]
    )
    svc = ContentRevisionService(reviser=reviser)
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=make_revision_plan(["K1"]),
    )
    k1 = next(a for a in result.revised_draft.assignments if a.slot_id == "slot-001")
    assert k1.capacity_utilization == pytest.approx(0.5)
    assert k1.character_count == 50


# ---------------------------------------------------------------------------
# Feedback propagation
# ---------------------------------------------------------------------------


def test_service_manager_issue_feedback_propagated_exactly():
    """The reviser receives exactly the M7 issues selected by plan indexes."""
    from tests.test_revision.conftest import make_manager_review, make_visual_qa
    from slidestein.review.models import ManagerReviewIssue

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Core message is unclear.",
        recommendation="Revise K1 to state the message directly."
    )
    manager_review = make_manager_review(issues=[issue])
    visual_qa = make_visual_qa()
    plan = RevisionPlan(
        slide_id="slide-test-001", deck_id="deck-abc123", slide_number=2,
        route=RevisionRoute.CONTENT_REVISION,
        reasons=["Core message unclear."],
        target_slot_keys=["K1"],
        manager_issue_indexes=[0],  # selects issue at index 0
        requires_model_call=True,
    )
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=plan,
        manager_review=manager_review,
        visual_qa=visual_qa,
    )
    call_kwargs = reviser.revise.call_args.kwargs
    feedback = call_kwargs.get("revision_feedback", [])
    assert len(feedback) == 1
    assert feedback[0]["source"] == "manager_review"
    assert feedback[0]["issue"] == "Core message is unclear."
    assert feedback[0]["slot_keys"] == ["K1"]


def test_service_visual_issue_feedback_propagated_exactly():
    """The reviser receives exactly the M8 issues selected by plan indexes."""
    from tests.test_revision.conftest import make_manager_review, make_visual_qa
    from slidestein.qa.models import VisualQAIssue

    issue = VisualQAIssue(
        severity="major", category="text_fit_and_clipping",
        slot_keys=["K1"], issue="Text overflows K1.",
        evidence="Clipping detected.", recommendation="Shorten K1 text."
    )
    visual_qa = make_visual_qa(issues=[issue])
    manager_review = make_manager_review()
    plan = RevisionPlan(
        slide_id="slide-test-001", deck_id="deck-abc123", slide_number=2,
        route=RevisionRoute.CONTENT_REVISION,
        reasons=["Text overflow."],
        target_slot_keys=["K1"],
        visual_issue_indexes=[0],  # selects visual issue at index 0
        requires_model_call=True,
    )
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=plan,
        manager_review=manager_review,
        visual_qa=visual_qa,
    )
    call_kwargs = reviser.revise.call_args.kwargs
    feedback = call_kwargs.get("revision_feedback", [])
    assert len(feedback) == 1
    assert feedback[0]["source"] == "visual_qa"
    assert feedback[0]["issue"] == "Text overflows K1."
    assert feedback[0]["evidence"] == "Clipping detected."


def test_service_factual_flag_feedback_propagated_exactly():
    """Factual flags at selected indexes are included in feedback."""
    from tests.test_revision.conftest import make_manager_review, make_visual_qa
    from slidestein.review.models import ManagerReviewIssue

    flag = ManagerReviewIssue(
        severity="major", category="factual_grounding",
        slot_keys=["K1"], issue="Claim A is not supported by source.",
        recommendation="Verify against source material."
    )
    manager_review = make_manager_review(factual_flags=[flag])
    plan = RevisionPlan(
        slide_id="slide-test-001", deck_id="deck-abc123", slide_number=2,
        route=RevisionRoute.CONTENT_REVISION,
        reasons=["Factual flag."],
        target_slot_keys=["K1"],
        factual_flag_indexes=[0],
        requires_model_call=True,
    )
    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=plan,
        manager_review=manager_review,
        visual_qa=make_visual_qa(),
    )
    call_kwargs = reviser.revise.call_args.kwargs
    feedback = call_kwargs.get("revision_feedback", [])
    assert len(feedback) == 1
    assert feedback[0]["source"] == "manager_factual_flag"
    assert feedback[0]["issue"] == "Claim A is not supported by source."


# ---------------------------------------------------------------------------
# BoundedRevisionOrchestrator
# ---------------------------------------------------------------------------


def _make_orchestrator_with_mocks(m7_result=None, m8_result=None, artifacts_dir=None):
    """Return (orchestrator, mock_content_svc, mock_manager_svc, mock_visual_svc)."""
    from tests.test_revision.conftest import make_complete_draft, make_manager_review, make_visual_qa
    from slidestein.revision.service import BoundedRevisionOrchestrator, ContentRevisionService

    mock_content_svc = MagicMock(spec=ContentRevisionService)
    # preflight returns an opaque preflight object (MagicMock); execute returns the result.
    mock_content_svc.preflight.return_value = MagicMock()
    mock_content_svc.execute.return_value = ContentRevisionResult(
        status="revised",
        revised_draft=make_complete_draft(),
        applied_changes=[],
        change_summary="Tightened.",
    )

    mock_manager_svc = MagicMock()
    mock_manager_svc.review.return_value = m7_result or make_manager_review()

    mock_visual_svc = MagicMock()
    mock_visual_svc.review.return_value = m8_result or make_visual_qa()

    orch = BoundedRevisionOrchestrator(
        content_revision_service=mock_content_svc,
        manager_review_service=mock_manager_svc,
        visual_qa_service=mock_visual_svc,
        artifacts_dir=artifacts_dir or Path("outputs/m9/artifacts"),
    )
    return orch, mock_content_svc, mock_manager_svc, mock_visual_svc


def test_orchestrator_finalize_returns_zero_model_calls():
    """finalize route → 0 model_calls, all services not called."""
    from tests.test_revision.conftest import make_revision_request

    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="approve",
        visual_recommendation="pass",
    )
    result = orch.revise(request)
    assert result.route == RevisionRoute.FINALIZE
    assert sum(result.model_calls.values()) == 0
    assert result.final_ready is True
    content_svc.execute.assert_not_called()
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_template_reselection_returns_zero_model_calls():
    """template_reselection route → 0 model_calls."""
    from slidestein.qa.models import VisualQAIssue
    from tests.test_revision.conftest import make_revision_request

    issue = VisualQAIssue(
        severity="major", category="visual_hierarchy",
        slot_keys=["K1"], issue="Broken hierarchy.", evidence="E.", recommendation="R."
    )
    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="approve",
        visual_recommendation="revise",
        m8_issues=[issue],
    )
    result = orch.revise(request)
    assert result.route == RevisionRoute.TEMPLATE_RESELECTION
    assert sum(result.model_calls.values()) == 0
    content_svc.execute.assert_not_called()
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_manual_review_returns_zero_model_calls():
    """manual_review route → 0 model_calls."""
    from tests.test_revision.conftest import make_revision_request

    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="revise",
    )
    result = orch.revise(request)
    assert result.route == RevisionRoute.MANUAL_REVIEW
    assert sum(result.model_calls.values()) == 0
    content_svc.execute.assert_not_called()
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_content_revision_calls_all_three_services():
    """content_revision route calls content_svc, manager_svc, visual_svc exactly once."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa, make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="answer_first_title",
        slot_keys=["K1"], issue="Not answer-first.", recommendation="Fix."
    )
    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks(
        m7_result=make_manager_review(recommendation="approve"),
        m8_result=make_visual_qa(recommendation="pass"),
    )
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=None):
        result = orch.revise(request)

    assert result.route == RevisionRoute.CONTENT_REVISION
    assert sum(result.model_calls.values()) == 3
    assert result.model_calls["revision"] == 1
    assert result.model_calls["manager_review"] == 1
    assert result.model_calls["visual_qa"] == 1
    content_svc.execute.assert_called_once()
    manager_svc.review.assert_called_once()
    visual_svc.review.assert_called_once()


def test_orchestrator_content_revision_final_ready_when_both_pass():
    """final_ready=True when M7=approve AND M8=pass after revision."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa, make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, _, _ = _make_orchestrator_with_mocks(
        m7_result=make_manager_review(recommendation="approve"),
        m8_result=make_visual_qa(recommendation="pass"),
    )
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=None):
        result = orch.revise(request)

    assert result.final_ready is True


def test_orchestrator_content_revision_not_final_ready_when_m7_revise():
    """final_ready=False when M7=revise after revision."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa, make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, _, _ = _make_orchestrator_with_mocks(
        m7_result=make_manager_review(recommendation="revise"),
        m8_result=make_visual_qa(recommendation="pass"),
    )
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=None):
        result = orch.revise(request)

    assert result.final_ready is False


def test_orchestrator_blocked_stops_immediately():
    """Blocked content result → no M7/M8 re-review calls."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    content_svc.execute.return_value = ContentRevisionResult(
        status="blocked",
        revised_draft=None,
        change_summary="Cannot revise.",
        blocked_reason="Text is minimal.",
    )
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    result = orch.revise(request)
    assert result.status == "blocked"
    assert result.final_ready is False
    assert sum(result.model_calls.values()) == 1  # only revision attempt counted
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_non_content_revision_result_fields_are_none():
    """Non-content_revision results have None revised_draft/pptx/reviews."""
    from tests.test_revision.conftest import make_revision_request

    orch, _, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="approve",
        visual_recommendation="pass",
    )
    result = orch.revise(request)
    assert result.revised_draft is None
    assert result.output_pptx is None
    assert result.manager_review_after is None
    assert result.visual_qa_after is None


def test_orchestrator_model_calls_dict_structure():
    """model_calls dict always has revision/manager_review/visual_qa keys."""
    from tests.test_revision.conftest import make_revision_request

    orch, _, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="approve",
        visual_recommendation="pass",
    )
    result = orch.revise(request)
    assert "revision" in result.model_calls
    assert "manager_review" in result.model_calls
    assert "visual_qa" in result.model_calls


def test_orchestrator_writeback_result_retained():
    """writeback_result from _run_writeback is stored on the result."""
    from slidestein.review.models import ManagerReviewIssue
    from slidestein.writeback.models import PowerPointWritebackResult
    from tests.test_revision.conftest import make_manager_review, make_visual_qa, make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    fake_writeback = PowerPointWritebackResult(
        source_pptx="data/test_decks/sample.pptx",
        output_pptx="outputs/m9/revised.pptx",
        slide_id="slide-test-001",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=1,
        clear_count=0,
        applied_assignments=[],
        verification_passed=True,
    )

    issue = ManagerReviewIssue(
        severity="major", category="answer_first_title",
        slot_keys=["K1"], issue="Not answer-first.", recommendation="Fix."
    )
    orch, _, _, _ = _make_orchestrator_with_mocks(
        m7_result=make_manager_review(recommendation="approve"),
        m8_result=make_visual_qa(recommendation="pass"),
    )
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=fake_writeback):
        result = orch.revise(request)

    assert result.writeback_result == fake_writeback


def test_orchestrator_overwrite_default_false():
    """RevisionRequest.overwrite must default to False."""
    from tests.test_revision.conftest import make_revision_request
    request = make_revision_request()
    assert request.overwrite is False


def test_orchestrator_failure_accounting_revision_stage():
    """RevisionExecutionError from content revision carries model_calls with revision=1."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    content_svc.execute.side_effect = RuntimeError("Provider timeout")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with pytest.raises(RevisionExecutionError) as exc_info:
        orch.revise(request)

    exc = exc_info.value
    assert exc.stage == "content_revision"
    assert exc.model_calls["revision"] == 1
    assert exc.model_calls["manager_review"] == 0
    assert exc.model_calls["visual_qa"] == 0
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_failure_accounting_writeback_stage():
    """RevisionExecutionError from writeback carries model_calls with revision=1."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(
        BoundedRevisionOrchestrator, "_run_writeback",
        side_effect=RuntimeError("COM error"),
    ):
        with pytest.raises(RevisionExecutionError) as exc_info:
            orch.revise(request)

    exc = exc_info.value
    assert exc.stage == "writeback"
    assert exc.model_calls["revision"] == 1
    assert exc.model_calls["manager_review"] == 0
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


# ---------------------------------------------------------------------------
# Issue 1 regression: RevisionError from ContentRevisionService preserves accounting
# ---------------------------------------------------------------------------


def test_orchestrator_content_revision_error_preserves_attempt_count():
    """RevisionError raised by ContentRevisionService must become RevisionExecutionError
    with stage='content_revision' and revision=1, not propagate as plain RevisionError."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    content_svc.execute.side_effect = RevisionError("outside-target key K2")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with pytest.raises(RevisionExecutionError) as exc_info:
        orch.revise(request)

    exc = exc_info.value
    assert exc.stage == "content_revision"
    assert exc.model_calls["revision"] == 1
    assert exc.model_calls["manager_review"] == 0
    assert exc.model_calls["visual_qa"] == 0
    # The original RevisionError is chained
    assert isinstance(exc.__cause__, RevisionError)
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_revision_error_not_plain_re_raise():
    """The orchestrator must NOT let a plain RevisionError escape from the revision stage."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    content_svc.execute.side_effect = RevisionError("capacity violation")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    # Must NOT raise plain RevisionError — must be RevisionExecutionError
    with pytest.raises(RevisionExecutionError):
        orch.revise(request)


# ---------------------------------------------------------------------------
# Issue 2 regression: real PowerPointWritebackError path preserves accounting
# ---------------------------------------------------------------------------


def test_orchestrator_writeback_pptx_error_wrapped_as_execution_error():
    """PowerPointWritebackError converted to RevisionError in _run_writeback must
    still surface as RevisionExecutionError with stage='writeback' and revision=1."""
    from slidestein.review.models import ManagerReviewIssue
    from slidestein.writeback.errors import PowerPointWritebackError
    from tests.test_revision.conftest import make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )

    # Simulate the REAL production path: _run_writeback catches PowerPointWritebackError
    # and converts it to RevisionError, which is what the orchestrator then receives.
    def _wb_raises_revision_error(*args, **kwargs):
        pptx_exc = PowerPointWritebackError("COM object not accessible")
        raise RevisionError(
            "Write-back preflight/apply failed: PowerPointWritebackError"
        ) from pptx_exc

    with patch.object(BoundedRevisionOrchestrator, "_run_writeback",
                      side_effect=_wb_raises_revision_error):
        with pytest.raises(RevisionExecutionError) as exc_info:
            orch.revise(request)

    exc = exc_info.value
    assert exc.stage == "writeback"
    assert exc.model_calls["revision"] == 1
    assert exc.model_calls["manager_review"] == 0
    assert exc.model_calls["visual_qa"] == 0
    # Exception chaining preserved
    assert isinstance(exc.__cause__, RevisionError)
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


# ---------------------------------------------------------------------------
# Issue 3 regression: strict feedback index validation
# ---------------------------------------------------------------------------


def test_service_out_of_range_manager_issue_index_raises_before_provider():
    """manager_issue_indexes=[99] when only 1 issue exists → RevisionError, 0 provider calls."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    mr = make_manager_review(issues=[issue])
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"manager_issue_indexes": [99]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="manager_issue_indexes"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=mr,
            visual_qa=make_visual_qa(),
        )
    reviser.revise.assert_not_called()


def test_service_out_of_range_factual_flag_index_raises_before_provider():
    """factual_flag_indexes=[5] when 0 flags exist → RevisionError, 0 provider calls."""
    from tests.test_revision.conftest import make_manager_review, make_visual_qa

    mr = make_manager_review()  # no flags
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"factual_flag_indexes": [5]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="factual_flag_indexes"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=mr,
            visual_qa=make_visual_qa(),
        )
    reviser.revise.assert_not_called()


def test_service_out_of_range_visual_issue_index_raises_before_provider():
    """visual_issue_indexes=[2] when 0 visual issues exist → RevisionError, 0 provider calls."""
    from tests.test_revision.conftest import make_manager_review, make_visual_qa

    vq = make_visual_qa()  # no issues
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"visual_issue_indexes": [2]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="visual_issue_indexes"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=make_manager_review(),
            visual_qa=vq,
        )
    reviser.revise.assert_not_called()


def test_service_negative_manager_issue_index_raises_before_provider():
    """Negative index → RevisionError before provider call."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    mr = make_manager_review(issues=[issue])
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"manager_issue_indexes": [-1]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=mr,
            visual_qa=make_visual_qa(),
        )
    reviser.revise.assert_not_called()


def test_service_manager_indexes_without_manager_review_raises():
    """manager_issue_indexes non-empty but manager_review=None → RevisionError."""
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"manager_issue_indexes": [0]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="manager_review"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=None,
            visual_qa=None,
        )
    reviser.revise.assert_not_called()


def test_service_visual_indexes_without_visual_qa_raises():
    """visual_issue_indexes non-empty but visual_qa=None → RevisionError."""
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"visual_issue_indexes": [0]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="visual_qa"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=None,
            visual_qa=None,
        )
    reviser.revise.assert_not_called()


def test_service_factual_flag_indexes_without_manager_review_raises():
    """factual_flag_indexes non-empty but manager_review=None → RevisionError."""
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"factual_flag_indexes": [0]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    with pytest.raises(RevisionError, match="manager_review"):
        svc.revise(
            brief=make_brief(),
            draft=make_complete_draft(),
            slot_map=make_slot_map(),
            source_material=None,
            revision_plan=plan,
            manager_review=None,
            visual_qa=None,
        )
    reviser.revise.assert_not_called()


def test_service_valid_indexes_do_not_raise():
    """Valid in-range indexes with present review context must NOT raise."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    mr = make_manager_review(issues=[issue])
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"manager_issue_indexes": [0]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    # Should NOT raise RevisionError for index 0 when 1 issue exists
    result = svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=plan,
        manager_review=mr,
        visual_qa=make_visual_qa(),
    )
    assert result.status == "revised"
    reviser.revise.assert_called_once()


def test_service_feedback_no_fabricated_fallback():
    """Feedback for factual flags uses actual object fields only — no fabricated defaults."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa

    flag = ManagerReviewIssue(
        severity="major", category="factual_grounding",
        slot_keys=["K1"], issue="Claim is unsupported.",
        recommendation="Verify against source."
    )
    mr = make_manager_review(factual_flags=[flag])
    plan = make_revision_plan(["K1"])
    plan = plan.model_copy(update={"factual_flag_indexes": [0]})

    reviser = make_mock_reviser()
    svc = ContentRevisionService(reviser=reviser)
    svc.revise(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
        source_material=None,
        revision_plan=plan,
        manager_review=mr,
        visual_qa=make_visual_qa(),
    )
    feedback = reviser.revise.call_args.kwargs.get("revision_feedback", [])
    assert len(feedback) == 1
    assert feedback[0]["source"] == "manager_factual_flag"
    assert feedback[0]["recommendation"] == "Verify against source."
    # Must NOT be the fabricated fallback string
    assert "Verify this claim against source material." not in feedback[0]["recommendation"]


# ---------------------------------------------------------------------------
# Orchestrator-level zero-call prevalidation accounting (new requirement)
# Uses a REAL ContentRevisionService with a mocked reviser so that the actual
# preflight() logic runs.  RevisionRouter.route is patched to inject bad plans.
# ---------------------------------------------------------------------------


def _real_content_svc_orchestrator():
    """Return (orchestrator, mock_reviser) with a REAL ContentRevisionService."""
    from slidestein.revision.service import BoundedRevisionOrchestrator, ContentRevisionService

    mock_reviser = MagicMock()
    real_content_svc = ContentRevisionService(reviser=mock_reviser)
    orch = BoundedRevisionOrchestrator(
        content_revision_service=real_content_svc,
        manager_review_service=MagicMock(),
        visual_qa_service=MagicMock(),
        artifacts_dir=Path("outputs/m9/artifacts"),
    )
    return orch, mock_reviser


def _bad_plan(request, **overrides):
    """Build a content_revision RevisionPlan with custom index overrides."""
    from slidestein.revision.models import RevisionPlan, RevisionRoute
    defaults = dict(
        slide_id=request.draft.slide_id,
        deck_id=request.draft.deck_id,
        slide_number=request.slot_map.slide_number,
        route=RevisionRoute.CONTENT_REVISION,
        reasons=["test bad index"],
        target_slot_keys=["K1"],
        requires_model_call=True,
    )
    defaults.update(overrides)
    return RevisionPlan(**defaults)


def test_orchestrator_preflight_invalid_manager_index_zero_attempts():
    """Invalid manager_issue_index in plan → RevisionError (preflight), revision=0, reviser=0."""
    from slidestein.revision.router import RevisionRouter
    from tests.test_revision.conftest import make_revision_request

    orch, mock_reviser = _real_content_svc_orchestrator()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
    )  # manager_review has 0 issues
    plan = _bad_plan(request, manager_issue_indexes=[99])

    with patch.object(RevisionRouter, "route", return_value=plan):
        with pytest.raises(RevisionError):
            orch.revise(request)

    mock_reviser.revise.assert_not_called()


def test_orchestrator_preflight_invalid_factual_flag_index_zero_attempts():
    """Invalid factual_flag_index in plan → RevisionError (preflight), revision=0, reviser=0."""
    from slidestein.revision.router import RevisionRouter
    from tests.test_revision.conftest import make_revision_request

    orch, mock_reviser = _real_content_svc_orchestrator()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
    )  # manager_review has 0 factual_flags
    plan = _bad_plan(request, factual_flag_indexes=[5])

    with patch.object(RevisionRouter, "route", return_value=plan):
        with pytest.raises(RevisionError):
            orch.revise(request)

    mock_reviser.revise.assert_not_called()


def test_orchestrator_preflight_invalid_visual_index_zero_attempts():
    """Invalid visual_issue_index in plan → RevisionError (preflight), revision=0, reviser=0."""
    from slidestein.revision.router import RevisionRouter
    from tests.test_revision.conftest import make_revision_request

    orch, mock_reviser = _real_content_svc_orchestrator()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
    )  # visual_qa has 0 issues
    plan = _bad_plan(request, visual_issue_indexes=[2])

    with patch.object(RevisionRouter, "route", return_value=plan):
        with pytest.raises(RevisionError):
            orch.revise(request)

    mock_reviser.revise.assert_not_called()


def test_orchestrator_preflight_missing_manager_review_zero_attempts():
    """manager_issue_indexes non-empty but manager_review=None → RevisionError, revision=0."""
    from slidestein.revision.router import RevisionRouter
    from tests.test_revision.conftest import make_revision_request

    orch, mock_reviser = _real_content_svc_orchestrator()
    # Build a request but we'll use a plan that expects manager indexes
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
    )
    # Inject a plan that references manager_issue_indexes=[0] but the request has
    # manager_review with 0 issues — the preflight will raise "manager_review"
    plan = _bad_plan(request, manager_issue_indexes=[0])

    with patch.object(RevisionRouter, "route", return_value=plan):
        with pytest.raises(RevisionError, match="manager_issue_indexes"):
            orch.revise(request)

    mock_reviser.revise.assert_not_called()


def test_orchestrator_preflight_missing_visual_qa_zero_attempts():
    """visual_issue_indexes non-empty with 0 visual issues → RevisionError, revision=0."""
    from slidestein.revision.router import RevisionRouter
    from tests.test_revision.conftest import make_revision_request

    orch, mock_reviser = _real_content_svc_orchestrator()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
    )  # visual_qa has 0 issues
    plan = _bad_plan(request, visual_issue_indexes=[0])

    with patch.object(RevisionRouter, "route", return_value=plan):
        with pytest.raises(RevisionError, match="visual_issue_indexes"):
            orch.revise(request)

    mock_reviser.revise.assert_not_called()


def test_orchestrator_preflight_not_revision_execution_error():
    """Preflight failure must NOT raise RevisionExecutionError (no attempt consumed)."""
    from slidestein.revision.router import RevisionRouter
    from tests.test_revision.conftest import make_revision_request

    orch, mock_reviser = _real_content_svc_orchestrator()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
    )
    plan = _bad_plan(request, manager_issue_indexes=[99])

    with patch.object(RevisionRouter, "route", return_value=plan):
        # Must be RevisionError, NOT RevisionExecutionError
        with pytest.raises(RevisionError) as exc_info:
            orch.revise(request)
    assert not isinstance(exc_info.value, RevisionExecutionError)
    mock_reviser.revise.assert_not_called()


def test_orchestrator_post_provider_outside_scope_counts_as_attempt():
    """Outside-target-scope key from model output is post-provider → revision=1."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    content_svc.execute.side_effect = RevisionError("outside.*target scope")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with pytest.raises(RevisionExecutionError) as exc_info:
        orch.revise(request)

    assert exc_info.value.model_calls["revision"] == 1


def test_orchestrator_post_provider_capacity_violation_counts_as_attempt():
    """Capacity violation in execute is post-provider → revision=1."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    content_svc.execute.side_effect = RevisionError("exceeds capacity")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with pytest.raises(RevisionExecutionError) as exc_info:
        orch.revise(request)

    assert exc_info.value.model_calls["revision"] == 1


def test_orchestrator_m7_failure_accounting():
    """M7 review failure after successful revision → revision=1, manager_review=1, visual_qa=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    manager_svc.review.side_effect = RuntimeError("M7 provider timeout")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=None):
        with pytest.raises(RevisionExecutionError) as exc_info:
            orch.revise(request)

    exc = exc_info.value
    assert exc.stage == "manager_review"
    assert exc.model_calls["revision"] == 1
    assert exc.model_calls["manager_review"] == 1
    assert exc.model_calls["visual_qa"] == 0
    visual_svc.review.assert_not_called()


def test_orchestrator_m8_failure_accounting():
    """M8 QA failure after M7 succeeds → revision=1, manager_review=1, visual_qa=1."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, _, visual_svc = _make_orchestrator_with_mocks(
        m7_result=make_manager_review(recommendation="approve"),
    )
    visual_svc.review.side_effect = RuntimeError("M8 provider timeout")

    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
    )
    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=None):
        with pytest.raises(RevisionExecutionError) as exc_info:
            orch.revise(request)

    exc = exc_info.value
    assert exc.stage == "visual_qa"
    assert exc.model_calls["revision"] == 1
    assert exc.model_calls["manager_review"] == 1
    assert exc.model_calls["visual_qa"] == 1


# ---------------------------------------------------------------------------
# File preflight — non-content routes accept None paths (step 6)
# ---------------------------------------------------------------------------


def test_orchestrator_finalize_with_no_pptx_paths():
    """finalize route with template_pptx=None, output_pptx=None → success, 0 calls."""
    from tests.test_revision.conftest import make_revision_request

    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="approve",
        visual_recommendation="pass",
        template_pptx=None,
        output_pptx=None,
    )
    result = orch.revise(request)
    assert result.route == RevisionRoute.FINALIZE
    assert sum(result.model_calls.values()) == 0
    content_svc.execute.assert_not_called()
    manager_svc.review.assert_not_called()
    visual_svc.review.assert_not_called()


def test_orchestrator_template_reselection_with_no_pptx_paths():
    """template_reselection route with template_pptx=None, output_pptx=None → success, 0 calls."""
    from slidestein.qa.models import VisualQAIssue
    from tests.test_revision.conftest import make_revision_request

    issue = VisualQAIssue(
        severity="major", category="visual_hierarchy",
        slot_keys=["K1"], issue="Broken hierarchy.", evidence="E.", recommendation="R."
    )
    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="approve",
        visual_recommendation="revise",
        m8_issues=[issue],
        template_pptx=None,
        output_pptx=None,
    )
    result = orch.revise(request)
    assert result.route == RevisionRoute.TEMPLATE_RESELECTION
    assert sum(result.model_calls.values()) == 0
    content_svc.execute.assert_not_called()


def test_orchestrator_manual_review_with_no_pptx_paths():
    """manual_review route with template_pptx=None, output_pptx=None → success, 0 calls."""
    from tests.test_revision.conftest import make_revision_request

    orch, content_svc, manager_svc, visual_svc = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="revise",
        template_pptx=None,
        output_pptx=None,
    )
    result = orch.revise(request)
    assert result.route == RevisionRoute.MANUAL_REVIEW
    assert sum(result.model_calls.values()) == 0
    content_svc.execute.assert_not_called()


# ---------------------------------------------------------------------------
# File preflight — content_revision route failures (step 7)
# All failures must raise RevisionError BEFORE provider invocation (revision=0)
# ---------------------------------------------------------------------------


def test_orchestrator_content_revision_no_source_material_raises():
    """content_revision with source_material=None → RevisionError, revision=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material=None,  # missing
    )
    with pytest.raises(RevisionError, match="source_material"):
        orch.revise(request)
    content_svc.execute.assert_not_called()


def test_orchestrator_content_revision_empty_source_material_raises():
    """content_revision with empty source_material → RevisionError, revision=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material="   ",  # blank only
    )
    with pytest.raises(RevisionError, match="source_material"):
        orch.revise(request)
    content_svc.execute.assert_not_called()


def test_orchestrator_content_revision_no_template_pptx_raises():
    """content_revision with template_pptx=None → RevisionError, revision=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material="Some source text.",
        template_pptx=None,
    )
    with pytest.raises(RevisionError, match="template_pptx"):
        orch.revise(request)
    content_svc.execute.assert_not_called()


def test_orchestrator_content_revision_missing_template_file_raises():
    """content_revision with non-existent template_pptx → RevisionError, revision=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material="Some source text.",
        template_pptx=Path("nonexistent/does_not_exist.pptx"),
    )
    with pytest.raises(RevisionError, match="not found"):
        orch.revise(request)
    content_svc.execute.assert_not_called()


def test_orchestrator_content_revision_no_output_pptx_raises():
    """content_revision with output_pptx=None → RevisionError, revision=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material="Some source text.",
        template_pptx=Path("data/test_decks/sample_consulting_deck.pptx"),
        output_pptx=None,
    )
    with pytest.raises(RevisionError, match="output_pptx"):
        orch.revise(request)
    content_svc.execute.assert_not_called()


def test_orchestrator_content_revision_output_exists_overwrite_false_raises(tmp_path):
    """output_pptx already exists and overwrite=False → RevisionError, revision=0."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_revision_request

    existing_file = tmp_path / "existing.pptx"
    existing_file.write_bytes(b"placeholder")

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, content_svc, _, _ = _make_orchestrator_with_mocks()
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material="Some source text.",
        template_pptx=Path("data/test_decks/sample_consulting_deck.pptx"),
        output_pptx=existing_file,
        # overwrite defaults to False
    )
    with pytest.raises(RevisionError, match="overwrite=False"):
        orch.revise(request)
    content_svc.execute.assert_not_called()


def test_orchestrator_content_revision_output_exists_overwrite_true_proceeds(tmp_path):
    """output_pptx already exists but overwrite=True → no error from file preflight."""
    from slidestein.review.models import ManagerReviewIssue
    from tests.test_revision.conftest import make_manager_review, make_visual_qa, make_revision_request
    from slidestein.revision.service import BoundedRevisionOrchestrator

    existing_file = tmp_path / "existing.pptx"
    existing_file.write_bytes(b"placeholder")

    # template_pptx must exist on disk; use the existing_file as a stand-in
    # (file preflight only checks exists+is_file, not PPTX validity)
    template_file = tmp_path / "template.pptx"
    template_file.write_bytes(b"template")

    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    orch, _, _, _ = _make_orchestrator_with_mocks(
        m7_result=make_manager_review(recommendation="approve"),
        m8_result=make_visual_qa(recommendation="pass"),
    )
    request = make_revision_request(
        manager_recommendation="revise",
        visual_recommendation="pass",
        m7_issues=[issue],
        source_material="Some source text.",
        template_pptx=template_file,
        output_pptx=existing_file,
    )
    # overwrite=True on the request — need to set it manually since make_revision_request
    # doesn't accept overwrite param; use model_copy
    request = request.model_copy(update={"overwrite": True})

    with patch.object(BoundedRevisionOrchestrator, "_run_writeback", return_value=None):
        result = orch.revise(request)

    # File preflight passed (overwrite=True); execution proceeds
    assert result.route == RevisionRoute.CONTENT_REVISION
    assert result.model_calls["revision"] == 1

