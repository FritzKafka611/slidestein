"""Stable slide ID resolution tests for M8 Visual QA."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from slidestein.qa.errors import VisualQAError
from slidestein.qa.models import VisualQARequest
from slidestein.qa.service import VisualQAService
from slidestein.writeback.errors import PowerPointWritebackError
from tests.test_qa.conftest import (
    make_complete_draft,
    make_native_check,
    make_slot_map,
    make_visual_model_output,
)

# ---------------------------------------------------------------------------
# IO mock constants (match conftest defaults)
# ---------------------------------------------------------------------------

_LIVE_GEOS = {
    "K1": {"x_ratio": 0.04, "y_ratio": 0.07, "width_ratio": 0.88, "height_ratio": 0.09},
    "K2": {"x_ratio": 0.04, "y_ratio": 0.25, "width_ratio": 0.88, "height_ratio": 0.09},
}
_TEXT_MAP = {
    "21": "Digital transformation drives efficiency.",
    "22": "Channel 1, Channel 2, Channel 3.",
}


def _make_service():
    from unittest.mock import MagicMock

    reviewer = MagicMock()
    reviewer.review.return_value = make_visual_model_output()
    renderer = MagicMock()
    overlay_builder = MagicMock()
    native_inspector = MagicMock()
    native_inspector.inspect.return_value = [make_native_check()]
    return VisualQAService(
        reviewer=reviewer,
        renderer=renderer,
        overlay_builder=overlay_builder,
        native_inspector=native_inspector,
    )


def _make_request(tmp_path, slot_map=None, draft=None):
    return VisualQARequest(
        template_pptx=tmp_path / "template.pptx",
        generated_pptx=tmp_path / "generated.pptx",
        draft=draft or make_complete_draft(),
        slot_map=slot_map or make_slot_map(),
    )


def _io_patches():
    """Context manager that mocks all IO steps (5b, 5c) in service.review()."""
    return (
        patch("slidestein.qa.service.read_live_slot_geometries", return_value=_LIVE_GEOS),
        patch("slidestein.qa.service.read_shape_text",
              side_effect=lambda pptx, sn, path: _TEXT_MAP.get(path)),
        patch("slidestein.qa.service.normalize_readback", side_effect=lambda x: x),
    )


# ---------------------------------------------------------------------------
# Stable slide targeting
# ---------------------------------------------------------------------------


def test_resolver_called_for_both_decks(tmp_path):
    """Stable slide resolver is invoked separately for template and generated."""
    service = _make_service()
    request = _make_request(tmp_path)

    call_log = []

    def _fake_resolver(pptx_path, deck_id, slide_id):
        call_log.append(pptx_path)
        return (2, 256)

    p1, p2, p3 = _io_patches()
    with patch("slidestein.qa.service.resolve_slide_by_stable_id", side_effect=_fake_resolver), \
         p1, p2, p3:
        service.review(request, tmp_path / "artifacts")

    assert len(call_log) == 2
    pptx_names = {Path(p).name for p in call_log}
    assert "template.pptx" in pptx_names
    assert "generated.pptx" in pptx_names


def test_slide_moved_ordinal_resolved_correctly(tmp_path):
    """Slide moved from ordinal 2 to ordinal 4 is still resolved correctly."""
    service = _make_service()
    request = _make_request(tmp_path)

    def _fake_resolver(pptx_path, deck_id, slide_id):
        return (4, 256)

    p1, p2, p3 = _io_patches()
    with patch("slidestein.qa.service.resolve_slide_by_stable_id", side_effect=_fake_resolver), \
         p1, p2, p3:
        result = service.review(request, tmp_path / "artifacts")

    assert result.resolved_generated_slide_number == 4


def test_template_resolver_failure_raises_visual_qa_error(tmp_path):
    """If template resolution fails, VisualQAError is raised before rendering."""
    service = _make_service()
    request = _make_request(tmp_path)

    call_count = [0]

    def _fail_first(pptx_path, deck_id, slide_id):
        call_count[0] += 1
        if "template" in str(pptx_path):
            raise PowerPointWritebackError("Template slide not found")
        return (2, 256)

    with patch("slidestein.qa.service.resolve_slide_by_stable_id", side_effect=_fail_first):
        with pytest.raises(VisualQAError, match="template"):
            service.review(request, tmp_path / "artifacts")


def test_generated_resolver_failure_raises_visual_qa_error(tmp_path):
    """If generated PPTX resolution fails, VisualQAError is raised."""
    service = _make_service()
    request = _make_request(tmp_path)

    def _fail_generated(pptx_path, deck_id, slide_id):
        if Path(pptx_path).name == "generated.pptx":
            raise PowerPointWritebackError("Generated slide not found")
        return (2, 256)

    with patch("slidestein.qa.service.resolve_slide_by_stable_id", side_effect=_fail_generated):
        with pytest.raises(VisualQAError, match="generated"):
            service.review(request, tmp_path / "artifacts")


def test_missing_deck_id_raises_before_resolver(tmp_path):
    """slot_map.deck_id is required — missing deck_id raises before resolver."""
    service = _make_service()

    slot_map = make_slot_map(deck_id=None)
    draft = make_complete_draft()
    request = _make_request(tmp_path, slot_map=slot_map, draft=draft)

    with patch("slidestein.qa.service.resolve_slide_by_stable_id") as mock_resolver:
        with pytest.raises(VisualQAError, match="deck_id"):
            service.review(request, tmp_path / "artifacts")

    mock_resolver.assert_not_called()
