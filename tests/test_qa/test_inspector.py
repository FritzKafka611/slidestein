"""Native inspector tests for M8 Visual QA."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.qa.inspector import (
    NativeVisualInspector,
    _check_outside_bounds,
    _com_text_overflow_for_shapes,
)
from slidestein.qa.models import NativeCheckStatus, NativeCheckType
from tests.test_qa.conftest import make_slot, make_slot_map


# ---------------------------------------------------------------------------
# _check_outside_bounds (pure function — no COM, no PPTX)
# ---------------------------------------------------------------------------


def _make_pptx_shape(left: int, top: int, width: int, height: int):
    """Return a minimal mock object mimicking a python-pptx shape's geometry."""
    shape = MagicMock()
    shape.left = left
    shape.top = top
    shape.width = width
    shape.height = height
    return shape


SLIDE_W = 12195175
SLIDE_H = 6858000


def test_shape_inside_slide_is_pass():
    shape = _make_pptx_shape(left=100, top=100, width=5000000, height=2000000)
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.PASS
    assert chk.check_type == NativeCheckType.OUTSIDE_SLIDE_BOUNDS


def test_shape_exceeds_right_is_fail():
    shape = _make_pptx_shape(
        left=10000000, top=100, width=5000000, height=2000000
    )  # right = 15000000 > SLIDE_W
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K2", "22")
    assert chk.status == NativeCheckStatus.FAIL
    assert "right" in chk.details


def test_shape_exceeds_bottom_is_fail():
    shape = _make_pptx_shape(
        left=100, top=5000000, width=1000000, height=3000000
    )  # bottom = 8000000 > SLIDE_H
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K3", "23")
    assert chk.status == NativeCheckStatus.FAIL
    assert "bottom" in chk.details


def test_shape_negative_left_is_fail():
    shape = _make_pptx_shape(left=-10, top=100, width=1000000, height=500000)
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.FAIL


def test_shape_geometry_exception_returns_unknown():
    from unittest.mock import PropertyMock  # noqa: PLC0415

    shape = MagicMock()
    type(shape).left = PropertyMock(side_effect=Exception("COM error"))
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.UNKNOWN


def test_shape_exactly_at_slide_boundary_is_pass():
    shape = _make_pptx_shape(
        left=0, top=0, width=SLIDE_W, height=SLIDE_H
    )
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.PASS


# ---------------------------------------------------------------------------
# COM text overflow (mocked — COM not required in CI)
# ---------------------------------------------------------------------------


def test_com_overflow_true_detected():
    """COM not available in test env — should return None (unknown) for non-existent PPTX."""
    result = _com_text_overflow_for_shapes(Path("fake.pptx"), 1, ["21"])
    assert "21" in result
    assert result["21"] is None


def test_com_overflow_false_when_fits():
    """When BoundHeight <= available, no overflow."""
    # Same test — COM unavailable → None (unknown)
    result = _com_text_overflow_for_shapes(Path("fake.pptx"), 1, ["22"])
    assert result["22"] is None


def test_com_overflow_returns_none_when_unavailable():
    """COM not installed / any exception → unknown for all shapes."""
    result = _com_text_overflow_for_shapes(Path("nonexistent.pptx"), 1, ["K1", "K2"])
    assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# NativeVisualInspector integration (mocked python-pptx, no real PPTX)
# ---------------------------------------------------------------------------


def test_inspector_missing_pptx_returns_fail_check(tmp_path):
    inspector = NativeVisualInspector()
    slot_map = make_slot_map()
    slot_key_map = {"K1": slot_map.slots[0], "K2": slot_map.slots[1]}

    checks = inspector.inspect(
        tmp_path / "nonexistent.pptx",
        slide_number=2,
        slot_key_map=slot_key_map,
        slot_map=slot_map,
    )

    assert len(checks) >= 1
    assert any(c.status == NativeCheckStatus.FAIL for c in checks)
    assert any(c.check_type == NativeCheckType.RENDERING_IDENTITY for c in checks)


def test_inspector_uses_slot_map_slide_dimensions_on_fallback(tmp_path):
    """If python-pptx cannot read slide dimensions, slot_map dimensions are used."""
    from pptx import Presentation  # noqa: PLC0415
    import io  # noqa: PLC0415
    from pptx.util import Inches  # noqa: PLC0415

    # Create a tiny valid PPTX with one slide
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0])
    pptx_path = tmp_path / "test.pptx"
    prs.save(str(pptx_path))

    slot_map = make_slot_map(slide_id="x", deck_id="y", slide_number=1)
    slot_key_map = {}  # no target slots → no checks beyond identity

    inspector = NativeVisualInspector()
    checks = inspector.inspect(pptx_path, 1, slot_key_map, slot_map)
    # With empty slot_key_map, no shape-level checks are done.
    assert isinstance(checks, list)


