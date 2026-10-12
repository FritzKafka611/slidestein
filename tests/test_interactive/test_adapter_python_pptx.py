"""Tests for PythonPptxPowerPointHostAdapter using real PPTX files."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from slidestein.interactive.adapters.python_pptx import PythonPptxPowerPointHostAdapter
from slidestein.interactive.models import SlidePatchOperation, SlidePatchPlan
from tests.test_interactive.conftest import make_pingpong_pptx


_ADAPTER = PythonPptxPowerPointHostAdapter()


def _make_minimal_pptx(tmp_path: Path, text: str = "Hello") -> Path:
    """Single top-level text shape (ID 5) on a blank slide."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    xml = (
        f'<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:nvSpPr>"
        f'<p:cNvPr id="5" name="Box5"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/>'
        f"</p:nvSpPr>"
        f"<p:spPr><a:xfrm>"
        f'<a:off x="1000000" y="500000"/>'
        f'<a:ext cx="5000000" cy="1000000"/>'
        f"</a:xfrm>"
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f"</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
        f"</p:txBody></p:sp>"
    )
    slide.shapes._spTree.append(etree.fromstring(xml))
    path = tmp_path / "minimal.pptx"
    prs.save(str(path))
    return path


def test_capture_returns_slide_state(tmp_path):
    path = _make_minimal_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    assert state.slide_number == 1
    assert len(state.shapes) >= 1


def test_capture_state_hash_is_64_hex(tmp_path):
    path = _make_minimal_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    assert len(state.state_hash) == 64
    assert all(c in "0123456789abcdef" for c in state.state_hash)


def test_capture_includes_group_and_child(tmp_path):
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    captured_paths = {s.shape_path for s in state.shapes}
    assert "20" in captured_paths       # group itself
    assert "20/21" in captured_paths    # group child


def test_capture_slide_space_geometry_nested(tmp_path):
    """Group child slide-space x == group.left + child.local.left (chOff=0)."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    shape_map = {s.shape_path: s for s in state.shapes}
    group = shape_map.get("20")
    child = shape_map.get("20/21")
    assert group is not None
    assert child is not None
    # Child local coords are 0,0 in the fixture; slide_x = group.x + 0 = group.x
    assert child.x == group.x


def test_apply_patch_stale_hash_rejected(tmp_path):
    path = _make_minimal_pptx(tmp_path)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash="0" * 64,   # deliberate mismatch
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=5, shape_path="5", field="text", value="new"
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "stale_base_state"


def test_apply_patch_missing_shape_rejected(tmp_path):
    path = _make_minimal_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=999, shape_path="999", field="text", value="x"
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "missing_target_shape"


def test_apply_patch_precondition_failed(tmp_path):
    path = _make_minimal_pptx(tmp_path, text="Original")
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=5, shape_path="5", field="text",
                expected_before="WRONG EXPECTED",
                value="new",
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "precondition_failed"


def test_apply_patch_replace_text_succeeds(tmp_path):
    path = _make_minimal_pptx(tmp_path, text="Original")
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=5, shape_path="5", field="text", value="Updated"
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.status == "applied"
    assert result.after_state is not None
    shape_map = {s.shape_path: s for s in result.after_state.shapes}
    assert shape_map["5"].text == "Updated"


def test_apply_patch_clear_text(tmp_path):
    path = _make_minimal_pptx(tmp_path, text="Original")
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="clear_text", shape_id=5, shape_path="5", field="text"
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.status == "applied"
    shape_map = {s.shape_path: s for s in result.after_state.shapes}
    assert shape_map["5"].text == ""


def test_apply_patch_verification_passed(tmp_path):
    path = _make_minimal_pptx(tmp_path, text="Original")
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=5, shape_path="5", field="text", value="New"
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.verification_passed


def test_apply_patch_does_not_change_non_target_shape(tmp_path):
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    title_path = paths["title"]
    bullet1_path = paths["bullet_1"]

    title_before = next(s for s in state.shapes if s.shape_path == title_path)

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=int(bullet1_path),
                shape_path=bullet1_path,
                field="text",
                value="Only bullet 1 changed",
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)
    assert result.status == "applied"

    shape_map = {s.shape_path: s for s in result.after_state.shapes}
    assert shape_map[title_path].text == title_before.text


def test_atomic_write_temp_file_cleaned_up(tmp_path):
    path = _make_minimal_pptx(tmp_path, text="Original")
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=5, shape_path="5", field="text", value="X"
            )
        ],
    )
    _ADAPTER.apply_patch(path, patch)

    # No ._m11tmp_ files should remain after successful apply
    leftover = list(tmp_path.glob("._m11tmp_*"))
    assert leftover == []


def test_apply_patch_wrong_shape_id_rejected(tmp_path):
    """Patch with correct shape_path but wrong shape_id must be rejected (Req 4)."""
    path = _make_minimal_pptx(tmp_path, text="Hello")
    state = _ADAPTER.capture_slide_state(path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=9999,  # shape_path "5" has ID 5, not 9999
                shape_path="5",
                field="text",
                value="Should not apply",
            )
        ],
    )
    result = _ADAPTER.apply_patch(path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "shape_identity_mismatch"
    # Original unchanged
    state_after = _ADAPTER.capture_slide_state(path, slide_number=1)
    assert state_after.state_hash == state.state_hash
