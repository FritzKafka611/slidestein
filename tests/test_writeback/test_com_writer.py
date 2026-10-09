"""Tests for writeback/com_writer.py — COM mock tests.

No real PowerPoint COM calls.  All COM objects are replaced with MagicMock.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from slidestein.drafting.models import SlotDraftAction
from slidestein.writeback.com_writer import (
    _find_in_com_collection,
    normalize_for_com,
    normalize_readback,
    resolve_com_shape_by_path,
)
from slidestein.writeback.errors import PowerPointWritebackError
from slidestein.writeback.models import WritebackOperation, WritebackPlan
from slidestein.writeback.versions import WRITEBACK_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# normalize_for_com
# ---------------------------------------------------------------------------


def test_normalize_for_com_no_newlines() -> None:
    assert normalize_for_com("Hello World") == "Hello World"


def test_normalize_for_com_single_newline() -> None:
    assert normalize_for_com("Line1\nLine2") == "Line1\rLine2"


def test_normalize_for_com_multiple_newlines() -> None:
    assert normalize_for_com("a\nb\nc") == "a\rb\rc"


def test_normalize_for_com_empty_string() -> None:
    assert normalize_for_com("") == ""


# ---------------------------------------------------------------------------
# normalize_readback
# ---------------------------------------------------------------------------


def test_normalize_readback_no_change() -> None:
    assert normalize_readback("Plain text") == "Plain text"


def test_normalize_readback_crlf() -> None:
    assert normalize_readback("a\r\nb") == "a\nb"


def test_normalize_readback_cr_only() -> None:
    assert normalize_readback("a\rb") == "a\nb"


def test_normalize_readback_vertical_tab() -> None:
    assert normalize_readback("a\x0bb") == "a\nb"


def test_normalize_readback_mixed() -> None:
    result = normalize_readback("a\r\nb\rc\x0bd")
    assert result == "a\nb\nc\nd"


# ---------------------------------------------------------------------------
# _find_in_com_collection
# ---------------------------------------------------------------------------


def _com_shape(com_id: int) -> MagicMock:
    s = MagicMock()
    s.Id = com_id
    return s


def test_find_in_com_collection_found() -> None:
    shapes = [_com_shape(3), _com_shape(7), _com_shape(12)]
    result = _find_in_com_collection(shapes, 7)
    assert result is shapes[1]


def test_find_in_com_collection_not_found() -> None:
    shapes = [_com_shape(3), _com_shape(7)]
    result = _find_in_com_collection(shapes, 99)
    assert result is None


def test_find_in_com_collection_empty() -> None:
    result = _find_in_com_collection([], 7)
    assert result is None


# ---------------------------------------------------------------------------
# resolve_com_shape_by_path
# ---------------------------------------------------------------------------


def _mock_slide_com(shapes: list[MagicMock]) -> MagicMock:
    slide = MagicMock()
    slide.Shapes = shapes
    return slide


def test_resolve_top_level_found() -> None:
    shape = _com_shape(7)
    slide = _mock_slide_com([shape])
    result = resolve_com_shape_by_path(slide, "7")
    assert result is shape


def test_resolve_top_level_not_found() -> None:
    slide = _mock_slide_com([_com_shape(3)])
    result = resolve_com_shape_by_path(slide, "99")
    assert result is None


def test_resolve_group_child() -> None:
    child = _com_shape(5)
    group = _com_shape(12)
    group.GroupItems = [child]  # COM GroupItems is flat (leaf shapes only)
    slide = _mock_slide_com([group])
    result = resolve_com_shape_by_path(slide, "12/5")
    assert result is child


def test_resolve_nested_group() -> None:
    """For a 3-part path, COM GroupItems is flat — we search for the leaf in the
    top-level group's GroupItems directly (intermediate group 38 not exposed)."""
    inner = _com_shape(37)   # leaf shape
    outer = _com_shape(31)
    # COM's GroupItems of shape 31 is flat: contains leaf shapes directly
    # (intermediate group shape 38 is NOT in GroupItems)
    outer.GroupItems = [inner]
    slide = _mock_slide_com([outer])
    result = resolve_com_shape_by_path(slide, "31/38/37")
    assert result is inner


