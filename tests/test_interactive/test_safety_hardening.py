"""M11.1 Safety hardening tests.

Req 3:  Original file byte-identical after forced verification failure
Req 4:  Shape identity mismatch rejection
Req 5:  Non-editable target rejection
Req 12: Deleted shape presence protected (deleted shape = ._presence in protected_fields)
Req 15: Human-added shape preserved through SlideStein patch
Req 20: Atomic write failure — no orphan temp files, original unchanged
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch as mpatch

import pytest
from lxml import etree
from pptx import Presentation

from slidestein.interactive.adapters.python_pptx import (
    PythonPptxPowerPointHostAdapter,
    _set_text_preserving_format,
)
from slidestein.interactive.diff import SlideStateDiffService
from slidestein.interactive.models import SlidePatchOperation, SlidePatchPlan
from slidestein.interactive.patch import SlidePatchService
from slidestein.interactive.session import SlideSessionService
from tests.test_interactive.conftest import (
    _SHAPES,
    make_pingpong_pptx,
    simulate_human_add_shape,
    simulate_human_delete_shape,
    simulate_human_text_edit,
)

_ADAPTER = PythonPptxPowerPointHostAdapter()
_SESSION_SVC = SlideSessionService()
_PATCH_SVC = SlidePatchService()
_DIFF_SVC = SlideStateDiffService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


class _UndeclaredChangeAdapter(PythonPptxPowerPointHostAdapter):
    """Injects an unauthorized mutation during _apply_mutations to force verification failure."""

    def _apply_mutations(self, slide, path_map, operations):
        super()._apply_mutations(slide, path_map, operations)
        target_paths = {op.shape_path for op in operations}
        for path, shape in path_map.items():
            if path not in target_paths and hasattr(shape, "text_frame"):
                shape.text_frame.text = "__UNAUTHORIZED_INJECTION__"
                return


# ---------------------------------------------------------------------------
# Req 3: Original file integrity — forced verification failure
# ---------------------------------------------------------------------------

def test_verification_failure_original_unchanged(tmp_path):
    """When verification fails (undeclared change injected), original PPTX must be unchanged."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    original_bytes = pptx_path.read_bytes()

    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    adapter = _UndeclaredChangeAdapter()

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                value="Authorized bullet",
            )
        ],
    )

    result = adapter.apply_patch(pptx_path, patch)

    assert result.status == "rejected"
    assert result.rejection_reason == "verification_failed"
    assert result.verification_passed is False
    assert len(result.unexpected_changed_fields) > 0

    # Original PPTX must be byte-for-byte identical
    assert pptx_path.read_bytes() == original_bytes, \
        "Original PPTX was modified despite verification failure"

    # No orphan temp files
    assert list(tmp_path.glob("._m11tmp_*")) == [], "Temp file not cleaned up after failure"


def test_verification_failure_leaves_no_temp_files(tmp_path):
    """After verification failure, no ._m11tmp_ files should remain."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    adapter = _UndeclaredChangeAdapter()

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                value="x",
            )
        ],
    )
    adapter.apply_patch(pptx_path, patch)
    assert list(tmp_path.glob("._m11tmp_*")) == []


# ---------------------------------------------------------------------------
# Req 4: Shape identity mismatch
# ---------------------------------------------------------------------------

def test_shape_identity_mismatch_rejected(tmp_path):
    """Patch with correct shape_path but wrong shape_id must be rejected."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)

    bullet1_path = paths["bullet_1"]
    real_id = _SHAPES["bullet_1"][0]  # correct ID

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=real_id + 9000,  # wrong ID for this path
                shape_path=bullet1_path,
                field="text",
                value="Should not apply",
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)

    assert result.status == "rejected"
    assert result.rejection_reason == "shape_identity_mismatch"

    # Original unchanged — hash must be the same
    state_after = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    assert state_after.state_hash == state.state_hash


# ---------------------------------------------------------------------------
# Req 5: Non-editable target
# ---------------------------------------------------------------------------

def test_non_editable_target_rejected(tmp_path):
    """Patch targeting a group shape (editable_text=False) must be rejected."""
    pptx_path, _ = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)

    group_shape = next(s for s in state.shapes if s.shape_path == "20")
    assert not group_shape.editable_text, "Expected group to be non-editable"

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=group_shape.shape_id,
                shape_path="20",
                field="text",
                value="illegal",
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)

    assert result.status == "rejected"
    assert result.rejection_reason == "target_not_editable"

    # Original unchanged
    state_after = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    assert state_after.state_hash == state.state_hash


# ---------------------------------------------------------------------------
# Req 12: Deleted shape presence protected
# ---------------------------------------------------------------------------

def test_deleted_shape_presence_protected(tmp_path):
    """After human deletes a shape, ._presence must be in protected_fields."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)

    unrelated_id = _SHAPES["unrelated"][0]
    unrelated_path = paths["unrelated"]

    simulate_human_delete_shape(pptx_path, unrelated_id)

    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, diff = _SESSION_SVC.advance_after_human_edit(session, v2)

    assert len(diff.deleted_shapes) >= 1
    deleted_paths = {s.shape_path for s in diff.deleted_shapes}
    assert unrelated_path in deleted_paths

    assert f"{unrelated_path}._presence" in session.protected_fields


# ---------------------------------------------------------------------------
# Req 15: Human-added shape preserved through SlideStein patch
# ---------------------------------------------------------------------------

def test_human_added_shape_preserved_through_patch(tmp_path):
    """Req 15: A shape added by the human must still be present in V3 after a SlideStein patch."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)

    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)
    v1_paths = {s.shape_path for s in v1.shapes}

    # Human adds a new shape (ID 50, not in original fixture)
    simulate_human_add_shape(
        pptx_path,
        shape_id=50,
        x=1000000, y=5000000, w=2000000, h=500000,
        text="Human added shape",
    )

    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, diff = _SESSION_SVC.advance_after_human_edit(session, v2)

    assert len(diff.added_shapes) >= 1
    added_paths = {s.shape_path for s in diff.added_shapes}
    assert "50" in added_paths

    # Added shape fully protected
    assert "50._presence" in session.protected_fields
    assert "50.x" in session.protected_fields

    # SlideStein patches bullet_1
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                value="Patched bullet1",
            )
        ],
    )
    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "applied", f"Patch rejected: {result.rejection_reason}"

    # Added shape must still be present in V3
    v3_paths = {s.shape_path for s in result.after_state.shapes}
    assert "50" in v3_paths, "Human-added shape was removed by SlideStein patch"

    v3_map = {s.shape_path: s for s in result.after_state.shapes}
    assert v3_map["50"].text == "Human added shape", "Human-added shape text changed"
    assert v3_map[paths["bullet_1"]].text == "Patched bullet1"


