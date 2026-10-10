"""Tests for M10 domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.structural.models import (
    CandidateReference,
    StructuralCandidateInfo,
    StructuralDrift,
    StructuralRecoveryPlan,
    StructuralRecoveryRequest,
    StructuralRecoveryResult,
    StructuralRecoveryRoute,
    StructuralSelectionOutput,
)
from slidestein.structural.versions import (
    STRUCTURAL_RECOVERY_POLICY_VERSION,
    STRUCTURAL_RECOVERY_SCHEMA_VERSION,
)

from .conftest import (
    make_brief,
    make_complete_draft,
    make_m9_plan,
    make_manager_review,
    make_recovery_request,
    make_slot_map,
    make_visual_qa,
)
from slidestein.revision.models import RevisionRoute


# ---------------------------------------------------------------------------
# StructuralRecoveryRoute
# ---------------------------------------------------------------------------


def test_route_values():
    assert StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE.value == "rebuild_current_template"
    assert StructuralRecoveryRoute.RESELECT_TEMPLATE.value == "reselect_template"
    assert StructuralRecoveryRoute.MANUAL_REVIEW.value == "manual_review"


def test_route_is_str_enum():
    assert isinstance(StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE, str)


# ---------------------------------------------------------------------------
# StructuralDrift
# ---------------------------------------------------------------------------


def test_drift_missing_shape():
    d = StructuralDrift(
        key="K1",
        slot_id="slot-001",
        shape_path="21",
        template_geometry={"x": 100, "y": 100, "width": 500, "height": 200},
        generated_geometry=None,
        drift_type="missing_shape",
    )
    assert d.drift_type == "missing_shape"
    assert d.generated_geometry is None


def test_drift_position_changed():
    d = StructuralDrift(
        key="K2",
        slot_id="slot-002",
        shape_path="22",
        template_geometry={"x": 100, "y": 100, "width": 500, "height": 200},
        generated_geometry={"x": 120, "y": 100, "width": 500, "height": 200},
        drift_type="position_changed",
    )
    assert d.drift_type == "position_changed"


def test_drift_invalid_type():
    with pytest.raises(ValidationError):
        StructuralDrift(
            key="K1",
            slot_id="slot-001",
            shape_path="21",
            template_geometry={"x": 100},
            drift_type="completely_wrong",
        )


def test_drift_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        StructuralDrift(
            key="K1",
            slot_id="slot-001",
            shape_path="21",
            template_geometry={"x": 100},
            drift_type="missing_shape",
            extra_field="bad",
        )


# ---------------------------------------------------------------------------
# StructuralRecoveryPlan
# ---------------------------------------------------------------------------


def _make_plan(route=StructuralRecoveryRoute.RESELECT_TEMPLATE):
    return StructuralRecoveryPlan(
        slide_id="slide-001",
        deck_id="deck-001",
        slide_number=2,
        route=route,
        reasons=["Template is a poor structural fit."],
        current_template_slide_id="slide-001",
        requires_candidate_retrieval=(route == StructuralRecoveryRoute.RESELECT_TEMPLATE),
        requires_selection_call=(route == StructuralRecoveryRoute.RESELECT_TEMPLATE),
        requires_redraft_call=(route == StructuralRecoveryRoute.RESELECT_TEMPLATE),
    )


def test_plan_schema_version_default():
    p = _make_plan()
    assert p.schema_version == STRUCTURAL_RECOVERY_SCHEMA_VERSION


def test_plan_policy_version_default():
    p = _make_plan()
    assert p.policy_version == STRUCTURAL_RECOVERY_POLICY_VERSION


def test_plan_reasons_non_empty():
    with pytest.raises(ValidationError):
        StructuralRecoveryPlan(
            slide_id="s",
            deck_id="d",
            slide_number=1,
            route=StructuralRecoveryRoute.MANUAL_REVIEW,
            reasons=[],
            current_template_slide_id="s",
            requires_candidate_retrieval=False,
            requires_selection_call=False,
            requires_redraft_call=False,
        )


def test_plan_max_structural_cycles_default():
    p = _make_plan()
    assert p.max_structural_cycles == 1


def test_plan_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        StructuralRecoveryPlan(
            slide_id="s",
            deck_id="d",
            slide_number=1,
            route=StructuralRecoveryRoute.MANUAL_REVIEW,
            reasons=["ok"],
            current_template_slide_id="s",
            requires_candidate_retrieval=False,
            requires_selection_call=False,
            requires_redraft_call=False,
            unknown_field="bad",
        )


# ---------------------------------------------------------------------------
# CandidateReference
# ---------------------------------------------------------------------------


def test_candidate_reference_fields():
    ref = CandidateReference(
        candidate_key="SC1",
        slide_id="slide-cand-001",
        deck_id="deck-cand-001",
        slide_number=3,
        hybrid_rank=1,
        structural_fingerprint="abc123",
    )
    assert ref.candidate_key == "SC1"
    assert ref.hybrid_rank == 1


def test_candidate_reference_extra_forbidden():
    with pytest.raises(ValidationError):
        CandidateReference(
            candidate_key="SC1",
            slide_id="s",
            deck_id="d",
            slide_number=1,
            hybrid_rank=1,
            structural_fingerprint="fp",
            extra="bad",
        )


# ---------------------------------------------------------------------------
# StructuralCandidateInfo
# ---------------------------------------------------------------------------


def test_candidate_info_fields():
    info = StructuralCandidateInfo(
        candidate_key="SC1",
        slide_id="slide-001",
        deck_id="deck-001",
        slide_number=3,
        has_title_slot=True,
        editable_slot_count=3,
        slot_count=4,
        slot_summary="K1 (title); K2 (body)",
        structural_fingerprint="fp-001",
    )
    assert info.visual_archetype == ""  # default


def test_candidate_info_visual_archetype_optional():
    info = StructuralCandidateInfo(
        candidate_key="SC1",
        slide_id="s",
        deck_id="d",
        slide_number=1,
        has_title_slot=True,
        editable_slot_count=2,
        slot_count=2,
        slot_summary="K1, K2",
        structural_fingerprint="fp",
        visual_archetype="matrix",
    )
    assert info.visual_archetype == "matrix"


# ---------------------------------------------------------------------------
# StructuralSelectionOutput
# ---------------------------------------------------------------------------


def test_selection_output_valid():
    out = StructuralSelectionOutput(
        selected_candidate_key="SC2",
        rationale="Better structural balance.",
    )
    assert out.selected_candidate_key == "SC2"


def test_selection_output_blank_key_rejected():
    with pytest.raises(ValidationError):
        StructuralSelectionOutput(selected_candidate_key="  ", rationale="ok")


def test_selection_output_blank_rationale_rejected():
    with pytest.raises(ValidationError):
        StructuralSelectionOutput(selected_candidate_key="SC1", rationale="")


# ---------------------------------------------------------------------------
# StructuralRecoveryRequest
# ---------------------------------------------------------------------------


def test_recovery_request_valid():
    req = make_recovery_request()
    assert req.m9_plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert req.current_draft.is_complete


def test_recovery_request_extra_forbidden():
    from pathlib import Path
    with pytest.raises(ValidationError):
        StructuralRecoveryRequest(
            brief=make_brief(),
            current_draft=make_complete_draft(),
            current_slot_map=make_slot_map(),
            manager_review=make_manager_review(),
            visual_qa=make_visual_qa(),
            m9_plan=make_m9_plan(),
            template_pptx=Path("template.pptx"),
            generated_pptx=Path("generated.pptx"),
            extra_field="bad",
        )


# ---------------------------------------------------------------------------
# StructuralRecoveryResult
# ---------------------------------------------------------------------------


def test_result_schema_version_default():
    plan = _make_plan()
    r = StructuralRecoveryResult(
        route=StructuralRecoveryRoute.MANUAL_REVIEW,
        status="escalation_required",
        slide_id="s",
        deck_id="d",
        slide_number=1,
        plan=plan,
        content_changed=False,
        manager_review_effective=make_manager_review(),
    )
    assert r.schema_version == STRUCTURAL_RECOVERY_SCHEMA_VERSION
    assert r.policy_version == STRUCTURAL_RECOVERY_POLICY_VERSION


def test_result_default_model_calls():
    plan = _make_plan()
    r = StructuralRecoveryResult(
        route=StructuralRecoveryRoute.MANUAL_REVIEW,
        status="escalation_required",
        slide_id="s",
        deck_id="d",
        slide_number=1,
        plan=plan,
        content_changed=False,
        manager_review_effective=make_manager_review(),
    )
    assert r.model_calls == {
        "retrieval_embedding": 0,
        "template_selection": 0,
        "drafting": 0,
        "manager_review": 0,
        "visual_qa": 0,
    }


def test_result_final_ready_default_false():
    plan = _make_plan()
    r = StructuralRecoveryResult(
        route=StructuralRecoveryRoute.MANUAL_REVIEW,
        status="escalation_required",
        slide_id="s",
        deck_id="d",
        slide_number=1,
        plan=plan,
        content_changed=False,
        manager_review_effective=make_manager_review(),
    )
    assert r.final_ready is False


def test_result_invalid_status_rejected():
    plan = _make_plan()
    with pytest.raises(ValidationError):
        StructuralRecoveryResult(
            route=StructuralRecoveryRoute.MANUAL_REVIEW,
            status="not_a_real_status",
            slide_id="s",
            deck_id="d",
            slide_number=1,
            plan=plan,
            content_changed=False,
            manager_review_effective=make_manager_review(),
        )


def test_result_json_round_trip():
    plan = _make_plan()
    r = StructuralRecoveryResult(
        route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
        status="blocked",
        slide_id="slide-001",
        deck_id="deck-001",
        slide_number=2,
        plan=plan,
        content_changed=False,
        manager_review_effective=make_manager_review(),
        final_ready=False,
    )
    json_str = r.model_dump_json()
    r2 = StructuralRecoveryResult.model_validate_json(json_str)
    assert r2.route == r.route
    assert r2.status == r.status
    assert r2.slide_id == r.slide_id
