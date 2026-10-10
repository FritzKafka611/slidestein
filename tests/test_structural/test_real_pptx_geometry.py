"""Real PPTX nested-group regression tests (Req 2 + Req 10).

Creates actual PPTX fixtures using python-pptx and verifies slide-space
geometry via the REAL _build_path_map and _slide_space_geometry functions.
No mocking of either function.

Group-transform convention used in all fixtures:
  chOff = (0, 0)   — child coordinates are group-relative starting from 0
  chExt = (group_width, group_height)  — scale = 1.0

Under this convention the slide-space formula simplifies to:
  slide_x = group.left + child.left

This is the convention that makes parent-group movement correctly propagate
to child slide-space coordinates.  When chOff == group.left (an alternative
OOXML convention), slide_x == child.left regardless of where the group is —
which would make parent-move invisible to the fingerprint (the M10.2 bug
discovered during hardening).

Tests:
1. BASELINE: child slide-space = group.left + child.left (chOff=0)
2. MUTATION:  moving ONLY the parent group changes child slide-space
3. TWO-LEVEL: outer -> inner -> leaf, slide-space composes additively
4. FINGERPRINT: slide-space fingerprint changes when parent group moves

Save-and-reopen is used to ensure OOXML round-trip correctness.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from slidestein.structural.diagnosis import _build_path_map, _slide_space_geometry
from slidestein.structural.fingerprint import compute_structural_fingerprint_slide_space
from tests.test_structural.conftest import make_slot
from slidestein.drafting.service import build_slot_key_mapping
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _create_pptx_with_group(
    tmp_path: Path,
    group_left: int,
    group_top: int,
    group_width: int,
    group_height: int,
    child_left_local: int,
    child_top_local: int,
    child_width: int,
    child_height: int,
    filename: str = "fixture.pptx",
) -> Path:
    """Save a PPTX with one group shape (chOff=0) containing one text shape.

    chOff=(0,0), chExt=(group_width, group_height): scale=1.0, child
    coordinates are group-relative from (0,0).  Under this convention:
        slide_x = group.left + child.left
    Moving the group changes the child's slide-space position.
    """
    from lxml import etree

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank

    grpSp_xml = (
        f'<p:grpSp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:nvGrpSpPr>"
        f'<p:cNvPr id="100" name="Group100"/>'
        f"<p:cNvGrpSpPr/><p:nvPr/>"
        f"</p:nvGrpSpPr>"
        f"<p:grpSpPr><a:xfrm>"
        f'<a:off x="{group_left}" y="{group_top}"/>'
        f'<a:ext cx="{group_width}" cy="{group_height}"/>'
        f'<a:chOff x="0" y="0"/>'
        f'<a:chExt cx="{group_width}" cy="{group_height}"/>'
        f"</a:xfrm></p:grpSpPr>"
        f"<p:sp>"
        f"<p:nvSpPr>"
        f'<p:cNvPr id="101" name="Child101"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/>'
        f"</p:nvSpPr>"
        f"<p:spPr><a:xfrm>"
        f'<a:off x="{child_left_local}" y="{child_top_local}"/>'
        f'<a:ext cx="{child_width}" cy="{child_height}"/>'
        f"</a:xfrm>"
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f"</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>Slot</a:t></a:r></a:p>"
        f"</p:txBody></p:sp></p:grpSp>"
    )
    slide.shapes._spTree.append(etree.fromstring(grpSp_xml))
    pptx_path = tmp_path / filename
    prs.save(str(pptx_path))
    return pptx_path


def _create_pptx_two_level(
    tmp_path: Path,
    outer_left: int,
    outer_top: int,
    outer_w: int,
    outer_h: int,
    inner_left: int,
    inner_top: int,
    inner_w: int,
    inner_h: int,
    leaf_left: int,
    leaf_top: int,
    leaf_w: int,
    leaf_h: int,
    filename: str = "fixture_2level.pptx",
) -> Path:
    """Save a PPTX with outer group -> inner group -> text shape.  chOff=0 at each level."""
    from lxml import etree

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])

    xml = (
        f'<p:grpSp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:nvGrpSpPr>"
        f'<p:cNvPr id="200" name="Outer"/><p:cNvGrpSpPr/><p:nvPr/>'
        f"</p:nvGrpSpPr>"
        f"<p:grpSpPr><a:xfrm>"
        f'<a:off x="{outer_left}" y="{outer_top}"/>'
        f'<a:ext cx="{outer_w}" cy="{outer_h}"/>'
        f'<a:chOff x="0" y="0"/>'
        f'<a:chExt cx="{outer_w}" cy="{outer_h}"/>'
        f"</a:xfrm></p:grpSpPr>"
        f"<p:grpSp>"
        f"<p:nvGrpSpPr>"
        f'<p:cNvPr id="201" name="Inner"/><p:cNvGrpSpPr/><p:nvPr/>'
        f"</p:nvGrpSpPr>"
        f"<p:grpSpPr><a:xfrm>"
        f'<a:off x="{inner_left}" y="{inner_top}"/>'
        f'<a:ext cx="{inner_w}" cy="{inner_h}"/>'
        f'<a:chOff x="0" y="0"/>'
        f'<a:chExt cx="{inner_w}" cy="{inner_h}"/>'
        f"</a:xfrm></p:grpSpPr>"
        f"<p:sp>"
        f"<p:nvSpPr>"
        f'<p:cNvPr id="202" name="Leaf"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/>'
        f"</p:nvSpPr>"
        f"<p:spPr><a:xfrm>"
        f'<a:off x="{leaf_left}" y="{leaf_top}"/>'
        f'<a:ext cx="{leaf_w}" cy="{leaf_h}"/>'
        f"</a:xfrm>"
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f"</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>Leaf</a:t></a:r></a:p>"
        f"</p:txBody></p:sp>"
        f"</p:grpSp>"
        f"</p:grpSp>"
    )
    slide.shapes._spTree.append(etree.fromstring(xml))
    pptx_path = tmp_path / filename
    prs.save(str(pptx_path))
    return pptx_path


# ---------------------------------------------------------------------------
# Test 1: BASELINE
# ---------------------------------------------------------------------------


def test_real_pptx_group_child_slide_space_baseline(tmp_path):
    """Child inside group: slide-space x = group.left + child.left (chOff=0).

    The PPTX is saved and reopened so the test exercises real OOXML round-trip.
    _build_path_map and _slide_space_geometry are called without any mocking.
    """
    GROUP_LEFT = 1_000_000
    GROUP_TOP  =   500_000
    GROUP_W    = 5_000_000
    GROUP_H    = 3_000_000
    CHILD_LEFT =   200_000   # group-relative (chOff=0)
    CHILD_TOP  =   100_000
    CHILD_W    = 1_500_000
    CHILD_H    =   400_000

    pptx_path = _create_pptx_with_group(
        tmp_path,
        group_left=GROUP_LEFT, group_top=GROUP_TOP,
        group_width=GROUP_W, group_height=GROUP_H,
        child_left_local=CHILD_LEFT, child_top_local=CHILD_TOP,
        child_width=CHILD_W, child_height=CHILD_H,
    )

    prs = Presentation(str(pptx_path))
    path_map = _build_path_map(prs.slides[0].shapes)
    geo = _slide_space_geometry(path_map, "100/101")

    assert geo is not None, "_slide_space_geometry returned None for real PPTX"
    # chOff=0, scale=1: slide_x = group.left + child.left
    assert geo["x"] == GROUP_LEFT + CHILD_LEFT, (
        f"Expected slide-space x={GROUP_LEFT + CHILD_LEFT}, got {geo['x']}"
    )
    assert geo["y"] == GROUP_TOP + CHILD_TOP
    assert geo["width"] == CHILD_W
    assert geo["height"] == CHILD_H


# ---------------------------------------------------------------------------
# Test 2: MUTATION
# ---------------------------------------------------------------------------


def test_real_pptx_parent_group_move_changes_child_slide_space(tmp_path):
    """Moving only the parent group changes child slide-space geometry.

    PPTX A: group at (500000, 300000)
    PPTX B: group at (900000, 700000)   <- moved +400000 each axis
    Child group-local coords identical in both.

    Both PPTXs are saved and reopened before calling the real functions.
    """
    CHILD_LEFT = 600_000   # group-relative
    CHILD_TOP  = 400_000
    GROUP_W    = 5_000_000
    GROUP_H    = 3_000_000
    CHILD_W    = 1_500_000
    CHILD_H    =   600_000

    pptx_a = _create_pptx_with_group(
        tmp_path,
        group_left=500_000, group_top=300_000,
        group_width=GROUP_W, group_height=GROUP_H,
        child_left_local=CHILD_LEFT, child_top_local=CHILD_TOP,
        child_width=CHILD_W, child_height=CHILD_H,
        filename="fixture_a.pptx",
    )
    pptx_b = _create_pptx_with_group(
        tmp_path,
        group_left=900_000, group_top=700_000,
        group_width=GROUP_W, group_height=GROUP_H,
        child_left_local=CHILD_LEFT, child_top_local=CHILD_TOP,
        child_width=CHILD_W, child_height=CHILD_H,
        filename="fixture_b.pptx",
    )

    prs_a = Presentation(str(pptx_a))
    path_map_a = _build_path_map(prs_a.slides[0].shapes)
    geo_a = _slide_space_geometry(path_map_a, "100/101")

    prs_b = Presentation(str(pptx_b))
    path_map_b = _build_path_map(prs_b.slides[0].shapes)
    geo_b = _slide_space_geometry(path_map_b, "100/101")

    assert geo_a is not None
    assert geo_b is not None

    # Confirm child group-local coords are identical (python-pptx reads raw XML off)
    child_a = path_map_a.get("100/101")
    child_b = path_map_b.get("100/101")
    assert child_a is not None and child_b is not None
    assert int(child_a.left) == CHILD_LEFT, "child group-local left must be unchanged"
    assert int(child_b.left) == CHILD_LEFT, "child group-local left must be unchanged"

    # Slide-space x MUST differ: (500000+600000) vs (900000+600000)
    assert geo_a["x"] == 500_000 + CHILD_LEFT
    assert geo_b["x"] == 900_000 + CHILD_LEFT
    assert geo_a["x"] != geo_b["x"], (
        "Parent group move must change child slide-space x when chOff=0"
    )
    assert geo_a["y"] != geo_b["y"]


# ---------------------------------------------------------------------------
# Test 3: TWO-LEVEL
# ---------------------------------------------------------------------------


def test_real_pptx_two_level_group_composes_correctly(tmp_path):
    """Outer -> inner -> leaf: slide-space = outer.left + inner.left + leaf.left.

    Both groups use chOff=0.  All functions called without mocking.
    PPTX is saved and reopened.
    """
    OUTER_L = 1_000_000
    OUTER_T =   500_000
    OUTER_W = 7_000_000
    OUTER_H = 4_000_000
    INNER_L =   500_000   # group-relative within outer (chOff=0)
    INNER_T =   300_000
    INNER_W = 3_000_000
    INNER_H = 2_000_000
    LEAF_L  =   200_000   # group-relative within inner (chOff=0)
    LEAF_T  =   100_000
    LEAF_W  = 1_000_000
    LEAF_H  =   400_000

    pptx_path = _create_pptx_two_level(
        tmp_path,
        outer_left=OUTER_L, outer_top=OUTER_T, outer_w=OUTER_W, outer_h=OUTER_H,
        inner_left=INNER_L, inner_top=INNER_T, inner_w=INNER_W, inner_h=INNER_H,
        leaf_left=LEAF_L, leaf_top=LEAF_T, leaf_w=LEAF_W, leaf_h=LEAF_H,
    )

    prs = Presentation(str(pptx_path))
    path_map = _build_path_map(prs.slides[0].shapes)
    geo = _slide_space_geometry(path_map, "200/201/202")

    assert geo is not None, "_slide_space_geometry returned None for two-level group"
    # slide_x = outer.left + inner.left + leaf.left  (each level chOff=0, scale=1)
    assert geo["x"] == OUTER_L + INNER_L + LEAF_L, (
        f"Expected {OUTER_L + INNER_L + LEAF_L}, got {geo['x']}"
    )
    assert geo["y"] == OUTER_T + INNER_T + LEAF_T


# ---------------------------------------------------------------------------
# Test 4: FINGERPRINT (Req 10 test B)
# ---------------------------------------------------------------------------


def test_real_pptx_fingerprint_changes_on_parent_group_move(tmp_path):
    """compute_structural_fingerprint_slide_space differs when parent group moves.

    Req 10 test B: same group-local child coordinates, different parent
    group position -> DIFFERENT fingerprint.

    Both PPTXs use chOff=0 so parent position propagates to slide-space.
    """
    GROUP_W    = 5_000_000
    GROUP_H    = 3_000_000
    CHILD_LEFT = 600_000
    CHILD_TOP  = 400_000
    CHILD_W    = 1_500_000
    CHILD_H    =   600_000

    pptx_a = _create_pptx_with_group(
        tmp_path,
        group_left=500_000, group_top=300_000,
        group_width=GROUP_W, group_height=GROUP_H,
        child_left_local=CHILD_LEFT, child_top_local=CHILD_TOP,
        child_width=CHILD_W, child_height=CHILD_H,
        filename="fp_a.pptx",
    )
    pptx_b = _create_pptx_with_group(
        tmp_path,
        group_left=900_000, group_top=700_000,
        group_width=GROUP_W, group_height=GROUP_H,
        child_left_local=CHILD_LEFT, child_top_local=CHILD_TOP,
        child_width=CHILD_W, child_height=CHILD_H,
        filename="fp_b.pptx",
    )

    # Slot references shape path "100/101" (group_id=100, child_id=101)
    slot = make_slot(
        slot_id="slot-001",
        shape_id=101,
        shape_path="100/101",
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        x_emu=CHILD_LEFT,
        y_emu=CHILD_TOP,
        w_emu=CHILD_W,
        h_emu=CHILD_H,
    )
    slot_key_map = build_slot_key_mapping([slot])

    fp_a = compute_structural_fingerprint_slide_space(pptx_a, 1, slot_key_map)
    fp_b = compute_structural_fingerprint_slide_space(pptx_b, 1, slot_key_map)

    assert isinstance(fp_a, str) and len(fp_a) == 64, "fingerprint must be SHA-256 hex"
    assert isinstance(fp_b, str) and len(fp_b) == 64
    assert fp_a != fp_b, (
        "Slide-space fingerprint must differ when parent group moves. "
        "Parent at (500000,300000) gives different slide-space than (900000,700000)."
    )


# ---------------------------------------------------------------------------
# Test 5: FINGERPRINT invariant (Req 10 test A)
# ---------------------------------------------------------------------------


def test_real_pptx_fingerprint_identical_for_same_layout_different_ids(tmp_path):
    """compute_structural_fingerprint_slide_space is invariant to shape IDs and text.

    Req 10 test A: two PPTXs with identical role/editable/slide-space geometry
    but different shape IDs -> SAME fingerprint.

    We create two single-slot PPTXs at the exact same slide-space position using
    top-level shapes (no group), verify fingerprints match, then confirm that
    using a different slide position produces a different fingerprint.
    """
    from lxml import etree

    def _make_toplevel_pptx(tmp_path, shape_id, left, top, width, height, fname):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        xml = (
            f'<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f"<p:nvSpPr>"
            f'<p:cNvPr id="{shape_id}" name="Shape{shape_id}"/>'
            f'<p:cNvSpPr txBox="1"/><p:nvPr/>'
            f"</p:nvSpPr>"
            f"<p:spPr><a:xfrm>"
            f'<a:off x="{left}" y="{top}"/>'
            f'<a:ext cx="{width}" cy="{height}"/>'
            f"</a:xfrm>"
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f"</p:spPr>"
            f"<p:txBody><a:bodyPr/><a:lstStyle/>"
            f"<a:p><a:r><a:t>Different text content #{shape_id}</a:t></a:r></a:p>"
            f"</p:txBody></p:sp>"
        )
        slide.shapes._spTree.append(etree.fromstring(xml))
        path = tmp_path / fname
        prs.save(str(path))
        return path

    LEFT  = 1_000_000
    TOP   =   500_000
    W     = 5_000_000
    H     =   600_000

    # Two PPTXs with different shape IDs and different text but identical geometry
    pptx_x = _make_toplevel_pptx(tmp_path, shape_id=50, left=LEFT, top=TOP, width=W, height=H, fname="inv_x.pptx")
    pptx_y = _make_toplevel_pptx(tmp_path, shape_id=99, left=LEFT, top=TOP, width=W, height=H, fname="inv_y.pptx")
    # Third with different position — fingerprint must differ
    pptx_z = _make_toplevel_pptx(tmp_path, shape_id=50, left=LEFT + 100_000, top=TOP, width=W, height=H, fname="inv_z.pptx")

    def _make_slot_key_map(shape_id):
        slot = make_slot(
            slot_id=f"slot-{shape_id}",
            shape_id=shape_id,
            shape_path=str(shape_id),
            slot_role=SlotRole.TITLE,
            semantic_label="Title",
            x_emu=LEFT,
            y_emu=TOP,
            w_emu=W,
            h_emu=H,
        )
        return build_slot_key_mapping([slot])

    fp_x = compute_structural_fingerprint_slide_space(pptx_x, 1, _make_slot_key_map(50))
    fp_y = compute_structural_fingerprint_slide_space(pptx_y, 1, _make_slot_key_map(99))
    fp_z = compute_structural_fingerprint_slide_space(pptx_z, 1, _make_slot_key_map(50))

    assert fp_x == fp_y, (
        "Same slide-space geometry with different shape IDs/text must give SAME fingerprint"
    )
    assert fp_x != fp_z, (
        "Different slide-space position must give DIFFERENT fingerprint"
    )