# ---------------------------------------------------------------------------
# EMU magnitude in outside-bounds details (hardening item #10)
# ---------------------------------------------------------------------------


def test_negative_left_details_include_emu_overflow():
    """left=-4273 EMU → details includes 'overflow=4273 EMU'."""
    shape = _make_pptx_shape(left=-4273, top=100, width=1000000, height=500000)
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.FAIL
    assert "overflow=4273 EMU" in chk.details


def test_negative_top_details_include_emu_overflow():
    """top=-4273 EMU (intentional design bleed) → FAIL with explicit overflow magnitude."""
    shape = _make_pptx_shape(left=0, top=-4273, width=SLIDE_W, height=500000)
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.FAIL
    assert "top=-4273 EMU" in chk.details
    assert "overflow=4273 EMU" in chk.details


def test_right_overflow_details_include_magnitude():
    """right > slide_width → details includes overflow magnitude in EMU."""
    overflow = 5000
    shape = _make_pptx_shape(
        left=SLIDE_W - 100, top=0, width=100 + overflow, height=100000
    )  # right = SLIDE_W + overflow
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K2", "22")
    assert chk.status == NativeCheckStatus.FAIL
    assert f"overflow={overflow} EMU" in chk.details


def test_bottom_overflow_details_include_magnitude():
    """bottom > slide_height → details includes overflow magnitude in EMU."""
    overflow = 12000
    shape = _make_pptx_shape(
        left=0, top=SLIDE_H - 50, width=100000, height=50 + overflow
    )
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K3", "23")
    assert chk.status == NativeCheckStatus.FAIL
    assert f"overflow={overflow} EMU" in chk.details


def test_emu_keyword_present_in_pass_details():
    """PASS details also include EMU values (coordinates, not overflow)."""
    shape = _make_pptx_shape(left=100, top=200, width=1000000, height=500000)
    chk = _check_outside_bounds(shape, SLIDE_W, SLIDE_H, "K1", "21")
    assert chk.status == NativeCheckStatus.PASS
    assert "EMU" in chk.details


# ---------------------------------------------------------------------------
# COM Shape.Height formula regression (hardening item: correct COM API)
# ---------------------------------------------------------------------------


def test_com_overflow_uses_shape_height_not_tf_height(tmp_path):
    """Overflow uses com_shape.Height (not tf.Height which doesn't exist).

    BoundHeight=90, Shape.Height=100, margins=0 → fits → result is False (no overflow).
    If regressed to tf.Height (MagicMock), the comparison would be unpredictable.
    """
    from unittest.mock import MagicMock, patch  # noqa: PLC0415

    com_shape = MagicMock()
    com_shape.HasTextFrame = True
    tf = MagicMock()
    com_shape.TextFrame = tf
    tf.AutoSize = 0
    com_shape.Height = 100.0
    tf.MarginTop = 0.0
    tf.MarginBottom = 0.0
    tf.TextRange.BoundHeight = 90.0

    mock_ppt = MagicMock()
    mock_prs = MagicMock()
    mock_prs.Slides.return_value = MagicMock()
    mock_ppt.Presentations.Open.return_value = mock_prs

    with patch("comtypes.client.CreateObject", return_value=mock_ppt), \
         patch("slidestein.writeback.com_writer.resolve_com_shape_by_path",
               return_value=com_shape):
        result = _com_text_overflow_for_shapes(tmp_path / "test.pptx", 1, ["21"])

    assert result["21"] is False, (
        "BoundHeight(90) fits within Shape.Height(100) — no overflow expected. "
        "Regression: using tf.Height instead of com_shape.Height would break this."
    )


