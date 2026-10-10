"""VisualQAService end-to-end tests (all external calls mocked) for M8."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from slidestein.drafting.models import SlotDraftAction, SlotDraftAssignment
from slidestein.qa.errors import LiveGeometryError, VisualQAError
from slidestein.qa.models import (
    NativeCheckStatus,
    NativeCheckType,
    NativeVisualCheck,
    VisualQAIssue,
    VisualQARequest,
)
from slidestein.qa.providers.sap_aicore import VisualQAGenerationError
from slidestein.qa.service import VisualQAService
from slidestein.slots.roles import SlotRole
from tests.test_qa.conftest import (
    make_assignment,
    make_complete_draft,
    make_native_check,
    make_slot,
    make_slot_map,
    make_visual_model_output,
)

# ---------------------------------------------------------------------------
# IO mock constants (match make_complete_draft default assignments)
# ---------------------------------------------------------------------------

_DEFAULT_TEXT_MAP = {
    "21": "Digital transformation drives efficiency.",
    "22": "Channel 1, Channel 2, Channel 3.",
}

_DEFAULT_LIVE_GEOS = {
    "K1": {"x_ratio": 0.04, "y_ratio": 0.07, "width_ratio": 0.88, "height_ratio": 0.09},
    "K2": {"x_ratio": 0.04, "y_ratio": 0.25, "width_ratio": 0.88, "height_ratio": 0.09},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    reviewer=None,
    renderer=None,
    overlay_builder=None,
    native_inspector=None,
):
    reviewer = reviewer or _mock_reviewer()
    renderer = renderer or MagicMock()
    overlay_builder = overlay_builder or MagicMock()
    if native_inspector is None:
        native_inspector = MagicMock()
        native_inspector.inspect.return_value = [make_native_check()]
    return VisualQAService(
        reviewer=reviewer,
        renderer=renderer,
        overlay_builder=overlay_builder,
        native_inspector=native_inspector,
    )


def _mock_reviewer(output=None):
    rev = MagicMock()
    rev.review.return_value = output or make_visual_model_output()
    return rev


def _make_request(tmp_path, draft=None, slot_map=None):
    return VisualQARequest(
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
        draft=draft or make_complete_draft(),
        slot_map=slot_map or make_slot_map(),
    )


def _run_with_mocked_resolver(
    service,
    request,
    artifacts_dir,
    text_map=None,
    live_geos=None,
):
    """Run service.review() with stable slide resolver and IO functions monkeypatched."""
    _text_map = text_map if text_map is not None else _DEFAULT_TEXT_MAP
    _live_geos = live_geos if live_geos is not None else _DEFAULT_LIVE_GEOS

    def _fake_read_shape_text(pptx_path, slide_number, shape_path):
        return _text_map.get(shape_path)

    with patch("slidestein.qa.service.resolve_slide_by_stable_id", return_value=(2, 256)), \
         patch("slidestein.qa.service.read_live_slot_geometries", return_value=_live_geos), \
         patch("slidestein.qa.service.read_shape_text", side_effect=_fake_read_shape_text), \
         patch("slidestein.qa.service.normalize_readback", side_effect=lambda x: x):
        return service.review(request, artifacts_dir)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_reviewer_called_exactly_once(tmp_path):
    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    reviewer.review.assert_called_once()


def test_renderer_called_for_template_and_generated(tmp_path):
    renderer = MagicMock()
    service = _make_service(renderer=renderer)

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    assert renderer.render.call_count == 2


def test_overlay_builder_called_once(tmp_path):
    overlay_builder = MagicMock()
    service = _make_service(overlay_builder=overlay_builder)

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    overlay_builder.build.assert_called_once()


def test_native_inspector_called_once(tmp_path):
    native_inspector = MagicMock()
    native_inspector.inspect.return_value = []
    service = _make_service(native_inspector=native_inspector)

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    native_inspector.inspect.assert_called_once()


def test_result_has_correct_average_score(tmp_path):
    output = make_visual_model_output(
        scores={
            "text_fit_and_clipping": 5,
            "visual_hierarchy": 3,
            "alignment_and_spacing": 4,
            "balance_and_whitespace": 4,
            "typography_and_style_consistency": 3,
            "overall_readability": 5,
        }
    )
    reviewer = _mock_reviewer(output)
    service = _make_service(reviewer=reviewer)

    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    expected = round((5 + 3 + 4 + 4 + 3 + 5) / 6, 4)
    assert result.average_score == expected


def test_result_all_six_dimensions_copied(tmp_path):
    service = _make_service()
    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    assert result.text_fit_and_clipping.score == 5
    assert result.visual_hierarchy.score == 4
    assert result.alignment_and_spacing.score == 4
    assert result.balance_and_whitespace.score == 4
    assert result.typography_and_style_consistency.score == 4
    assert result.overall_readability.score == 4


def test_result_identity_application_owned(tmp_path):
    service = _make_service()
    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    assert result.slide_id == "slide-test-001"
    assert result.slide_number == 2
    assert result.resolved_generated_slide_number == 2  # from mocked resolver


def test_issues_propagated_to_result(tmp_path):
    issue = VisualQAIssue(
        severity="minor",
        category="alignment_and_spacing",
        slot_keys=["K1"],
        issue="Slight misalignment",
        evidence="Visible in image",
        recommendation="Adjust by 2px",
    )
    output = make_visual_model_output(issues=[issue])
    service = _make_service(reviewer=_mock_reviewer(output))

    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    assert len(result.issues) == 1
    assert result.issues[0].issue == "Slight misalignment"


def test_native_checks_propagated_to_result(tmp_path):
    checks = [
        NativeVisualCheck(
            check_type=NativeCheckType.TEXT_OVERFLOW,
            slot_key="K1",
            status=NativeCheckStatus.FAIL,
            details="Overflow detected",
        )
    ]
    native_inspector = MagicMock()
    native_inspector.inspect.return_value = checks
    service = _make_service(native_inspector=native_inspector)

    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    assert len(result.native_checks) == 1
    assert result.native_checks[0].status == NativeCheckStatus.FAIL


def test_executive_summary_propagated(tmp_path):
    output = make_visual_model_output(executive_summary="Excellent rendering quality.")
    service = _make_service(reviewer=_mock_reviewer(output))

    result = _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    assert result.executive_summary == "Excellent rendering quality."


def test_render_paths_in_result(tmp_path):
    service = _make_service()
    artifacts_dir = tmp_path / "artifacts"

    result = _run_with_mocked_resolver(service, _make_request(tmp_path), artifacts_dir)

    assert "generated.png" in result.generated_render_path
    assert "template.png" in result.template_render_path
    assert "overlay.png" in result.overlay_render_path


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_generation_error_propagates(tmp_path):
    reviewer = MagicMock()
    reviewer.review.side_effect = VisualQAGenerationError("Model failed")
    service = _make_service(reviewer=reviewer)

    with pytest.raises(VisualQAGenerationError):
        _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")


def test_unknown_k_key_in_issue_raises_visual_qa_error(tmp_path):
    issue = VisualQAIssue(
        severity="minor",
        category="visual_hierarchy",
        slot_keys=["K99"],  # unknown
        issue="Bad",
        evidence="image",
        recommendation="fix",
    )
    output = make_visual_model_output(issues=[issue])
    service = _make_service(reviewer=_mock_reviewer(output))

    with pytest.raises(VisualQAError, match="K99"):
        _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")


def test_renderer_exception_raises_visual_qa_error(tmp_path):
    renderer = MagicMock()
    renderer.render.side_effect = RuntimeError("COM crashed")
    service = _make_service(renderer=renderer)

    with pytest.raises(VisualQAError, match="render"):
        _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")


# ---------------------------------------------------------------------------
# Slot specs built correctly
# ---------------------------------------------------------------------------


def test_slot_specs_final_text_only_for_replace(tmp_path):
    """Clear slots must not expose historical current_text as final_text."""
    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    call_kwargs = reviewer.review.call_args
    slot_specs = call_kwargs[1]["slot_specs"] if call_kwargs[1] else call_kwargs[0][3]

    for spec in slot_specs:
        if spec.get("action") == "clear":
            assert "final_text" not in spec, "Clear slots must not have final_text"


def test_native_checks_passed_to_reviewer(tmp_path):
    """Native checks dict list is passed to Vision reviewer."""
    native_checks = [
        NativeVisualCheck(
            check_type=NativeCheckType.OUTSIDE_SLIDE_BOUNDS,
            slot_key="K1",
            status=NativeCheckStatus.PASS,
            details="OK",
        )
    ]
    native_inspector = MagicMock()
    native_inspector.inspect.return_value = native_checks
    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer, native_inspector=native_inspector)

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art")

    call_kwargs = reviewer.review.call_args
    passed_checks = call_kwargs[1]["native_checks"] if call_kwargs[1] else call_kwargs[0][4]
    assert len(passed_checks) == 1
    assert passed_checks[0]["status"] == "pass"


def test_no_provider_call_on_slide_id_mismatch(tmp_path):
    reviewer = MagicMock()
    service = _make_service(reviewer=reviewer)

    slot_map = make_slot_map(slide_id="DIFFERENT")
    draft = make_complete_draft(slide_id="ORIGINAL")
    request = _make_request(tmp_path, draft=draft, slot_map=slot_map)

    with pytest.raises(VisualQAError):
        _run_with_mocked_resolver(service, request, tmp_path / "art")

    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Content verification regression tests (hardening item: generated PPTX ↔ draft)
# ---------------------------------------------------------------------------


def test_content_verification_raises_on_text_mismatch(tmp_path):
    """REPLACE slot with wrong text in PPTX raises VisualQAError before Vision call."""
    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    # K1 expects "Digital transformation drives efficiency." but PPTX has "WRONG TEXT"
    bad_text_map = {
        "21": "WRONG TEXT — does not match draft",
        "22": "Channel 1, Channel 2, Channel 3.",
    }

    with pytest.raises(VisualQAError, match="Content verification failed"):
        _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art",
                                  text_map=bad_text_map)

    reviewer.review.assert_not_called()


def test_content_verification_raises_when_replace_shape_missing(tmp_path):
    """REPLACE slot where read_shape_text returns None raises VisualQAError."""
    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    # Shape not found → read_shape_text returns None
    missing_text_map = {
        "21": None,   # shape not found / no text frame
        "22": "Channel 1, Channel 2, Channel 3.",
    }

    with pytest.raises(VisualQAError, match="Content verification failed"):
        _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art",
                                  text_map=missing_text_map)

    reviewer.review.assert_not_called()


def test_content_verification_raises_on_clear_with_non_empty_text(tmp_path):
    """CLEAR slot that still contains text in PPTX raises VisualQAError."""
    from tests.test_qa.conftest import make_assignment  # noqa: PLC0415

    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    # Make K1 a CLEAR slot
    assignments = [
        make_assignment(slot_id="slot-001", shape_id=21, shape_path="21",
                        slot_role=SlotRole.TITLE, action=SlotDraftAction.CLEAR, text=None),
        make_assignment(slot_id="slot-002", shape_id=22, shape_path="22",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Channel 1, Channel 2, Channel 3."),
    ]
    draft = make_complete_draft(assignments=assignments)
    request = _make_request(tmp_path, draft=draft)

    # PPTX still has text in K1 (should be cleared but wasn't)
    bad_text_map = {"21": "Old title text still present", "22": "Channel 1, Channel 2, Channel 3."}

    with pytest.raises(VisualQAError, match="Content verification failed"):
        _run_with_mocked_resolver(service, request, tmp_path / "art",
                                  text_map=bad_text_map)

    reviewer.review.assert_not_called()


def test_content_verification_passes_for_clear_with_empty_text(tmp_path):
    """CLEAR slot with empty text in PPTX passes verification."""
    from tests.test_qa.conftest import make_assignment  # noqa: PLC0415

    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    assignments = [
        make_assignment(slot_id="slot-001", shape_id=21, shape_path="21",
                        slot_role=SlotRole.TITLE, action=SlotDraftAction.CLEAR, text=None),
        make_assignment(slot_id="slot-002", shape_id=22, shape_path="22",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Channel 1, Channel 2, Channel 3."),
    ]
    draft = make_complete_draft(assignments=assignments)
    request = _make_request(tmp_path, draft=draft)

    # K1 is empty (cleared correctly), K2 has expected text
    ok_text_map = {"21": "", "22": "Channel 1, Channel 2, Channel 3."}

    result = _run_with_mocked_resolver(service, request, tmp_path / "art",
                                       text_map=ok_text_map)

    reviewer.review.assert_called_once()


# ---------------------------------------------------------------------------
# CLEAR missing-shape contract (Item 3/4: None is not a successful CLEAR)
# ---------------------------------------------------------------------------


def test_clear_missing_shape_raises_before_render(tmp_path):
    """CLEAR slot where read_shape_text returns None raises VisualQAError (shape missing != cleared)."""
    reviewer = _mock_reviewer()
    renderer = MagicMock()
    service = _make_service(reviewer=reviewer, renderer=renderer)

    assignments = [
        make_assignment(slot_id="slot-001", shape_id=21, shape_path="21",
                        slot_role=SlotRole.TITLE, action=SlotDraftAction.CLEAR, text=None),
        make_assignment(slot_id="slot-002", shape_id=22, shape_path="22",
                        slot_role=SlotRole.BODY_TEXT,
                        text="Channel 1, Channel 2, Channel 3."),
    ]
    draft = make_complete_draft(assignments=assignments)
    request = _make_request(tmp_path, draft=draft)

    # Shape not found → read_shape_text returns None for K1 (shape_path="21")
    missing_shape_map = {
        "21": None,   # shape missing — must NOT be treated as successful CLEAR
        "22": "Channel 1, Channel 2, Channel 3.",
    }

    with pytest.raises(VisualQAError, match="missing shape is never a successful CLEAR"):
        _run_with_mocked_resolver(service, request, tmp_path / "art",
                                  text_map=missing_shape_map)

    renderer.render.assert_not_called()
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# LiveGeometryError propagation (Item 5/6/7)
# ---------------------------------------------------------------------------


def test_live_geometry_error_converts_to_visual_qa_error(tmp_path):
    """Service converts LiveGeometryError from read_live_slot_geometries to VisualQAError."""
    reviewer = _mock_reviewer()
    renderer = MagicMock()
    service = _make_service(reviewer=reviewer, renderer=renderer)

    def _fake_read_shape_text(pptx_path, slide_number, shape_path):
        return _DEFAULT_TEXT_MAP.get(shape_path)

    with patch("slidestein.qa.service.resolve_slide_by_stable_id", return_value=(2, 256)), \
         patch("slidestein.qa.service.read_live_slot_geometries",
               side_effect=LiveGeometryError("Shape '21' not found in slide 2")), \
         patch("slidestein.qa.service.read_shape_text", side_effect=_fake_read_shape_text), \
         patch("slidestein.qa.service.normalize_readback", side_effect=lambda x: x):
        with pytest.raises(VisualQAError, match="Cannot read live geometry"):
            service.review(_make_request(tmp_path), tmp_path / "art")

    renderer.render.assert_not_called()
    reviewer.review.assert_not_called()


# ---------------------------------------------------------------------------
# Live geometry in slot specs (hardening item: generated_geometry in specs)
# ---------------------------------------------------------------------------


def test_generated_geometry_in_slot_specs(tmp_path):
    """Slot specs passed to Vision reviewer include generated_geometry from live PPTX."""
    reviewer = _mock_reviewer()
    service = _make_service(reviewer=reviewer)

    live_geos = {
        "K1": {"x_ratio": 0.11, "y_ratio": 0.22, "width_ratio": 0.55, "height_ratio": 0.08},
        "K2": {"x_ratio": 0.04, "y_ratio": 0.35, "width_ratio": 0.70, "height_ratio": 0.40},
    }

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art",
                               live_geos=live_geos)

    call_kwargs = reviewer.review.call_args
    slot_specs = call_kwargs[1]["slot_specs"] if call_kwargs[1] else call_kwargs[0][3]

    geo_by_key = {spec["key"]: spec.get("generated_geometry") for spec in slot_specs}
    assert geo_by_key["K1"] is not None, "K1 must have generated_geometry"
    assert geo_by_key["K1"]["x_ratio"] == pytest.approx(0.11)
    assert geo_by_key["K2"]["y_ratio"] == pytest.approx(0.35)


def test_overlay_builder_receives_live_geometry_dict(tmp_path):
    """overlay_builder.build is called with dict[str, dict] (not TemplateSlot objects)."""
    overlay_builder = MagicMock()
    service = _make_service(overlay_builder=overlay_builder)

    live_geos = {
        "K1": {"x_ratio": 0.5, "y_ratio": 0.5, "width_ratio": 0.2, "height_ratio": 0.1},
        "K2": {"x_ratio": 0.1, "y_ratio": 0.1, "width_ratio": 0.3, "height_ratio": 0.2},
    }

    _run_with_mocked_resolver(service, _make_request(tmp_path), tmp_path / "art",
                               live_geos=live_geos)

    overlay_builder.build.assert_called_once()
    _src, _out, geometries = overlay_builder.build.call_args.args
    # All values must be plain dicts, not TemplateSlot objects
    for key, geo in geometries.items():
        assert isinstance(geo, dict), f"Geometry for {key} must be a dict, got {type(geo)}"
        assert "x_ratio" in geo

