"""Overlay builder tests for M8 Visual QA."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidestein.qa.errors import LiveGeometryError
from slidestein.qa.overlay import create_slot_overlay, read_live_slot_geometries
from tests.test_qa.conftest import make_slot, make_slot_map


def _make_test_image(path: Path, width: int = 400, height: int = 300) -> Path:
    """Create a minimal test PNG at the given path."""
    from PIL import Image  # noqa: PLC0415

    img = Image.new("RGB", (width, height), color=(200, 200, 200))
    img.save(str(path), format="PNG")
    return path


def _make_geo(
    x_ratio: float = 0.04,
    y_ratio: float = 0.07,
    width_ratio: float = 0.88,
    height_ratio: float = 0.09,
) -> dict:
    """Create a geometry dict as returned by read_live_slot_geometries."""
    return {
        "x_ratio": x_ratio,
        "y_ratio": y_ratio,
        "width_ratio": width_ratio,
        "height_ratio": height_ratio,
    }


# ---------------------------------------------------------------------------
# Basic overlay tests (slot_geometries as dict[str, dict])
# ---------------------------------------------------------------------------


def test_overlay_output_dimensions_unchanged(tmp_path):
    """Overlay preserves source image dimensions."""
    from PIL import Image  # noqa: PLC0415

    src = _make_test_image(tmp_path / "src.png", width=800, height=600)
    out = tmp_path / "overlay.png"
    key_map = {"K1": _make_geo(y_ratio=0.07), "K2": _make_geo(y_ratio=0.25)}

    create_slot_overlay(src, out, key_map)

    assert out.exists()
    img = Image.open(str(out))
    assert img.size == (800, 600)


def test_overlay_correct_key_count(tmp_path):
    """One label per slot key — no extra or missing labels."""
    from PIL import Image  # noqa: PLC0415

    src = _make_test_image(tmp_path / "src.png")
    out = tmp_path / "overlay.png"

    key_map = {
        f"K{i}": _make_geo(x_ratio=0.05, y_ratio=0.1 * i)
        for i in range(1, 6)
    }

    create_slot_overlay(src, out, key_map)
    assert out.exists()
    img = Image.open(str(out))
    assert img.size == src_size(src)


def src_size(path):
    from PIL import Image  # noqa: PLC0415
    return Image.open(str(path)).size


def test_overlay_empty_slot_map_produces_copy(tmp_path):
    """Empty slot map: output is still a valid PNG at same dimensions."""
    from PIL import Image  # noqa: PLC0415

    src = _make_test_image(tmp_path / "src.png", width=640, height=480)
    out = tmp_path / "overlay.png"

    create_slot_overlay(src, out, {})

    assert out.exists()
    img = Image.open(str(out))
    assert img.size == (640, 480)


def test_overlay_creates_parent_directories(tmp_path):
    """Overlay creates the output parent directory if needed."""
    src = _make_test_image(tmp_path / "src.png")
    out = tmp_path / "subdir" / "deep" / "overlay.png"

    create_slot_overlay(src, out, {})

    assert out.exists()


def test_overlay_slot_geometry_maps_to_pixels(tmp_path):
    """Slot at (x_ratio=0, y_ratio=0) gets a box near the top-left corner."""
    from PIL import Image  # noqa: PLC0415

    src = _make_test_image(tmp_path / "src.png", width=1000, height=600)
    out = tmp_path / "overlay.png"

    create_slot_overlay(src, out, {"K1": _make_geo(x_ratio=0.0, y_ratio=0.0, width_ratio=0.2, height_ratio=0.1)})

    assert out.exists()
    img = Image.open(str(out))
    assert img.size == (1000, 600)


def test_overlay_clear_slot_receives_box(tmp_path):
    """Clear slots also get locator boxes (they appear in slot_key_map)."""
    src = _make_test_image(tmp_path / "src.png")
    out = tmp_path / "overlay.png"

    create_slot_overlay(src, out, {"K1": _make_geo()})

    assert out.exists()


def test_overlay_does_not_modify_source(tmp_path):
    """Source image bytes are unchanged after overlay creation."""
    src = _make_test_image(tmp_path / "src.png")
    original_bytes = src.read_bytes()

    out = tmp_path / "overlay.png"
    create_slot_overlay(src, out, {"K1": _make_geo()})

    assert src.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# read_live_slot_geometries — strict live-geometry contract (no fallbacks)
# ---------------------------------------------------------------------------


def test_read_live_slot_geometries_live_values_from_real_pptx(tmp_path):
    """With a real PPTX, read_live_slot_geometries returns actual shape positions."""
    from pptx import Presentation  # noqa: PLC0415
    from pptx.util import Emu  # noqa: PLC0415

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout

    left = Emu(500000)
    top = Emu(800000)
    width = Emu(3000000)
    height = Emu(1000000)
    txBox = slide.shapes.add_textbox(left, top, width, height)
    shape_id = txBox.shape_id

    pptx_path = tmp_path / "test.pptx"
    prs.save(str(pptx_path))

    slide_w = int(prs.slide_width)
    slide_h = int(prs.slide_height)

    slot = make_slot(slot_id="slot-001", shape_id=shape_id, shape_path=str(shape_id))
    slot_key_map = {"K1": slot}

    live_geos = read_live_slot_geometries(pptx_path, 1, slot_key_map)

    assert "K1" in live_geos
    assert live_geos["K1"]["x_ratio"] == pytest.approx(500000 / slide_w, abs=1e-4)
    assert live_geos["K1"]["y_ratio"] == pytest.approx(800000 / slide_h, abs=1e-4)
    assert live_geos["K1"]["width_ratio"] == pytest.approx(3000000 / slide_w, abs=1e-4)
    assert live_geos["K1"]["height_ratio"] == pytest.approx(1000000 / slide_h, abs=1e-4)


def test_read_live_slot_geometries_moved_shape_differs_from_template(tmp_path):
    """K3 moved from template position: live geometry reflects new position, not template."""
    from pptx import Presentation  # noqa: PLC0415
    from pptx.util import Emu  # noqa: PLC0415

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # Shape placed at a position very different from the template slot geometry
    live_left = Emu(8000000)   # far right — different from template x_ratio=0.04
    live_top = Emu(3000000)
    live_width = Emu(1500000)
    live_height = Emu(500000)
    txBox = slide.shapes.add_textbox(live_left, live_top, live_width, live_height)
    shape_id = txBox.shape_id

    pptx_path = tmp_path / "moved_k3.pptx"
    prs.save(str(pptx_path))

    slide_w = int(prs.slide_width)

    # Template slot says x_ratio=0.04 (far left) — but live PPTX has it far right
    slot = make_slot(slot_id="slot-003", shape_id=shape_id, shape_path=str(shape_id),
                     x_ratio=0.04, y_ratio=0.07)
    slot_key_map = {"K3": slot}

    live_geos = read_live_slot_geometries(pptx_path, 1, slot_key_map)

    # Live geometry should match actual PPTX position, not template geometry
    assert live_geos["K3"]["x_ratio"] == pytest.approx(8000000 / slide_w, abs=1e-4)
    assert live_geos["K3"]["x_ratio"] > 0.5, "Should be far right (> 50% of slide width)"


def test_read_live_slot_geometries_unreadable_pptx_raises(tmp_path):
    """Non-existent PPTX raises LiveGeometryError (no silent fallback)."""
    slot = make_slot(slot_id="slot-001", shape_id=21, shape_path="21")
    slot_key_map = {"K1": slot}

    with pytest.raises(LiveGeometryError, match="Cannot open"):
        read_live_slot_geometries(tmp_path / "nonexistent.pptx", 1, slot_key_map)


def test_read_live_slot_geometries_invalid_slide_number_raises(tmp_path):
    """Slide number out of range raises LiveGeometryError."""
    from pptx import Presentation  # noqa: PLC0415

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    pptx_path = tmp_path / "test.pptx"
    prs.save(str(pptx_path))

    slot = make_slot(slot_id="slot-001", shape_id=21, shape_path="21")
    slot_key_map = {"K1": slot}

    with pytest.raises(LiveGeometryError, match="out of range"):
        read_live_slot_geometries(pptx_path, 99, slot_key_map)

    with pytest.raises(LiveGeometryError, match="out of range"):
        read_live_slot_geometries(pptx_path, 0, slot_key_map)


def test_read_live_slot_geometries_missing_shape_raises(tmp_path):
    """Shape not in PPTX raises LiveGeometryError (no fallback to TemplateSlot.geometry)."""
    from pptx import Presentation  # noqa: PLC0415

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    pptx_path = tmp_path / "test.pptx"
    prs.save(str(pptx_path))

    # shape_path "9999" does not exist in the blank slide
    slot = make_slot(slot_id="slot-001", shape_id=9999, shape_path="9999",
                     x_ratio=0.1, y_ratio=0.2, width_ratio=0.5, height_ratio=0.3)
    slot_key_map = {"K1": slot}

    with pytest.raises(LiveGeometryError, match="not found"):
        read_live_slot_geometries(pptx_path, 1, slot_key_map)


def test_read_live_slot_geometries_geometry_property_unreadable_raises(tmp_path):
    """Shape with unreadable geometry property raises LiveGeometryError."""
    from pptx import Presentation  # noqa: PLC0415
    from pptx.util import Emu  # noqa: PLC0415
    from unittest.mock import patch, PropertyMock  # noqa: PLC0415

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    txBox = slide.shapes.add_textbox(Emu(100), Emu(100), Emu(1000000), Emu(500000))
    shape_id = txBox.shape_id
    pptx_path = tmp_path / "test.pptx"
    prs.save(str(pptx_path))

    slot = make_slot(slot_id="slot-001", shape_id=shape_id, shape_path=str(shape_id))
    slot_key_map = {"K1": slot}

    # Patch the shape's .left property to raise — simulates unreadable geometry
    with patch("slidestein.qa.overlay._build_path_map") as mock_build:
        bad_shape = type("BadShape", (), {
            "left": property(lambda self: (_ for _ in ()).throw(ValueError("COM error"))),
        })()
        mock_build.return_value = {str(shape_id): bad_shape}
        with pytest.raises(LiveGeometryError, match="Cannot read geometry"):
            read_live_slot_geometries(pptx_path, 1, slot_key_map)


def test_read_live_slot_geometries_no_template_geometry_fallback(tmp_path):
    """Proves TemplateSlot.geometry is never used: missing PPTX always raises."""
    slot = make_slot(slot_id="slot-001", shape_id=21, shape_path="21",
                     x_ratio=0.1, y_ratio=0.2, width_ratio=0.5, height_ratio=0.3)
    slot_key_map = {"K1": slot}

    # Even though TemplateSlot has geometry (x_ratio=0.1 etc.), we must NOT get
    # those values back — we must get LiveGeometryError
    with pytest.raises(LiveGeometryError):
        read_live_slot_geometries(tmp_path / "nonexistent.pptx", 1, slot_key_map)