# ---------------------------------------------------------------------------
# Req 20: Atomic write failure — original unchanged, no temp files
# ---------------------------------------------------------------------------

def test_atomic_replace_failure_original_unchanged(tmp_path):
    """When os.replace fails, original PPTX must be unchanged and no temp files left."""
    pptx_path = _make_minimal_pptx(tmp_path, text="Original")
    original_bytes = pptx_path.read_bytes()

    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=5,
                shape_path="5",
                field="text",
                value="New text",
            )
        ],
    )

    import slidestein.interactive.adapters.python_pptx as _mod

    def _fail_replace(src, dst):
        raise OSError("Simulated os.replace failure")

    with mpatch.object(_mod.os, "replace", _fail_replace):
        with pytest.raises(OSError, match="Simulated"):
            _ADAPTER.apply_patch(pptx_path, patch)

    # Original byte-for-byte unchanged
    assert pptx_path.read_bytes() == original_bytes, "Original was modified after os.replace failure"

    # No orphan temp files
    assert list(tmp_path.glob("._m11tmp_*")) == [], "Temp file remains after os.replace failure"


def test_atomic_replace_failure_no_orphan_temp(tmp_path):
    """After os.replace failure, temp file must be deleted."""
    pptx_path = _make_minimal_pptx(tmp_path, text="Check cleanup")
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=5, shape_path="5",
                field="text", value="x"
            )
        ],
    )

    import slidestein.interactive.adapters.python_pptx as _mod

    def _fail_replace(src, dst):
        raise OSError("injected failure")

    with mpatch.object(_mod.os, "replace", _fail_replace):
        with pytest.raises(OSError):
            _ADAPTER.apply_patch(pptx_path, patch)

    assert list(tmp_path.glob("._m11tmp_*")) == []


# ---------------------------------------------------------------------------
# Comprehensive deleted-shape preservation test (M11 Final Closure Spec §5)
# ---------------------------------------------------------------------------

def test_deleted_shape_absent_after_patch_elsewhere(tmp_path):
    """Full V1→delete-unrelated→V2→patch-bullet_1→V3 real-PPTX sequence.

    Asserts:
      - Deleted shape remains absent in V3
      - bullet_1 text changed as requested
      - No other unexpected changes in V2→V3 diff
    """
    pptx_path, paths = make_pingpong_pptx(tmp_path)

    # V1
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)
    unrelated_id = _SHAPES["unrelated"][0]
    unrelated_path = paths["unrelated"]
    assert unrelated_path in {s.shape_path for s in v1.shapes}

    # Human deletes unrelated shape
    simulate_human_delete_shape(pptx_path, unrelated_id)

    # V2
    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, diff12 = _SESSION_SVC.advance_after_human_edit(session, v2)

    assert unrelated_path not in {s.shape_path for s in v2.shapes}, "Shape not actually deleted"
    deleted_paths = {s.shape_path for s in diff12.deleted_shapes}
    assert unrelated_path in deleted_paths
    assert f"{unrelated_path}._presence" in session.protected_fields

    # SlideStein patches bullet_1 with base = V2
    bullet_path = paths["bullet_1"]
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=bullet_path,
                field="text",
                value="After delete patch",
            )
        ],
    )
    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "applied", f"Patch rejected: {result.rejection_reason}"

    v3 = result.after_state
    v3_paths = {s.shape_path for s in v3.shapes}

    # Deleted shape stays absent
    assert unrelated_path not in v3_paths, "Deleted shape reappeared after SlideStein patch"

    # bullet_1 changed correctly
    v3_map = {s.shape_path: s for s in v3.shapes}
    assert v3_map[bullet_path].text == "After delete patch"

    # V2→V3 diff: only bullet_1 changed
    from slidestein.interactive.diff import SlideStateDiffService
    diff23 = SlideStateDiffService().diff(v2, v3)
    changed_v3 = {d.shape_path for d in diff23.shape_deltas}
    assert bullet_path in changed_v3
    assert unrelated_path not in changed_v3   # deleted shape not in either state
    assert len(diff23.added_shapes) == 0
    assert len(diff23.deleted_shapes) == 0


def test_patch_on_deleted_shape_missing_target(tmp_path):
    """Patch targeting a shape that was deleted by the human → missing_target_shape."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)

    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)
    unrelated_id = _SHAPES["unrelated"][0]
    unrelated_path = paths["unrelated"]

    simulate_human_delete_shape(pptx_path, unrelated_id)

    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, _ = _SESSION_SVC.advance_after_human_edit(session, v2)

    # Patch directly targets the deleted shape
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=unrelated_id,
                shape_path=unrelated_path,
                field="text",
                value="Impossible",
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "missing_target_shape"
