"""Tests for StructuralDiagnosisService — _classify_drift and routing logic.

All geometry reads are mocked; no PPTX files are needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.structural.diagnosis import (
    StructuralDiagnosisService,
    _classify_drift,
)
from slidestein.structural.errors import StructuralRecoveryError
from slidestein.structural.models import StructuralRecoveryRoute

from .conftest import make_recovery_request


# ---------------------------------------------------------------------------
# _classify_drift — unit tests (pure function)
# ---------------------------------------------------------------------------


def test_classify_drift_none_when_identical():
    geo = {"x": 100, "y": 200, "width": 500, "height": 300}
    assert _classify_drift(geo, geo.copy()) is None


def test_classify_drift_missing_shape():
    geo = {"x": 100, "y": 200, "width": 500, "height": 300}
    assert _classify_drift(geo, None) == "missing_shape"
    assert _classify_drift(geo, {}) == "missing_shape"


def test_classify_drift_position_changed():
    t = {"x": 100, "y": 200, "width": 500, "height": 300}
    g = {"x": 110, "y": 200, "width": 500, "height": 300}
    assert _classify_drift(t, g) == "position_changed"


def test_classify_drift_size_changed():
    t = {"x": 100, "y": 200, "width": 500, "height": 300}
    g = {"x": 100, "y": 200, "width": 600, "height": 300}
    assert _classify_drift(t, g) == "size_changed"


def test_classify_drift_position_and_size_changed():
    t = {"x": 100, "y": 200, "width": 500, "height": 300}
    g = {"x": 110, "y": 220, "width": 600, "height": 400}
    assert _classify_drift(t, g) == "position_and_size_changed"


def test_classify_drift_y_position_change():
    t = {"x": 100, "y": 200, "width": 500, "height": 300}
    g = {"x": 100, "y": 210, "width": 500, "height": 300}
    assert _classify_drift(t, g) == "position_changed"


def test_classify_drift_height_size_change():
    t = {"x": 100, "y": 200, "width": 500, "height": 300}
    g = {"x": 100, "y": 200, "width": 500, "height": 400}
    assert _classify_drift(t, g) == "size_changed"


# ---------------------------------------------------------------------------
# StructuralDiagnosisService — routing (geometry mocked)
# ---------------------------------------------------------------------------


def _patch_diagnosis(request, template_geos, generated_geos, content_ok=True):
    """Run diagnose() with mocked PPTX reads."""
    svc = StructuralDiagnosisService()

    def _mock_content_verify(generated_pptx, slide_number, slot_key_map, draft):
        if not content_ok:
            raise StructuralRecoveryError("Content identity mismatch (mocked)")

    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries") as mock_read_geo,
        patch.object(svc, "_verify_content_identity", side_effect=_mock_content_verify),
    ):
        # resolve_slide_by_stable_id is called twice: once for generated, once for template
        mock_resolve.return_value = (2, "native-001")
        mock_read_geo.side_effect = [template_geos, generated_geos]

        return svc.diagnose(request)


def test_no_drift_routes_to_reselect():
    request = make_recovery_request()
    slot_map = request.current_slot_map
    # Both template and generated have identical geometry → no drift
    identical_geos = {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
                      "K2": {"x": 100, "y": 600, "width": 500, "height": 800}}
    plan = _patch_diagnosis(request, identical_geos, identical_geos)
    assert plan.route == StructuralRecoveryRoute.RESELECT_TEMPLATE
    assert plan.structural_drifts == []
    assert plan.requires_candidate_retrieval is True
    assert plan.requires_selection_call is True


def test_drift_routes_to_rebuild():
    request = make_recovery_request()
    template_geos = {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
                     "K2": {"x": 100, "y": 600, "width": 500, "height": 800}}
    generated_geos = {"K1": {"x": 200, "y": 200, "width": 500, "height": 300},  # x changed
                      "K2": {"x": 100, "y": 600, "width": 500, "height": 800}}
    plan = _patch_diagnosis(request, template_geos, generated_geos)
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    assert len(plan.structural_drifts) == 1
    assert plan.structural_drifts[0].key == "K1"
    assert plan.structural_drifts[0].drift_type == "position_changed"
    assert plan.requires_candidate_retrieval is False


def test_missing_shape_routes_to_rebuild():
    request = make_recovery_request()
    template_geos = {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
                     "K2": {"x": 100, "y": 600, "width": 500, "height": 800}}
    generated_geos = {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
                      "K2": {}}  # empty = missing
    plan = _patch_diagnosis(request, template_geos, generated_geos)
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE
    assert any(d.drift_type == "missing_shape" for d in plan.structural_drifts)


def test_content_identity_failure_raises():
    request = make_recovery_request()
    svc = StructuralDiagnosisService()
    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries"),
        patch.object(svc, "_verify_content_identity",
                     side_effect=StructuralRecoveryError("mismatch")),
    ):
        mock_resolve.return_value = (2, "native-001")
        with pytest.raises(StructuralRecoveryError, match="mismatch"):
            svc.diagnose(request)


def test_template_geo_none_routes_to_manual():
    request = make_recovery_request()
    svc = StructuralDiagnosisService()
    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries") as mock_read,
        patch.object(svc, "_verify_content_identity"),
    ):
        mock_resolve.return_value = (2, "native-001")
        mock_read.side_effect = [None, {"K1": {"x": 1}}]  # template returns None
        plan = svc.diagnose(request)
    assert plan.route == StructuralRecoveryRoute.MANUAL_REVIEW


def test_generated_geo_none_routes_to_manual():
    request = make_recovery_request()
    svc = StructuralDiagnosisService()
    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries") as mock_read,
        patch.object(svc, "_verify_content_identity"),
    ):
        mock_resolve.return_value = (2, "native-001")
        mock_read.side_effect = [{"K1": {"x": 1}}, None]  # generated returns None
        plan = svc.diagnose(request)
    assert plan.route == StructuralRecoveryRoute.MANUAL_REVIEW


def test_no_deck_id_routes_to_manual():
    from .conftest import make_slot_map, make_complete_draft, make_manager_review, make_visual_qa, make_m9_plan, make_brief
    from slidestein.structural.models import StructuralRecoveryRequest

    sm_no_deck = make_slot_map(deck_id=None)
    request = StructuralRecoveryRequest(
        brief=make_brief(),
        current_draft=make_complete_draft(deck_id=None),
        current_slot_map=sm_no_deck,
        manager_review=make_manager_review(deck_id=None),
        visual_qa=make_visual_qa(deck_id=None),
        m9_plan=make_m9_plan(deck_id=None),
        template_pptx=Path("template.pptx"),
        generated_pptx=Path("generated.pptx"),
    )
    svc = StructuralDiagnosisService()
    plan = svc.diagnose(request)
    assert plan.route == StructuralRecoveryRoute.MANUAL_REVIEW


def test_plan_slide_identity_propagated():
    request = make_recovery_request(slide_id="slide-xxx", deck_id="deck-yyy", slide_number=5)
    identical_geos = {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
                      "K2": {"x": 100, "y": 600, "width": 500, "height": 800}}
    plan = _patch_diagnosis(request, identical_geos, identical_geos)
    assert plan.slide_id == "slide-xxx"
    assert plan.deck_id == "deck-yyy"
    assert plan.slide_number == 5
