"""Corruption-control fixture tests for M10 structural diagnosis.

These tests verify that geometry modifications are reliably detected as
structural drift and correctly routed to rebuild_current_template.

Design intent (requirement 23):
  Simulate a "K3 geometry corruption" — a generated PPTX where K3's shape
  has shifted position relative to the template.  The content identity check
  passes (text is correct) but the geometry comparison detects drift, so
  diagnosis must route to rebuild_current_template.

These are DETERMINISTIC tests.  Zero provider/API calls.
No real PPTX files are required — geometry reads are mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from slidestein.structural.diagnosis import StructuralDiagnosisService
from slidestein.structural.errors import StructuralRecoveryError
from slidestein.structural.models import StructuralRecoveryRoute
from slidestein.slots.roles import SlotRole
from slidestein.structural.models import StructuralRecoveryRequest

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


def _make_3slot_slot_map(slide_id="slide-cc-001", deck_id="deck-cc-001"):
    """TemplateSlotMap with K1 (Title), K2 (Body), K3 (CalloutBox)."""
    return make_slot_map(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=2,
        slots=[
            make_slot(
                slot_id="slot-001", shape_id=21, shape_path="21",
                slot_role=SlotRole.TITLE, semantic_label="Title",
                x_emu=457200, y_emu=457200, w_emu=10972800, h_emu=685800,
                y_ratio=0.07, x_ratio=0.04,
            ),
            make_slot(
                slot_id="slot-002", shape_id=22, shape_path="22",
                slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
                x_emu=457200, y_emu=1143000, w_emu=6858000, h_emu=4572000,
                y_ratio=0.25, x_ratio=0.04, max_chars=300, max_lines=8,
            ),
            make_slot(
                slot_id="slot-003", shape_id=23, shape_path="23",
                slot_role=SlotRole.BODY_TEXT, semantic_label="Callout Box",
                x_emu=7315200, y_emu=1143000, w_emu=4114800, h_emu=4572000,
                y_ratio=0.25, x_ratio=0.60, max_chars=120, max_lines=4,
            ),
        ],
    )


def _make_3slot_draft(slide_id="slide-cc-001", deck_id="deck-cc-001"):
    from slidestein.drafting.models import SlideContentDraft

    return SlideContentDraft(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=2,
        brief_key_message="Digital transformation drives efficiency.",
        assignments=[
            make_assignment("slot-001", 21, "21", SlotRole.TITLE, "Title",
                            text="Digital Transformation Drives Efficiency"),
            make_assignment("slot-002", 22, "22", SlotRole.BODY_TEXT, "Body",
                            text="Stream A, Stream B, Stream C.",
                            max_chars=300, max_lines=8),
            make_assignment("slot-003", 23, "23", SlotRole.BODY_TEXT, "Callout Box",
                            text="Key benefit: 20% faster cycle time.",
                            max_chars=120, max_lines=4),
        ],
        drafting_summary="3-slot corruption-control draft.",
        is_complete=True,
    )


def _make_3slot_request(tmp_path=None):
    slot_map = _make_3slot_slot_map()
    draft = _make_3slot_draft()

    return StructuralRecoveryRequest(
        brief=make_brief(),
        source_material="Source material for corruption control test.",
        current_draft=draft,
        current_slot_map=slot_map,
        manager_review=make_manager_review(
            slide_id=slot_map.slide_id, deck_id=slot_map.deck_id
        ),
        visual_qa=make_visual_qa(
            slide_id=slot_map.slide_id, deck_id=slot_map.deck_id
        ),
        m9_plan=make_m9_plan(
            slide_id=slot_map.slide_id, deck_id=slot_map.deck_id
        ),
        template_pptx=Path("data/test_decks/template.pptx"),
        generated_pptx=Path("data/test_decks/generated.pptx"),
    )


# Canonical template geometry — K1, K2, K3 at known positions
_TEMPLATE_GEOS = {
    "K1": {"x": 457200, "y": 457200, "width": 10972800, "height": 685800},
    "K2": {"x": 457200, "y": 1143000, "width": 6858000, "height": 4572000},
    "K3": {"x": 7315200, "y": 1143000, "width": 4114800, "height": 4572000},
}


def _run_diagnosis_with_geos(request, template_geos, generated_geos):
    svc = StructuralDiagnosisService()
    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries") as mock_read,
        patch.object(svc, "_verify_content_identity"),
    ):
        mock_resolve.return_value = (2, "native-001")
        mock_read.side_effect = [template_geos, generated_geos]
        return svc.diagnose(request)


# ---------------------------------------------------------------------------
# Positive control: no drift → reselect
# ---------------------------------------------------------------------------


def test_corruption_control_no_drift_routes_to_reselect():
    """Baseline: template = generated → no drift → reselect_template.

    This confirms the control works before we apply any corruption.
    """
    request = _make_3slot_request()
    # Generated exactly matches template
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, _TEMPLATE_GEOS.copy())
    assert plan.route == StructuralRecoveryRoute.RESELECT_TEMPLATE
    assert plan.structural_drifts == []


# ---------------------------------------------------------------------------
# K3 geometry corruption — position shift
# ---------------------------------------------------------------------------


def test_k3_position_drift_routes_to_rebuild():
    """K3 x-coordinate shifts → drift detected → rebuild_current_template."""
    request = _make_3slot_request()
    generated_geos = {
        "K1": _TEMPLATE_GEOS["K1"].copy(),
        "K2": _TEMPLATE_GEOS["K2"].copy(),
        "K3": {  # K3 x shifted by 457200 EMU (~1/2 inch)
            "x": _TEMPLATE_GEOS["K3"]["x"] + 457200,
            "y": _TEMPLATE_GEOS["K3"]["y"],
            "width": _TEMPLATE_GEOS["K3"]["width"],
            "height": _TEMPLATE_GEOS["K3"]["height"],
        },
    }
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, generated_geos)
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    assert any(d.key == "K3" and d.drift_type == "position_changed" for d in plan.structural_drifts)


def test_k3_size_drift_routes_to_rebuild():
    """K3 width grows → drift detected → rebuild_current_template."""
    request = _make_3slot_request()
    generated_geos = {
        "K1": _TEMPLATE_GEOS["K1"].copy(),
        "K2": _TEMPLATE_GEOS["K2"].copy(),
        "K3": {
            "x": _TEMPLATE_GEOS["K3"]["x"],
            "y": _TEMPLATE_GEOS["K3"]["y"],
            "width": _TEMPLATE_GEOS["K3"]["width"] + 228600,  # width increased
            "height": _TEMPLATE_GEOS["K3"]["height"],
        },
    }
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, generated_geos)
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    assert any(d.key == "K3" and d.drift_type == "size_changed" for d in plan.structural_drifts)


def test_k3_position_and_size_drift_routes_to_rebuild():
    """K3 position AND size change → drift_type=position_and_size_changed."""
    request = _make_3slot_request()
    generated_geos = {
        "K1": _TEMPLATE_GEOS["K1"].copy(),
        "K2": _TEMPLATE_GEOS["K2"].copy(),
        "K3": {
            "x": _TEMPLATE_GEOS["K3"]["x"] + 114300,
            "y": _TEMPLATE_GEOS["K3"]["y"] + 228600,
            "width": _TEMPLATE_GEOS["K3"]["width"] - 114300,
            "height": _TEMPLATE_GEOS["K3"]["height"] + 114300,
        },
    }
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, generated_geos)
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    k3_drift = next(d for d in plan.structural_drifts if d.key == "K3")
    assert k3_drift.drift_type == "position_and_size_changed"


def test_k3_missing_shape_routes_to_rebuild():
    """K3 shape missing from generated slide → drift_type=missing_shape."""
    request = _make_3slot_request()
    generated_geos = {
        "K1": _TEMPLATE_GEOS["K1"].copy(),
        "K2": _TEMPLATE_GEOS["K2"].copy(),
        "K3": None,  # shape missing
    }
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, generated_geos)
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    assert any(d.key == "K3" and d.drift_type == "missing_shape" for d in plan.structural_drifts)


# ---------------------------------------------------------------------------
# Only K3 drifts — K1 and K2 remain correct
# ---------------------------------------------------------------------------


def test_only_k3_in_structural_drifts_when_k1_k2_ok():
    """Drift list contains exactly K3 — K1 and K2 have no drift entries."""
    request = _make_3slot_request()
    generated_geos = {
        "K1": _TEMPLATE_GEOS["K1"].copy(),
        "K2": _TEMPLATE_GEOS["K2"].copy(),
        "K3": {
            "x": _TEMPLATE_GEOS["K3"]["x"] + 300000,
            "y": _TEMPLATE_GEOS["K3"]["y"],
            "width": _TEMPLATE_GEOS["K3"]["width"],
            "height": _TEMPLATE_GEOS["K3"]["height"],
        },
    }
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, generated_geos)
    drifted_keys = {d.key for d in plan.structural_drifts}
    assert drifted_keys == {"K3"}


# ---------------------------------------------------------------------------
# Content identity verification is INDEPENDENT from geometry comparison
# ---------------------------------------------------------------------------


def test_content_identity_failure_raises_before_geometry_comparison():
    """Content mismatch raises StructuralRecoveryError regardless of geometry."""
    request = _make_3slot_request()
    svc = StructuralDiagnosisService()
    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries"),
        patch.object(svc, "_verify_content_identity",
                     side_effect=StructuralRecoveryError("K3 content mismatch")),
    ):
        mock_resolve.return_value = (2, "native-001")
        with pytest.raises(StructuralRecoveryError, match="K3 content mismatch"):
            svc.diagnose(request)


# ---------------------------------------------------------------------------
# Drift record completeness
# ---------------------------------------------------------------------------


def test_k3_drift_record_carries_correct_geometry():
    """StructuralDrift for K3 records both template and generated geometry."""
    request = _make_3slot_request()
    drifted_k3_geo = {
        "x": _TEMPLATE_GEOS["K3"]["x"] + 457200,
        "y": _TEMPLATE_GEOS["K3"]["y"],
        "width": _TEMPLATE_GEOS["K3"]["width"],
        "height": _TEMPLATE_GEOS["K3"]["height"],
    }
    generated_geos = {
        "K1": _TEMPLATE_GEOS["K1"].copy(),
        "K2": _TEMPLATE_GEOS["K2"].copy(),
        "K3": drifted_k3_geo,
    }
    plan = _run_diagnosis_with_geos(request, _TEMPLATE_GEOS, generated_geos)
    k3_drift = next(d for d in plan.structural_drifts if d.key == "K3")
    assert k3_drift.template_geometry == _TEMPLATE_GEOS["K3"]
    assert k3_drift.generated_geometry == drifted_k3_geo
    assert k3_drift.slot_id == "slot-003"
    assert k3_drift.shape_path == "23"
