"""Shared fixtures and helpers for test_interactive suite.

PPTX fixture shape layout (IDs chosen to avoid collision with blank-layout placeholders):

  Shape 10  title          top strip,  full width
  Shape 11  left_content   left column, main area
  Shape 12  bullet_1       right column, row 1
  Shape 13  bullet_2       right column, row 2
  Shape 14  bullet_3       right column, row 3
  Shape 15  unrelated      bottom area
  Group 20  (group container, bottom-right)
    Shape 21  grouped_child  (child of group 20, local coords 0,0)

All text shapes contain exactly one paragraph with one run so that
_set_text_preserving_format can replace text without destroying formatting.

Group uses chOff=(0,0) convention: slide_x = group.left + child.left.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree
from pptx import Presentation

_NS = (
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
)

# Absolute EMU positions (fit on a 9144000 × 6858000 default slide)
_SHAPES = {
    # (shape_id, name, x, y, w, h, initial_text)
    "title":        (10, "Title10",       457200,  228600, 8229600,  685800, "Initial title"),
    "left_content": (11, "LeftContent11", 457200, 1143000, 3657600, 3200000, "Initial left content"),
    "bullet_1":     (12, "Bullet12",     4572000, 1143000, 4115000,  514350, "Initial bullet 1"),
    "bullet_2":     (13, "Bullet13",     4572000, 1743000, 4115000,  514350, "Initial bullet 2"),
    "bullet_3":     (14, "Bullet14",     4572000, 2343000, 4115000,  514350, "Initial bullet 3"),
    "unrelated":    (15, "Unrelated15",   457200, 4400000, 4115000,  514350, "Initial unrelated"),
}
_GROUP_ID   = 20
_CHILD_ID   = 21
_GROUP_X    = 6400000
_GROUP_Y    = 4400000
_GROUP_W    = 2000000
_GROUP_H    =  514350
_CHILD_TEXT = "Initial grouped child"


def _sp_xml(shape_id: int, name: str, x: int, y: int, w: int, h: int, text: str) -> str:
    return (
        f'<p:sp {_NS}>'
        f"<p:nvSpPr>"
        f'<p:cNvPr id="{shape_id}" name="{name}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/>'
        f"</p:nvSpPr>"
        f"<p:spPr><a:xfrm>"
        f'<a:off x="{x}" y="{y}"/>'
        f'<a:ext cx="{w}" cy="{h}"/>'
        f"</a:xfrm>"
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f"</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
        f"</p:txBody></p:sp>"
    )


def _grp_xml(
    group_id: int,
    group_name: str,
    gx: int,
    gy: int,
    gw: int,
    gh: int,
    child_id: int,
    child_name: str,
    child_text: str,
) -> str:
    return (
        f'<p:grpSp {_NS}>'
        f"<p:nvGrpSpPr>"
        f'<p:cNvPr id="{group_id}" name="{group_name}"/>'
        f"<p:cNvGrpSpPr/><p:nvPr/>"
        f"</p:nvGrpSpPr>"
        f"<p:grpSpPr><a:xfrm>"
        f'<a:off x="{gx}" y="{gy}"/>'
        f'<a:ext cx="{gw}" cy="{gh}"/>'
        f'<a:chOff x="0" y="0"/>'
        f'<a:chExt cx="{gw}" cy="{gh}"/>'
        f"</a:xfrm></p:grpSpPr>"
        f"<p:sp>"
        f"<p:nvSpPr>"
        f'<p:cNvPr id="{child_id}" name="{child_name}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/>'
        f"</p:nvSpPr>"
        f"<p:spPr><a:xfrm>"
        f'<a:off x="0" y="0"/>'
        f'<a:ext cx="{gw}" cy="{gh}"/>'
        f"</a:xfrm>"
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f"</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>{child_text}</a:t></a:r></a:p>"
        f"</p:txBody></p:sp></p:grpSp>"
    )


def make_pingpong_pptx(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Create a PPTX with 7 shapes (6 top-level + 1 group with child).

    Returns (pptx_path, shape_paths) where shape_paths maps name → shape_path string.
    """
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank

    for _name, (sid, sname, x, y, w, h, text) in _SHAPES.items():
        slide.shapes._spTree.append(etree.fromstring(_sp_xml(sid, sname, x, y, w, h, text)))

    slide.shapes._spTree.append(
        etree.fromstring(
            _grp_xml(
                _GROUP_ID, "Group20",
                _GROUP_X, _GROUP_Y, _GROUP_W, _GROUP_H,
                _CHILD_ID, "Child21", _CHILD_TEXT,
            )
        )
    )

    pptx_path = tmp_path / "pingpong_fixture.pptx"
    prs.save(str(pptx_path))

    shape_paths = {name: str(sid) for name, (sid, *_) in _SHAPES.items()}
    shape_paths["grouped_child"] = f"{_GROUP_ID}/{_CHILD_ID}"

    return pptx_path, shape_paths


# ---------------------------------------------------------------------------
# Human-edit simulation helpers
# ---------------------------------------------------------------------------


def _find_toplevel_shape(slide, shape_id: int):
    for shape in slide.shapes:
        if shape.shape_id == shape_id:
            return shape
    return None


def simulate_human_title_edit(pptx_path: Path, new_text: str) -> None:
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    shape = _find_toplevel_shape(slide, _SHAPES["title"][0])
    if shape:
        shape.text_frame.text = new_text
    prs.save(str(pptx_path))


def simulate_human_text_edit(pptx_path: Path, shape_id: int, new_text: str) -> None:
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    shape = _find_toplevel_shape(slide, shape_id)
    if shape and hasattr(shape, "text_frame"):
        shape.text_frame.text = new_text
    prs.save(str(pptx_path))


def simulate_human_geometry_edit(pptx_path: Path, shape_id: int, new_x: int) -> None:
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    shape = _find_toplevel_shape(slide, shape_id)
    if shape:
        shape.left = new_x
    prs.save(str(pptx_path))


def simulate_human_group_move(pptx_path: Path, group_id: int, new_x: int) -> None:
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    shape = _find_toplevel_shape(slide, group_id)
    if shape:
        shape.left = new_x
    prs.save(str(pptx_path))


def simulate_human_format_edit(
    pptx_path: Path,
    shape_id: int,
    *,
    bold: bool = True,
) -> None:
    """Set bold on first run of first paragraph — changes formatting_fingerprint."""
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    shape = _find_toplevel_shape(slide, shape_id)
    if shape and hasattr(shape, "text_frame"):
        tf = shape.text_frame
        paras = tf.paragraphs
        if paras and paras[0].runs:
            paras[0].runs[0].font.bold = bold
    prs.save(str(pptx_path))


def simulate_human_add_shape(
    pptx_path: Path,
    shape_id: int,
    x: int,
    y: int,
    w: int,
    h: int,
    text: str,
) -> None:
    """Inject a new top-level text shape into the PPTX (simulates user adding a shape)."""
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    xml = _sp_xml(shape_id, f"HumanAdded{shape_id}", x, y, w, h, text)
    slide.shapes._spTree.append(etree.fromstring(xml))
    prs.save(str(pptx_path))


def simulate_human_delete_shape(pptx_path: Path, shape_id: int) -> None:
    """Remove a top-level shape from the PPTX (simulates user deleting a shape)."""
    prs = Presentation(str(pptx_path))
    slide = prs.slides[0]
    sp_tree = slide.shapes._spTree
    shapes_to_remove = [s for s in slide.shapes if s.shape_id == shape_id]
    for s in shapes_to_remove:
        sp_tree.remove(s._element)
    prs.save(str(pptx_path))