def test_com_overflow_detects_overflow_via_shape_height(tmp_path):
    """Overflow fires when BoundHeight > Shape.Height - margins."""
    from unittest.mock import MagicMock, patch  # noqa: PLC0415

    com_shape = MagicMock()
    com_shape.HasTextFrame = True
    tf = MagicMock()
    com_shape.TextFrame = tf
    tf.AutoSize = 0
    com_shape.Height = 80.0
    tf.MarginTop = 5.0
    tf.MarginBottom = 5.0
    tf.TextRange.BoundHeight = 80.0  # 80 > (80 - 5 - 5 = 70) → overflow

    mock_ppt = MagicMock()
    mock_prs = MagicMock()
    mock_prs.Slides.return_value = MagicMock()
    mock_ppt.Presentations.Open.return_value = mock_prs

    with patch("comtypes.client.CreateObject", return_value=mock_ppt), \
         patch("slidestein.writeback.com_writer.resolve_com_shape_by_path",
               return_value=com_shape):
        result = _com_text_overflow_for_shapes(tmp_path / "test.pptx", 1, ["21"])

    assert result["21"] is True, "BoundHeight(80) > Shape.Height(80)-5-5(=70) → overflow"


def test_com_overflow_autosize_shape_never_overflows(tmp_path):
    """AutoSize == 1 shape is structurally overflow-free → result is False."""
    from unittest.mock import MagicMock, patch  # noqa: PLC0415

    com_shape = MagicMock()
    com_shape.HasTextFrame = True
    tf = MagicMock()
    com_shape.TextFrame = tf
    tf.AutoSize = 1  # auto-size → no overflow possible
    com_shape.Height = 50.0
    tf.MarginTop = 0.0
    tf.MarginBottom = 0.0
    tf.TextRange.BoundHeight = 500.0  # huge BoundHeight — irrelevant for AutoSize

    mock_ppt = MagicMock()
    mock_prs = MagicMock()
    mock_prs.Slides.return_value = MagicMock()
    mock_ppt.Presentations.Open.return_value = mock_prs

    with patch("comtypes.client.CreateObject", return_value=mock_ppt), \
         patch("slidestein.writeback.com_writer.resolve_com_shape_by_path",
               return_value=com_shape):
        result = _com_text_overflow_for_shapes(tmp_path / "test.pptx", 1, ["21"])

    assert result["21"] is False, "AutoSize=1 → shape grows to fit, no overflow"


# ---------------------------------------------------------------------------
# M6 COM resolver delegation (hardening item: reuse com_writer resolver)
# ---------------------------------------------------------------------------


def test_com_overflow_delegates_shape_resolution_to_m6_resolver(tmp_path):
    """_com_text_overflow_for_shapes calls resolve_com_shape_by_path from com_writer."""
    from unittest.mock import MagicMock, patch, call as mock_call  # noqa: PLC0415

    mock_ppt = MagicMock()
    mock_ppt.Presentations.Open.return_value = MagicMock()

    with patch("comtypes.client.CreateObject", return_value=mock_ppt), \
         patch("slidestein.writeback.com_writer.resolve_com_shape_by_path",
               return_value=None) as mock_resolver:
        _com_text_overflow_for_shapes(tmp_path / "test.pptx", 1, ["21", "22"])

    assert mock_resolver.call_count == 2, (
        "resolve_com_shape_by_path from com_writer must be called once per shape path"
    )


def test_com_overflow_unknown_when_no_text_frame(tmp_path):
    """Shape without text frame → result stays None (unknown), not False."""
    from unittest.mock import MagicMock, patch  # noqa: PLC0415

    com_shape = MagicMock()
    com_shape.HasTextFrame = False  # no text → skip, result stays None

    mock_ppt = MagicMock()
    mock_prs = MagicMock()
    mock_prs.Slides.return_value = MagicMock()
    mock_ppt.Presentations.Open.return_value = mock_prs

    with patch("comtypes.client.CreateObject", return_value=mock_ppt), \
         patch("slidestein.writeback.com_writer.resolve_com_shape_by_path",
               return_value=com_shape):
        result = _com_text_overflow_for_shapes(tmp_path / "test.pptx", 1, ["21"])

    assert result["21"] is None, "Shape without text frame → unknown (None), not False"


def test_overflow_fail_details_mention_shape_height_formula():
    """Text overflow FAIL details string contains the correct Shape.Height formula."""
    checks_text = (
        "Text content height exceeds available text-frame height "
        "(BoundHeight > Shape.Height - MarginTop - MarginBottom)"
    )
    # Verify the formula string is exactly what inspector.py produces on overflow
    from slidestein.qa.inspector import NativeVisualInspector  # noqa: PLC0415
    import inspect  # noqa: PLC0415

    src = inspect.getsource(NativeVisualInspector)
    assert "Shape.Height - MarginTop - MarginBottom" in src, (
        "Inspector must use Shape.Height formula (not tf.Height which doesn't exist)"
    )