def test_resolve_group_child_missing_returns_none() -> None:
    group = _com_shape(12)
    group.GroupItems = [_com_shape(99)]
    slide = _mock_slide_com([group])
    result = resolve_com_shape_by_path(slide, "12/5")
    assert result is None


def test_resolve_invalid_path_segment_returns_none() -> None:
    slide = _mock_slide_com([_com_shape(7)])
    result = resolve_com_shape_by_path(slide, "abc")
    assert result is None


# ---------------------------------------------------------------------------
# execute_plan (COM interaction tests)
# ---------------------------------------------------------------------------


def _make_plan(
    operations: list[WritebackOperation] | None = None,
) -> WritebackPlan:
    from pathlib import Path
    return WritebackPlan(
        schema_version=WRITEBACK_SCHEMA_VERSION,
        slide_id="slide-001",
        deck_id="deck-abc",
        slide_number=2,
        resolved_slide_number=2,
        native_slide_id=256,
        source_pptx=Path("/src/deck.pptx"),
        output_pptx=Path("/out/deck.pptx"),
        operations=operations or [],
        replacement_count=0,
        clear_count=0,
        before_structure_fingerprint="fp",
    )


def _make_replace_op(
    slot_id: str = "s1",
    shape_id: int = 7,
    shape_path: str = "7",
    text: str = "New title",
) -> WritebackOperation:
    return WritebackOperation(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        action=SlotDraftAction.REPLACE,
        text=text,
    )


def _make_clear_op(
    slot_id: str = "s1",
    shape_id: int = 7,
    shape_path: str = "7",
) -> WritebackOperation:
    return WritebackOperation(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=shape_path,
        action=SlotDraftAction.CLEAR,
        text=None,
    )


