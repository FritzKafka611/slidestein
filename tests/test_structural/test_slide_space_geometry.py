"""Unit tests for _slide_space_geometry and _get_group_xfrm.

All shapes are simulated with mock objects — no PPTX file I/O.
Tests verify:
  1. Top-level shape: geometry = shape.left/.top/.width/.height unchanged
  2. Group → child: parent position + child local = correct slide-space x/y
  3. chOff offsets the child-coordinate origin
  4. Scaling (chExt != group extent) scales child coordinates
  5. Two-level nesting: group → group → leaf
  6. Moving the parent group changes child slide-space geometry
  7. Missing ancestor returns None (not empty dict)

Regression requirement (hardening R8):
  Slide-space geometry must compose ALL ancestor group transforms.
  Reading shape.left/.top directly from a child inside a group returns
  group-LOCAL coordinates, not slide-space coordinates.  The test
  specifically verifies the group-transform composition is applied.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

from slidestein.structural.diagnosis import _get_group_xfrm, _slide_space_geometry


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _make_group_element(
    ch_off_x: int,
    ch_off_y: int,
    ch_ext_cx: int,
    ch_ext_cy: int,
) -> ET.Element:
    """Build a minimal OOXML group element with xfrm/chOff/chExt."""
    root = ET.Element(f"{{{_NS}}}grpSp")
    xfrm = ET.SubElement(root, f"{{{_NS}}}xfrm")
    chOff = ET.SubElement(xfrm, f"{{{_NS}}}chOff")
    chOff.set("x", str(ch_off_x))
    chOff.set("y", str(ch_off_y))
    chExt = ET.SubElement(xfrm, f"{{{_NS}}}chExt")
    chExt.set("cx", str(ch_ext_cx))
    chExt.set("cy", str(ch_ext_cy))
    return root


def _mock_shape(
    shape_id: int,
    left: int,
    top: int,
    width: int,
    height: int,
    is_group: bool = False,
    ch_off_x: int = 0,
    ch_off_y: int = 0,
    ch_ext_cx: int | None = None,
    ch_ext_cy: int | None = None,
):
    """Build a mock pptx-like shape (no real PPTX required).

    ch_ext_cx/ch_ext_cy default to width/height when None.
    Pass 0 explicitly to test degenerate/zero-extent groups.
    """
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    shape = MagicMock()
    shape.shape_id = shape_id
    shape.left = left
    shape.top = top
    shape.width = width
    shape.height = height
    shape.shape_type = MSO_SHAPE_TYPE.GROUP if is_group else MSO_SHAPE_TYPE.TEXT_BOX

    if is_group:
        # Use None-sentinel default to distinguish "not set" from "explicitly 0"
        actual_cx = ch_ext_cx if ch_ext_cx is not None else width
        actual_cy = ch_ext_cy if ch_ext_cy is not None else height
        shape._element = _make_group_element(ch_off_x, ch_off_y, actual_cx, actual_cy)

    return shape


def _build_path_map(*shapes) -> dict:
    """Build a path_map from a flat list of shapes (top-level IDs as string paths)."""
    return {str(s.shape_id): s for s in shapes}


def _nested_path_map(group_shape, child_shape) -> dict:
    """Build a path_map for a single group containing a single child."""
    gid = str(group_shape.shape_id)
    cid = str(child_shape.shape_id)
    return {
        gid: group_shape,
        f"{gid}/{cid}": child_shape,
    }


def _two_level_path_map(outer_group, inner_group, leaf) -> dict:
    """Build a path_map for outer_group → inner_group → leaf."""
    g1 = str(outer_group.shape_id)
    g2 = str(inner_group.shape_id)
    lf = str(leaf.shape_id)
    return {
        g1: outer_group,
        f"{g1}/{g2}": inner_group,
        f"{g1}/{g2}/{lf}": leaf,
    }


# ---------------------------------------------------------------------------
# _get_group_xfrm
# ---------------------------------------------------------------------------


def test_get_group_xfrm_reads_choff_chext():
    group = _mock_shape(10, 0, 0, 5000, 3000, is_group=True,
                        ch_off_x=100, ch_off_y=50, ch_ext_cx=5000, ch_ext_cy=3000)
    chOff_x, chOff_y, chExt_cx, chExt_cy = _get_group_xfrm(group)
    assert chOff_x == 100
    assert chOff_y == 50
    assert chExt_cx == 5000
    assert chExt_cy == 3000


def test_get_group_xfrm_falls_back_on_missing_element():
    """If _element has no xfrm, fall back to (0, 0, width, height)."""
    group = MagicMock()
    group.width = 6000
    group.height = 4000
    group._element = ET.Element("noxfrm")
    result = _get_group_xfrm(group)
    assert result == (0, 0, 6000, 4000)


def test_get_group_xfrm_falls_back_on_exception():
    """Attribute error on _element → fall back to (0, 0, width, height)."""
    group = MagicMock()
    group.width = 3000
    group.height = 2000
    del group._element  # no _element → AttributeError
    result = _get_group_xfrm(group)
    assert result == (0, 0, 3000, 2000)


# ---------------------------------------------------------------------------
# _slide_space_geometry — top-level shape
# ---------------------------------------------------------------------------


def test_top_level_shape_returns_direct_geometry():
    leaf = _mock_shape(21, left=1000, top=500, width=8000, height=2000)
    pm = _build_path_map(leaf)
    geo = _slide_space_geometry(pm, "21")
    assert geo == {"x": 1000, "y": 500, "width": 8000, "height": 2000}


def test_missing_top_level_shape_returns_none():
    pm = {}
    assert _slide_space_geometry(pm, "99") is None


# ---------------------------------------------------------------------------
# _slide_space_geometry — one-level group
# ---------------------------------------------------------------------------


def test_group_child_adds_group_position():
    """Child at (0, 0) local, group at (500, 300) → slide-space = (500, 300).

    When chOff=(0,0) and chExt=group extent, child local = slide-space offset by group pos.
    """
    GROUP_LEFT, GROUP_TOP = 500, 300
    GROUP_W, GROUP_H = 5000, 3000
    CHILD_LEFT, CHILD_TOP = 200, 100

    group = _mock_shape(10, GROUP_LEFT, GROUP_TOP, GROUP_W, GROUP_H,
                        is_group=True, ch_off_x=0, ch_off_y=0,
                        ch_ext_cx=GROUP_W, ch_ext_cy=GROUP_H)
    child = _mock_shape(20, CHILD_LEFT, CHILD_TOP, 1000, 500)
    pm = _nested_path_map(group, child)

    geo = _slide_space_geometry(pm, "10/20")

    expected_x = GROUP_LEFT + CHILD_LEFT  # 500 + 200 = 700
    expected_y = GROUP_TOP + CHILD_TOP    # 300 + 100 = 400
    assert geo is not None
    assert geo["x"] == expected_x
    assert geo["y"] == expected_y
    assert geo["width"] == 1000
    assert geo["height"] == 500


def test_group_child_with_choff_shifts_origin():
    """chOff=(100, 50) means child (100,50) local maps to group's top-left corner.

    Formula: slide_x = group_left + (child_local_x - chOff_x) * (group_w / chExt_cx)
    With scale=1.0: slide_x = group_left + child_local_x - chOff_x
    """
    GROUP_LEFT, GROUP_TOP = 1000, 600
    GROUP_W, GROUP_H = 4000, 2000
    CH_OFF_X, CH_OFF_Y = 200, 100
    CHILD_LEFT, CHILD_TOP = 500, 300  # in child coordinate space

    group = _mock_shape(11, GROUP_LEFT, GROUP_TOP, GROUP_W, GROUP_H,
                        is_group=True, ch_off_x=CH_OFF_X, ch_off_y=CH_OFF_Y,
                        ch_ext_cx=GROUP_W, ch_ext_cy=GROUP_H)
    child = _mock_shape(21, CHILD_LEFT, CHILD_TOP, 800, 400)
    pm = _nested_path_map(group, child)

    geo = _slide_space_geometry(pm, "11/21")

    # scale=1.0 → slide_x = group_left + (child_left - chOff_x)
    expected_x = GROUP_LEFT + (CHILD_LEFT - CH_OFF_X)  # 1000 + 300 = 1300
    expected_y = GROUP_TOP + (CHILD_TOP - CH_OFF_Y)    # 600 + 200 = 800
    assert geo is not None
    assert geo["x"] == expected_x
    assert geo["y"] == expected_y


def test_group_scaling_stretches_child_position():
    """When group extent differs from chExt, positions and sizes scale.

    Group displayed at 2× the child coordinate space:
      group_w = 4000, chExt_cx = 2000 → scale = 2.0
      child at local (200, 100) → slide-space x = group_left + 2 * 200 = group_left + 400
    """
    GROUP_LEFT, GROUP_TOP = 500, 300
    GROUP_W, GROUP_H = 4000, 2000
    CH_EXT_CX, CH_EXT_CY = 2000, 1000  # half the group extent → scale = 2.0
    CHILD_LEFT, CHILD_TOP = 200, 100
    CHILD_W, CHILD_H = 300, 150

    group = _mock_shape(12, GROUP_LEFT, GROUP_TOP, GROUP_W, GROUP_H,
                        is_group=True, ch_off_x=0, ch_off_y=0,
                        ch_ext_cx=CH_EXT_CX, ch_ext_cy=CH_EXT_CY)
    child = _mock_shape(22, CHILD_LEFT, CHILD_TOP, CHILD_W, CHILD_H)
    pm = _nested_path_map(group, child)

    geo = _slide_space_geometry(pm, "12/22")

    scale_x = GROUP_W / CH_EXT_CX  # 2.0
    scale_y = GROUP_H / CH_EXT_CY  # 2.0
    expected_x = int(round(GROUP_LEFT + scale_x * CHILD_LEFT))  # 500 + 400 = 900
    expected_y = int(round(GROUP_TOP + scale_y * CHILD_TOP))    # 300 + 200 = 500
    expected_w = int(round(scale_x * CHILD_W))                  # 600
    expected_h = int(round(scale_y * CHILD_H))                  # 300
    assert geo is not None
    assert geo["x"] == expected_x
    assert geo["y"] == expected_y
    assert geo["width"] == expected_w
    assert geo["height"] == expected_h


def test_missing_child_in_group_returns_none():
    group = _mock_shape(10, 500, 300, 5000, 3000, is_group=True,
                        ch_ext_cx=5000, ch_ext_cy=3000)
    pm = {"10": group}  # child "10/99" not in map
    assert _slide_space_geometry(pm, "10/99") is None


# ---------------------------------------------------------------------------
# _slide_space_geometry — two-level nesting (regression: R8)
# ---------------------------------------------------------------------------


def test_two_level_group_composes_transforms():
    """Outer group → inner group → leaf.  Both transforms must be composed.

    Setup (all scale=1, no chOff):
      outer group at (1000, 500), w=6000, h=4000
      inner group at (300, 200) [local to outer], w=3000, h=2000
      leaf at (100, 80) [local to inner], w=800, h=400

    Expected slide-space:
      x = 1000 + 300 + 100 = 1400
      y =  500 + 200 +  80 =  780
    """
    OUTER_L, OUTER_T, OUTER_W, OUTER_H = 1000, 500, 6000, 4000
    INNER_L, INNER_T, INNER_W, INNER_H = 300, 200, 3000, 2000
    LEAF_L, LEAF_T, LEAF_W, LEAF_H = 100, 80, 800, 400

    outer = _mock_shape(100, OUTER_L, OUTER_T, OUTER_W, OUTER_H,
                        is_group=True, ch_off_x=0, ch_off_y=0,
                        ch_ext_cx=OUTER_W, ch_ext_cy=OUTER_H)
    inner = _mock_shape(200, INNER_L, INNER_T, INNER_W, INNER_H,
                        is_group=True, ch_off_x=0, ch_off_y=0,
                        ch_ext_cx=INNER_W, ch_ext_cy=INNER_H)
    leaf = _mock_shape(300, LEAF_L, LEAF_T, LEAF_W, LEAF_H)
    pm = _two_level_path_map(outer, inner, leaf)

    geo = _slide_space_geometry(pm, "100/200/300")

    assert geo is not None
    assert geo["x"] == OUTER_L + INNER_L + LEAF_L  # 1400
    assert geo["y"] == OUTER_T + INNER_T + LEAF_T  # 780
    assert geo["width"] == LEAF_W
    assert geo["height"] == LEAF_H


def test_moving_parent_group_changes_child_slide_space_geometry():
    """Regression (R8): moving a parent group must update child slide-space geometry.

    This is the case that was BROKEN before the fix: old code read shape.left
    directly (group-local coordinates); now we compose transforms.
    """
    GROUP_W, GROUP_H = 5000, 3000
    CHILD_LEFT, CHILD_TOP = 200, 100

    # Position A: group at (500, 300)
    group_a = _mock_shape(10, 500, 300, GROUP_W, GROUP_H,
                          is_group=True, ch_off_x=0, ch_off_y=0,
                          ch_ext_cx=GROUP_W, ch_ext_cy=GROUP_H)
    child_a = _mock_shape(20, CHILD_LEFT, CHILD_TOP, 1000, 500)
    pm_a = _nested_path_map(group_a, child_a)

    # Position B: group at (900, 700) — moved
    group_b = _mock_shape(10, 900, 700, GROUP_W, GROUP_H,
                          is_group=True, ch_off_x=0, ch_off_y=0,
                          ch_ext_cx=GROUP_W, ch_ext_cy=GROUP_H)
    child_b = _mock_shape(20, CHILD_LEFT, CHILD_TOP, 1000, 500)
    pm_b = _nested_path_map(group_b, child_b)

    geo_a = _slide_space_geometry(pm_a, "10/20")
    geo_b = _slide_space_geometry(pm_b, "10/20")

    assert geo_a is not None and geo_b is not None

    # Child local coords are IDENTICAL, but slide-space differs because parent moved
    assert geo_a["x"] != geo_b["x"], (
        "Parent group move must change child slide-space x. "
        "If this fails, group-transform composition is broken."
    )
    assert geo_a["y"] != geo_b["y"]

    # Exact expected values
    assert geo_a["x"] == 700   # 500 + 200
    assert geo_a["y"] == 400   # 300 + 100
    assert geo_b["x"] == 1100  # 900 + 200
    assert geo_b["y"] == 800   # 700 + 100


def test_zero_chext_returns_none():
    """Degenerate group (chExt=0) must return None, not raise ZeroDivisionError."""
    group = _mock_shape(10, 500, 300, 5000, 3000, is_group=True,
                        ch_off_x=0, ch_off_y=0,
                        ch_ext_cx=0,  # degenerate
                        ch_ext_cy=3000)
    child = _mock_shape(20, 100, 50, 500, 250)
    pm = _nested_path_map(group, child)
    result = _slide_space_geometry(pm, "10/20")
    assert result is None


# ---------------------------------------------------------------------------
# Diagnosis routing with nested-group geometry (integration-level mock)
# ---------------------------------------------------------------------------


def test_diagnosis_detects_parent_group_move_as_drift():
    """Moving a parent group → slide-space drift → diagnosis=rebuild_current_template.

    This is the end-to-end regression: if diagnosis still reads raw group-local
    coords, this test will fail because template_geo == generated_geo (both see
    the same child local coords) and route=reselect_template instead of rebuild.
    """
    from pathlib import Path
    from unittest.mock import patch

    from slidestein.structural.diagnosis import (
        StructuralDiagnosisService,
        _slide_space_geometry,
    )
    from slidestein.structural.models import StructuralRecoveryRoute
    from tests.test_structural.conftest import make_recovery_request

    svc = StructuralDiagnosisService()
    request = make_recovery_request()

    # Template: parent group at (500, 300), child at (200, 100) local
    # → slide-space (700, 400)
    template_geos = {
        "K1": {"x": 700, "y": 400, "width": 1000, "height": 500},
        "K2": {"x": 700, "y": 1200, "width": 5000, "height": 2000},
    }

    # Generated: parent group moved to (900, 700), child still at (200, 100) local
    # → slide-space (1100, 800) — DIFFERENT from template
    generated_geos = {
        "K1": {"x": 1100, "y": 800, "width": 1000, "height": 500},
        "K2": {"x": 700, "y": 1200, "width": 5000, "height": 2000},
    }

    with (
        patch("slidestein.structural.diagnosis.resolve_slide_by_stable_id") as mock_resolve,
        patch("slidestein.structural.diagnosis._read_slide_space_geometries") as mock_read,
        patch.object(svc, "_verify_content_identity"),
    ):
        mock_resolve.return_value = (2, "native-001")
        mock_read.side_effect = [template_geos, generated_geos]

        plan = svc.diagnose(request)

    # Because slide-space geometry differs, route must be rebuild_current_template
    assert plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE, (
        "Expected rebuild_current_template because parent group moved. "
        "If route=reselect_template, geometry is being read as group-local."
    )
    assert any(d.key == "K1" for d in plan.structural_drifts)
    assert plan.structural_drifts[0].drift_type == "position_changed"
