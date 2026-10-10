"""Tests for StructuralRecoveryOrchestrator — input validation and routing.

All provider boundaries are mocked; zero API calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.revision.models import RevisionRoute
from slidestein.slots.roles import SlotRole
from slidestein.structural.errors import StructuralRecoveryError
from slidestein.structural.models import (
    StructuralRecoveryPlan,
    StructuralRecoveryResult,
    StructuralRecoveryRoute,
)
from slidestein.structural.orchestrator import StructuralRecoveryOrchestrator
from slidestein.structural.versions import (
    STRUCTURAL_RECOVERY_POLICY_VERSION,
    STRUCTURAL_RECOVERY_SCHEMA_VERSION,
)
from slidestein.writeback.models import PowerPointWritebackResult

from .conftest import (
    make_assignment,
    make_brief,
    make_complete_draft,
    make_m9_plan,
    make_manager_review,
    make_recovery_request,
    make_slot,
    make_slot_map,
    make_visual_qa,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wb_result(output_pptx: Path) -> PowerPointWritebackResult:
    return PowerPointWritebackResult(
        source_pptx="template.pptx",
        output_pptx=str(output_pptx),
        slide_id="slide-test-001",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=2,
        clear_count=0,
        applied_assignments=[],
        verification_passed=True,
    )


def _make_plan(route: StructuralRecoveryRoute) -> StructuralRecoveryPlan:
    return StructuralRecoveryPlan(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        route=route,
        reasons=["Test reason."],
        current_template_slide_id="slide-test-001",
        requires_candidate_retrieval=(route == StructuralRecoveryRoute.RESELECT_TEMPLATE),
        requires_selection_call=(route == StructuralRecoveryRoute.RESELECT_TEMPLATE),
        requires_redraft_call=(route == StructuralRecoveryRoute.RESELECT_TEMPLATE),
    )


def _make_orchestrator():
    """Build an orchestrator with all mock services."""
    orchestrator = StructuralRecoveryOrchestrator(
        searcher=MagicMock(),
        library=MagicMock(),
        selector=MagicMock(),
        drafting_service=MagicMock(),
        writeback_service=MagicMock(),
        manager_review_service=MagicMock(),
        visual_qa_service=MagicMock(),
        renderer=MagicMock(),
    )
    return orchestrator


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_wrong_m9_route_raises():
    req = make_recovery_request(m9_route=RevisionRoute.CONTENT_REVISION)
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError, match="template_reselection"):
        orch.recover(req, Path("artifacts"))


def test_wrong_m9_route_finalize_raises():
    req = make_recovery_request(m9_route=RevisionRoute.FINALIZE)
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError):
        orch.recover(req, Path("artifacts"))


def test_wrong_m9_route_manual_review_raises():
    req = make_recovery_request(m9_route=RevisionRoute.MANUAL_REVIEW)
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError):
        orch.recover(req, Path("artifacts"))


def test_incomplete_draft_raises(tmp_path):
    """Orchestrator must reject when draft.is_complete=False."""
    from slidestein.drafting.models import SlideContentDraft, SlotDraftAction, SlotDraftAssignment
    from slidestein.structural.models import StructuralRecoveryRequest

    # NEEDS_INPUT assignment requires missing_information to be non-blank
    needs_input_assign = SlotDraftAssignment(
        slot_id="slot-001",
        shape_id=21,
        shape_path="21",
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
        missing_information="Need the client name.",
        capacity_characters=100,
        capacity_utilization=0.0,
        max_lines_estimate=2,
    )
    draft_with_needs_input = SlideContentDraft(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        brief_key_message="Digital transformation drives efficiency.",
        assignments=[needs_input_assign],
        drafting_summary="Incomplete draft.",
        is_complete=False,
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")
    req = StructuralRecoveryRequest(
        brief=make_brief(),
        current_draft=draft_with_needs_input,
        current_slot_map=make_slot_map(slots=[
            make_slot(slot_id="slot-001", shape_id=21, shape_path="21",
                      slot_role=SlotRole.TITLE, semantic_label="Title"),
        ]),
        manager_review=make_manager_review(),
        visual_qa=make_visual_qa(),
        m9_plan=make_m9_plan(),
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError, match="is_complete"):
        orch.recover(req, tmp_path)


def test_manager_review_slide_id_mismatch_raises():
    from slidestein.structural.models import StructuralRecoveryRequest
    req = StructuralRecoveryRequest(
        brief=make_brief(),
        current_draft=make_complete_draft(slide_id="slide-A"),
        current_slot_map=make_slot_map(slide_id="slide-A"),
        manager_review=make_manager_review(slide_id="slide-B"),  # mismatch
        visual_qa=make_visual_qa(slide_id="slide-A"),
        m9_plan=make_m9_plan(slide_id="slide-A"),
        template_pptx=Path("template.pptx"),
        generated_pptx=Path("generated.pptx"),
    )
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError, match="manager_review"):
        orch.recover(req, Path("artifacts"))


def test_visual_qa_slide_id_mismatch_raises():
    from slidestein.structural.models import StructuralRecoveryRequest
    req = StructuralRecoveryRequest(
        brief=make_brief(),
        current_draft=make_complete_draft(slide_id="slide-A"),
        current_slot_map=make_slot_map(slide_id="slide-A"),
        manager_review=make_manager_review(slide_id="slide-A"),
        visual_qa=make_visual_qa(slide_id="slide-B"),  # mismatch
        m9_plan=make_m9_plan(slide_id="slide-A"),
        template_pptx=Path("template.pptx"),
        generated_pptx=Path("generated.pptx"),
    )
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError, match="visual_qa"):
        orch.recover(req, Path("artifacts"))


def test_m9_plan_slide_id_mismatch_raises():
    from slidestein.structural.models import StructuralRecoveryRequest
    req = StructuralRecoveryRequest(
        brief=make_brief(),
        current_draft=make_complete_draft(slide_id="slide-A"),
        current_slot_map=make_slot_map(slide_id="slide-A"),
        manager_review=make_manager_review(slide_id="slide-A"),
        visual_qa=make_visual_qa(slide_id="slide-A"),
        m9_plan=make_m9_plan(slide_id="slide-B"),  # mismatch
        template_pptx=Path("template.pptx"),
        generated_pptx=Path("generated.pptx"),
    )
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError, match="m9_plan"):
        orch.recover(req, Path("artifacts"))


# ---------------------------------------------------------------------------
# Manual review route
# ---------------------------------------------------------------------------


def test_manual_review_returns_immediately(tmp_path):
    req = make_recovery_request(
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")
    orch = _make_orchestrator()
    manual_plan = _make_plan(StructuralRecoveryRoute.MANUAL_REVIEW)

    with patch.object(orch._diagnosis, "diagnose", return_value=manual_plan):
        result = orch.recover(req, tmp_path)

    assert result.status == "escalation_required"
    assert result.route == StructuralRecoveryRoute.MANUAL_REVIEW
    assert result.final_ready is False
    assert sum(result.model_calls.values()) == 0  # No API calls


# ---------------------------------------------------------------------------
# Rebuild route
# ---------------------------------------------------------------------------


def test_rebuild_calls_m8_and_returns(tmp_path):
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    # Create dummy PPTX files so file existence checks pass
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    rebuild_plan = _make_plan(StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE)

    mock_wb_result = _make_wb_result(tmp_path / "output.pptx")

    mock_vqa_result = make_visual_qa(recommendation="pass")

    orch._writeback_service.preflight.return_value = MagicMock()
    orch._writeback_service.apply.return_value = mock_wb_result

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=rebuild_plan),
        patch.object(orch._visual_qa_service, "review", return_value=mock_vqa_result),
    ):
        result = orch.recover(req, tmp_path)

    assert result.status == "rebuilt"
    assert result.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    assert result.content_changed is False
    assert result.model_calls["visual_qa"] == 1
    assert result.model_calls["retrieval_embedding"] == 0
    assert result.model_calls["template_selection"] == 0
    assert result.model_calls["manager_review"] == 0


def test_rebuild_final_ready_when_m7_approve_m8_pass(tmp_path):
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    rebuild_plan = _make_plan(StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE)
    mock_vqa_pass = make_visual_qa(recommendation="pass")

    orch._writeback_service.preflight.return_value = MagicMock()
    orch._writeback_service.apply.return_value = _make_wb_result(tmp_path / "output.pptx")

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=rebuild_plan),
        patch.object(orch._visual_qa_service, "review", return_value=mock_vqa_pass),
    ):
        result = orch.recover(req, tmp_path)

    # M7 existing: "approve", M8 new: "pass" → final_ready=True
    assert result.final_ready is True


def test_rebuild_not_final_ready_when_m8_revise(tmp_path):
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    rebuild_plan = _make_plan(StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE)
    mock_vqa_revise = make_visual_qa(recommendation="revise")

    orch._writeback_service.preflight.return_value = MagicMock()
    orch._writeback_service.apply.return_value = _make_wb_result(tmp_path / "output.pptx")

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=rebuild_plan),
        patch.object(orch._visual_qa_service, "review", return_value=mock_vqa_revise),
    ):
        result = orch.recover(req, tmp_path)

    assert result.final_ready is False


# ---------------------------------------------------------------------------
# Reselect route — model call accounting
# ---------------------------------------------------------------------------


def test_reselect_increments_all_counters(tmp_path):
    from slidestein.structural.models import StructuralCandidateInfo

    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    # Mock retrieval
    mock_result = MagicMock()
    mock_result.slide_id = "slide-cand-001"
    mock_result.deck_id = "deck-cand-001"
    mock_result.slide_number = 3
    mock_result.rank = 1
    orch._searcher.search.return_value = [mock_result]

    # Mock library
    mock_record = MagicMock()
    mock_record.preview_path = None
    mock_record.source_deck_path = tmp_path / "source_deck.pptx"
    (tmp_path / "source_deck.pptx").write_bytes(b"fake")
    orch._library.get_slide.return_value = mock_record

    # Mock slot map retrieval (different fingerprint to avoid clone exclusion)
    cand_slot_map = make_slot_map(
        slide_id="slide-cand-001",
        deck_id="deck-cand-001",
        slide_number=3,
        slots=[
            make_slot(
                slot_id="cand-slot-001", shape_id=31, shape_path="31",
                slot_role=SlotRole.TITLE,
                semantic_label="Title",
                x_emu=228600, y_emu=228600, w_emu=11430000, h_emu=800000,
                y_ratio=0.03, x_ratio=0.02,
            ),
        ],
    )
    orch._library.get_slot_map.return_value = (
        cand_slot_map.model_dump_json(), "fp-cand", "2024-01-01"
    )
    orch._library.get_classification.return_value = None

    # Mock selection — preflight/select_prepared boundary
    from slidestein.structural.models import StructuralSelectionOutput
    from slidestein.structural.selector import StructuralSelectionPreflight
    orch._selector.preflight.return_value = StructuralSelectionPreflight(
        prompt_text="test prompt",
        content_parts=[],
    )
    orch._selector.select_prepared.return_value = StructuralSelectionOutput(
        selected_candidate_key="SC1",
        rationale="Better balance.",
    )

    # Mock drafting
    mock_alternate_draft = make_complete_draft(
        slide_id="slide-test-001", deck_id="deck-abc123"
    )
    orch._drafting_service.draft.return_value = mock_alternate_draft

    # Mock M7
    mock_m7_result = make_manager_review(recommendation="approve")
    orch._manager_review_service.review.return_value = mock_m7_result

    # Mock M8
    mock_m8_result = make_visual_qa(recommendation="pass")
    orch._visual_qa_service.review.return_value = mock_m8_result

    # Mock writeback via injected service
    mock_wb_result = _make_wb_result(tmp_path / "output.pptx")
    orch._writeback_service.preflight.return_value = MagicMock()
    orch._writeback_service.apply.return_value = mock_wb_result

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan),
        patch.object(orch, "_render_candidates", return_value={"SC1": tmp_path / "SC1.png"}),
        patch.object(orch, "_render_current_template", return_value=tmp_path / "current.png"),
    ):
        # Create fake rendered images so filters pass
        (tmp_path / "SC1.png").write_bytes(b"fake_png")
        (tmp_path / "current.png").write_bytes(b"fake_png")
        result = orch.recover(req, tmp_path)

    assert result.model_calls["retrieval_embedding"] == 1
    assert result.model_calls["template_selection"] == 1
    assert result.model_calls["drafting"] == 1
    assert result.model_calls["manager_review"] == 1
    assert result.model_calls["visual_qa"] == 1
    assert sum(result.model_calls.values()) == 5


def test_reselect_no_candidates_blocks(tmp_path):
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)
    orch._searcher.search.return_value = []

    with patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan):
        result = orch.recover(req, tmp_path)

    assert result.status == "blocked"
    assert result.model_calls["retrieval_embedding"] == 1


def test_no_api_calls_before_validation_failure():
    """Validation errors must not increment any counters."""
    req = make_recovery_request(m9_route=RevisionRoute.CONTENT_REVISION)
    orch = _make_orchestrator()
    with pytest.raises(StructuralRecoveryError):
        orch.recover(req, Path("artifacts"))
    # None of the mock services should have been called
    orch._searcher.search.assert_not_called()
    orch._selector.preflight.assert_not_called()
    orch._selector.select_prepared.assert_not_called()
    orch._drafting_service.draft.assert_not_called()


# ---------------------------------------------------------------------------
# Provider-boundary contract — preflight failure must NOT increment counter
# ---------------------------------------------------------------------------


def test_preflight_failure_does_not_increment_template_selection_counter(tmp_path):
    """preflight() raises → template_selection stays 0 (no external call was made)."""
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    mock_result = MagicMock()
    mock_result.slide_id = "slide-cand-001"
    mock_result.deck_id = "deck-cand-001"
    mock_result.slide_number = 3
    mock_result.rank = 1
    orch._searcher.search.return_value = [mock_result]

    mock_record = MagicMock()
    mock_record.preview_path = None
    mock_record.source_deck_path = tmp_path / "source_deck.pptx"
    (tmp_path / "source_deck.pptx").write_bytes(b"fake")
    orch._library.get_slide.return_value = mock_record
    orch._library.get_classification.return_value = None

    cand_slot_map = make_slot_map(
        slide_id="slide-cand-001",
        slots=[make_slot(slot_id="cand-s1", shape_id=31, shape_path="31",
                         slot_role=SlotRole.TITLE, semantic_label="Title",
                         x_emu=228600, y_emu=228600, w_emu=11430000, h_emu=800000)],
    )
    orch._library.get_slot_map.return_value = (
        cand_slot_map.model_dump_json(), "fp-cand", "2024-01-01"
    )

    # preflight raises — this must NOT count as a provider call
    orch._selector.preflight.side_effect = RuntimeError("SDK import failed")

    from slidestein.structural.errors import StructuralRecoveryExecutionError
    with (
        patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan),
        patch.object(orch, "_render_candidates",
                     return_value={"SC1": tmp_path / "SC1.png"}),
        patch.object(orch, "_render_current_template",
                     return_value=tmp_path / "current.png"),
    ):
        (tmp_path / "SC1.png").write_bytes(b"fake_png")
        (tmp_path / "current.png").write_bytes(b"fake_png")
        with pytest.raises(StructuralRecoveryExecutionError) as exc_info:
            orch.recover(req, tmp_path)

    assert exc_info.value.model_calls["template_selection"] == 0


def test_select_prepared_failure_increments_template_selection_counter(tmp_path):
    """select_prepared() raises → template_selection == 1 (external call was attempted)."""
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    mock_result = MagicMock()
    mock_result.slide_id = "slide-cand-001"
    mock_result.deck_id = "deck-cand-001"
    mock_result.slide_number = 3
    mock_result.rank = 1
    orch._searcher.search.return_value = [mock_result]

    mock_record = MagicMock()
    mock_record.preview_path = None
    mock_record.source_deck_path = tmp_path / "source_deck.pptx"
    (tmp_path / "source_deck.pptx").write_bytes(b"fake")
    orch._library.get_slide.return_value = mock_record
    orch._library.get_classification.return_value = None

    cand_slot_map = make_slot_map(
        slide_id="slide-cand-001",
        slots=[make_slot(slot_id="cand-s1", shape_id=31, shape_path="31",
                         slot_role=SlotRole.TITLE, semantic_label="Title",
                         x_emu=228600, y_emu=228600, w_emu=11430000, h_emu=800000)],
    )
    orch._library.get_slot_map.return_value = (
        cand_slot_map.model_dump_json(), "fp-cand", "2024-01-01"
    )

    from slidestein.structural.selector import StructuralSelectionPreflight
    orch._selector.preflight.return_value = StructuralSelectionPreflight(
        prompt_text="test", content_parts=[]
    )
    # select_prepared raises (e.g. network timeout after provider was contacted)
    orch._selector.select_prepared.side_effect = RuntimeError("provider timeout")

    from slidestein.structural.errors import StructuralRecoveryExecutionError
    with (
        patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan),
        patch.object(orch, "_render_candidates",
                     return_value={"SC1": tmp_path / "SC1.png"}),
        patch.object(orch, "_render_current_template",
                     return_value=tmp_path / "current.png"),
    ):
        (tmp_path / "SC1.png").write_bytes(b"fake_png")
        (tmp_path / "current.png").write_bytes(b"fake_png")
        with pytest.raises(StructuralRecoveryExecutionError) as exc_info:
            orch.recover(req, tmp_path)

    assert exc_info.value.model_calls["template_selection"] == 1


# ---------------------------------------------------------------------------
# Unrenderable candidate filtering
# ---------------------------------------------------------------------------


def _make_reselect_orch_with_candidate(tmp_path):
    """Return (orch, req, reselect_plan, cand_slot_map, mock_record)."""
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    mock_result = MagicMock()
    mock_result.slide_id = "slide-cand-001"
    mock_result.deck_id = "deck-cand-001"
    mock_result.slide_number = 3
    mock_result.rank = 1
    orch._searcher.search.return_value = [mock_result]

    mock_record = MagicMock()
    mock_record.preview_path = None
    mock_record.source_deck_path = str(tmp_path / "source_deck.pptx")
    (tmp_path / "source_deck.pptx").write_bytes(b"fake")
    orch._library.get_slide.return_value = mock_record
    orch._library.get_classification.return_value = None

    cand_slot_map = make_slot_map(
        slide_id="slide-cand-001",
        slots=[make_slot(slot_id="cand-s1", shape_id=31, shape_path="31",
                         slot_role=SlotRole.TITLE, semantic_label="Title",
                         x_emu=228600, y_emu=228600, w_emu=11430000, h_emu=800000)],
    )
    orch._library.get_slot_map.return_value = (
        cand_slot_map.model_dump_json(), "fp-cand", "2024-01-01"
    )
    return orch, req, reselect_plan, cand_slot_map, mock_record


def test_all_unrenderable_candidates_blocks_before_selector(tmp_path):
    """All candidates fail to render → blocked, selector never called."""
    orch, req, reselect_plan, _, _ = _make_reselect_orch_with_candidate(tmp_path)

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan),
        # render_candidates returns empty dict — all failed to render
        patch.object(orch, "_render_candidates", return_value={}),
        # current template renders successfully (Req 6: mandatory evidence)
        patch.object(orch, "_render_current_template",
                     return_value=tmp_path / "current.png"),
    ):
        (tmp_path / "current.png").write_bytes(b"fake_png")
        result = orch.recover(req, tmp_path)

    assert result.status == "blocked"
    assert result.model_calls["template_selection"] == 0
    orch._selector.preflight.assert_not_called()
    orch._selector.select_prepared.assert_not_called()


def test_unrenderable_candidate_excluded_from_eligibility_log(tmp_path):
    """Unrenderable candidates appear in eligibility_log with exclusion_reason=render_failed."""
    orch, req, reselect_plan, _, _ = _make_reselect_orch_with_candidate(tmp_path)

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan),
        patch.object(orch, "_render_candidates", return_value={}),  # render fails
        patch.object(orch, "_render_current_template",
                     return_value=tmp_path / "current.png"),
    ):
        (tmp_path / "current.png").write_bytes(b"fake_png")
        result = orch.recover(req, tmp_path)

    assert result.candidate_eligibility_log is not None
    render_failed = [
        e for e in result.candidate_eligibility_log
        if e.exclusion_reason == "render_failed"
    ]
    assert len(render_failed) == 1
    assert render_failed[0].eligible is False


# ---------------------------------------------------------------------------
# Eligibility log completeness
# ---------------------------------------------------------------------------


def test_eligibility_log_contains_no_library_record_exclusion(tmp_path):
    """Candidates with no library record appear in eligibility_log."""
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    mock_result = MagicMock()
    mock_result.slide_id = "slide-no-record"
    mock_result.deck_id = "deck-no-record"
    mock_result.slide_number = 5
    mock_result.rank = 1
    orch._searcher.search.return_value = [mock_result]

    # No library record
    orch._library.get_slide.return_value = None

    with patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan):
        result = orch.recover(req, tmp_path)

    assert result.status == "blocked"
    assert result.candidate_eligibility_log is not None
    no_record = [
        e for e in result.candidate_eligibility_log
        if e.exclusion_reason == "no_library_record"
    ]
    assert len(no_record) == 1


def test_eligibility_log_contains_structural_clone_exclusion(tmp_path):
    """Candidates that are structural clones appear in eligibility_log."""
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    mock_result = MagicMock()
    mock_result.slide_id = "slide-cand-clone"
    mock_result.deck_id = "deck-abc123"
    mock_result.slide_number = 9
    mock_result.rank = 1
    orch._searcher.search.return_value = [mock_result]

    mock_record = MagicMock()
    mock_record.preview_path = None
    mock_record.source_deck_path = str(tmp_path / "source.pptx")
    (tmp_path / "source.pptx").write_bytes(b"fake")
    orch._library.get_slide.return_value = mock_record
    orch._library.get_classification.return_value = None

    # Return IDENTICAL slot map as current → structural clone
    current_slot_map = make_slot_map()
    orch._library.get_slot_map.return_value = (
        current_slot_map.model_dump_json(), "fp-same", "2024-01-01"
    )

    with patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan):
        result = orch.recover(req, tmp_path)

    assert result.status == "blocked"
    clone_entries = [
        e for e in result.candidate_eligibility_log
        if e.exclusion_reason == "structural_clone"
    ]
    assert len(clone_entries) == 1


# ---------------------------------------------------------------------------
# Req 6: current template render failure blocks before selector
# ---------------------------------------------------------------------------


def test_current_template_render_failure_blocks_before_selector(tmp_path):
    """If current template cannot be rendered, return blocked before selector.

    Req 6: current_template_render_failed is mandatory evidence for comparative
    template selection.  A failed render must not be silently ignored.
    """
    orch, req, reselect_plan, _, _ = _make_reselect_orch_with_candidate(tmp_path)

    with (
        patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan),
        patch.object(orch, "_render_candidates",
                     return_value={"SC1": tmp_path / "SC1.png"}),
        # current template render returns None (failure)
        patch.object(orch, "_render_current_template", return_value=None),
    ):
        (tmp_path / "SC1.png").write_bytes(b"fake_png")
        result = orch.recover(req, tmp_path)

    assert result.status == "blocked"
    assert result.model_calls["template_selection"] == 0
    orch._selector.preflight.assert_not_called()
    orch._selector.select_prepared.assert_not_called()


# ---------------------------------------------------------------------------
# Req 8: all top-k results audited (vision_candidate_limit for excess eligible)
# ---------------------------------------------------------------------------


def test_all_top_k_results_audited_with_vision_candidate_limit(tmp_path):
    """All hybrid results produce eligibility records; excess eligible ones
    get exclusion_reason=vision_candidate_limit (not silently dropped).
    """
    req = make_recovery_request(
        output_pptx=tmp_path / "output.pptx",
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
    )
    (tmp_path / "template.pptx").write_bytes(b"fake")
    (tmp_path / "generated.pptx").write_bytes(b"fake")

    orch = _make_orchestrator()
    reselect_plan = _make_plan(StructuralRecoveryRoute.RESELECT_TEMPLATE)

    # 7 distinct candidates — all will pass eligibility except the limit
    # Vision candidate limit is 5, so candidate 6 and 7 → vision_candidate_limit
    mock_results = []
    for i in range(7):
        r = MagicMock()
        r.slide_id = f"slide-cand-{i+1:03d}"
        r.deck_id = f"deck-cand-{i+1:03d}"
        r.slide_number = i + 2
        r.rank = i + 1
        mock_results.append(r)
    orch._searcher.search.return_value = mock_results

    # All return a record with a source PPTX
    source_pptx = tmp_path / "source.pptx"
    source_pptx.write_bytes(b"fake")
    mock_record = MagicMock()
    mock_record.preview_path = None
    mock_record.source_deck_path = str(source_pptx)
    orch._library.get_slide.return_value = mock_record
    orch._library.get_classification.return_value = None

    # Each candidate has a distinct slot to avoid structural clone exclusion
    def make_cand_slot_map(idx):
        return make_slot_map(
            slide_id=f"slide-cand-{idx:03d}",
            deck_id=f"deck-cand-{idx:03d}",
            slide_number=idx + 1,
            slots=[
                make_slot(
                    slot_id=f"cand-s-{idx}",
                    shape_id=idx + 30,
                    shape_path=str(idx + 30),
                    slot_role=SlotRole.TITLE,
                    semantic_label="Title",
                    x_emu=228600 + idx * 10000,
                    y_emu=228600,
                    w_emu=11430000,
                    h_emu=800000,
                    x_ratio=0.02 + idx * 0.001,
                ),
            ],
        )

    call_idx = [0]

    def get_slot_map_side_effect(slide_id, version):
        idx = call_idx[0]
        call_idx[0] += 1
        sm = make_cand_slot_map(idx)
        return (sm.model_dump_json(), f"fp-{idx}", "2024-01-01")

    orch._library.get_slot_map.side_effect = get_slot_map_side_effect

    with patch.object(orch._diagnosis, "diagnose", return_value=reselect_plan):
        result = orch.recover(req, tmp_path)

    # All 7 hybrid results must produce exactly 1 eligibility record each
    assert result.candidate_eligibility_log is not None
    assert len(result.candidate_eligibility_log) == 7

    # Exactly 2 records should have vision_candidate_limit exclusion reason
    capped = [
        e for e in result.candidate_eligibility_log
        if e.exclusion_reason == "vision_candidate_limit"
    ]
    assert len(capped) == 2

    # First 5 eligible ones must have eligible=True before render step
    eligible_before_render = [
        e for e in result.candidate_eligibility_log
        if e.eligible or e.candidate_key is not None
    ]
    assert len(eligible_before_render) == 5