def _mock_com_env(
    shape_id: int = 7,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return (ppt, prs, slide, shape) mocks wired up for COM."""
    tr = MagicMock()
    tf = MagicMock()
    tf.TextRange = tr

    shape = MagicMock()
    shape.Id = shape_id
    shape.TextFrame = tf

    slide = MagicMock()
    slide.Shapes = [shape]

    prs = MagicMock()
    prs.Slides = MagicMock(return_value=slide)

    ppt = MagicMock()
    ppt.Presentations = MagicMock()
    ppt.Presentations.Open = MagicMock(return_value=prs)

    return ppt, prs, slide, shape


def test_replace_sets_correct_com_text(tmp_path: Path) -> None:
    from pathlib import Path as _Path
    from slidestein.writeback.com_writer import execute_plan

    out_file = tmp_path / "out.pptx"
    op = _make_replace_op(text="Hello\nWorld")
    plan = _make_plan(operations=[op])
    # Override output path to a writable location
    from dataclasses import replace as dc_replace
    plan = dc_replace(plan, output_pptx=out_file)

    ppt, prs, slide, shape = _mock_com_env(shape_id=7)

    with patch("comtypes.client.CreateObject", return_value=ppt):
        execute_plan(plan)

    # COM normalisation: \n → \r
    assert shape.TextFrame.TextRange.Text == "Hello\rWorld"


def test_clear_sets_empty_string(tmp_path: Path) -> None:
    from dataclasses import replace as dc_replace
    from slidestein.writeback.com_writer import execute_plan

    out_file = tmp_path / "out.pptx"
    op = _make_clear_op()
    plan = _make_plan(operations=[op])
    plan = dc_replace(plan, output_pptx=out_file)

    ppt, prs, slide, shape = _mock_com_env(shape_id=7)

    with patch("comtypes.client.CreateObject", return_value=ppt):
        execute_plan(plan)

    assert shape.TextFrame.TextRange.Text == ""


def test_needs_input_action_raises() -> None:
    """NEEDS_INPUT must never reach execution — defensive guard."""
    from slidestein.writeback.com_writer import _apply_operation

    op = WritebackOperation(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
    )

    shape = MagicMock()
    shape.Id = 7
    slide = MagicMock()
    slide.Shapes = [shape]

    with pytest.raises(PowerPointWritebackError, match="Impossible"):
        _apply_operation(slide, op, 2)


def test_shape_not_found_in_com_raises() -> None:
    from slidestein.writeback.com_writer import _apply_operation

    op = _make_replace_op(shape_id=7, shape_path="7", text="x")
    slide = MagicMock()
    slide.Shapes = [_com_shape(99)]  # shape 7 not present

    with pytest.raises(PowerPointWritebackError, match="Cannot resolve shape_path"):
        _apply_operation(slide, op, 2)


def test_shape_id_mismatch_in_com_raises() -> None:
    from slidestein.writeback.com_writer import _apply_operation

    op = _make_replace_op(shape_id=7, shape_path="7", text="x")
    # Shape at path "7" but Id=99 in COM (shouldn't happen after preflight, but defensive)
    shape = _com_shape(99)  # wrong ID
    slide = MagicMock()
    # Arrange so that the collection has shape_id 7, but shape.Id = 99
    # We need a shape whose Id as integer is 7 in the collection lookup
    # but then reports 99 when read directly. That's the failure case.
    # Simpler: just mock _find_in_com_collection to return shape with wrong Id
    shape_wrong = MagicMock()
    shape_wrong.Id = 99  # expected 7
    slide.Shapes = [shape_wrong]
    # _find_in_com_collection looks for int(shape.Id) == 7, which won't match 99
    # So it will return None → "Cannot resolve shape_path", not shape_id mismatch.
    # To test shape_id mismatch, mock at a lower level:
    with patch(
        "slidestein.writeback.com_writer.resolve_com_shape_by_path",
        return_value=shape_wrong,  # returns something, but wrong Id
    ):
        with pytest.raises(PowerPointWritebackError, match="Id=99"):
            _apply_operation(slide, op, 2)


# ---------------------------------------------------------------------------
# COM lifecycle: Close() and Quit() called in finally on success and failure
# ---------------------------------------------------------------------------


def test_com_lifecycle_close_and_quit_on_success(tmp_path: Path) -> None:
    from dataclasses import replace as dc_replace
    from slidestein.writeback.com_writer import execute_plan

    out_file = tmp_path / "out.pptx"
    op = _make_replace_op(text="Hi")
    plan = _make_plan(operations=[op])
    plan = dc_replace(plan, output_pptx=out_file)

    ppt, prs, slide, shape = _mock_com_env(shape_id=7)

    with patch("comtypes.client.CreateObject", return_value=ppt):
        execute_plan(plan)

    prs.Close.assert_called_once()
    ppt.Quit.assert_called_once()


def test_com_lifecycle_close_and_quit_on_operation_failure(tmp_path: Path) -> None:
    """Even when an operation raises, COM must be closed cleanly."""
    from dataclasses import replace as dc_replace
    from slidestein.writeback.com_writer import execute_plan

    out_file = tmp_path / "out.pptx"
    op = _make_replace_op(text="Hi")
    plan = _make_plan(operations=[op])
    plan = dc_replace(plan, output_pptx=out_file)

    ppt, prs, slide, shape = _mock_com_env(shape_id=7)

    # Make TextFrame.TextRange.Text assignment raise
    type(shape.TextFrame.TextRange).Text = property(
        fget=lambda self: "",
        fset=lambda self, v: (_ for _ in ()).throw(Exception("COM write error")),
    )
    # Simpler: just patch the _apply_operation to raise after COM is open
    with (
        patch("comtypes.client.CreateObject", return_value=ppt),
        patch(
            "slidestein.writeback.com_writer._apply_operation",
            side_effect=PowerPointWritebackError("test error"),
        ),
    ):
        with pytest.raises(PowerPointWritebackError, match="test error"):
            execute_plan(plan)

    # COM must be closed even when an operation fails
    prs.Close.assert_called_once()
    ppt.Quit.assert_called_once()


def test_com_lifecycle_close_and_quit_on_save_failure(tmp_path: Path) -> None:
    """Even when SaveAs raises, COM must be closed cleanly."""
    from dataclasses import replace as dc_replace
    from slidestein.writeback.com_writer import execute_plan

    out_file = tmp_path / "out.pptx"
    op = _make_replace_op(text="Hi")
    plan = _make_plan(operations=[op])
    plan = dc_replace(plan, output_pptx=out_file)

    ppt, prs, slide, shape = _mock_com_env(shape_id=7)
    prs.SaveAs.side_effect = Exception("SaveAs failed")

    with patch("comtypes.client.CreateObject", return_value=ppt):
        with pytest.raises(PowerPointWritebackError):
            execute_plan(plan)

    prs.Close.assert_called_once()
    ppt.Quit.assert_called_once()
