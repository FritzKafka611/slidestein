"""Unit tests for SlideStateDiffService."""

from __future__ import annotations

from slidestein.interactive.diff import SlideStateDiffService
from slidestein.interactive.hashing import compute_slide_state_hash
from slidestein.interactive.models import ShapeState, SlideState


def _make_shape(path="5", shape_id=5, text="Hello", x=1000, y=2000, w=5000, h=1000,
                fp=None) -> ShapeState:
    return ShapeState(
        shape_id=shape_id,
        shape_path=path,
        name=f"S{path}",
        shape_type="text_box",
        text=text,
        x=x,
        y=y,
        width=w,
        height=h,
        formatting_fingerprint=fp,
    )


def _make_state(shapes: list[ShapeState]) -> SlideState:
    w, h = 9144000, 6858000
    return SlideState(
        slide_number=1,
        slide_width=w,
        slide_height=h,
        shapes=shapes,
        state_hash=compute_slide_state_hash(shapes, w, h),
    )


_svc = SlideStateDiffService()


def test_identical_states_no_changes():
    shape = _make_shape()
    state = _make_state([shape])
    diff = _svc.diff(state, state)
    assert not diff.has_changes
    assert diff.shape_deltas == []
    assert diff.added_shapes == []
    assert diff.deleted_shapes == []


def test_text_change_detected():
    base = _make_state([_make_shape(text="Hello")])
    curr = _make_state([_make_shape(text="Goodbye")])
    diff = _svc.diff(base, curr)
    assert diff.has_changes
    assert len(diff.shape_deltas) == 1
    delta = diff.shape_deltas[0]
    assert "text" in delta.changed_fields
    assert "text_changed" in delta.delta_categories


def test_geometry_change_x_detected():
    base = _make_state([_make_shape(x=1000)])
    curr = _make_state([_make_shape(x=2000)])
    diff = _svc.diff(base, curr)
    assert diff.has_changes
    delta = diff.shape_deltas[0]
    assert "x" in delta.changed_fields
    assert "geometry_changed" in delta.delta_categories


def test_text_and_geometry_both_categories():
    base = _make_state([_make_shape(text="A", x=100)])
    curr = _make_state([_make_shape(text="B", x=200)])
    diff = _svc.diff(base, curr)
    delta = diff.shape_deltas[0]
    assert "text_changed" in delta.delta_categories
    assert "geometry_changed" in delta.delta_categories


def test_added_shape_detected():
    s1 = _make_shape(path="5", shape_id=5)
    s2 = _make_shape(path="6", shape_id=6)
    base = _make_state([s1])
    curr = _make_state([s1, s2])
    diff = _svc.diff(base, curr)
    assert diff.has_changes
    assert len(diff.added_shapes) == 1
    assert diff.added_shapes[0].shape_path == "6"


def test_deleted_shape_detected():
    s1 = _make_shape(path="5", shape_id=5)
    s2 = _make_shape(path="6", shape_id=6)
    base = _make_state([s1, s2])
    curr = _make_state([s1])
    diff = _svc.diff(base, curr)
    assert diff.has_changes
    assert len(diff.deleted_shapes) == 1
    assert diff.deleted_shapes[0].shape_path == "6"


def test_formatting_change_detected():
    base = _make_state([_make_shape(fp="aabbccdd11223344")])
    curr = _make_state([_make_shape(fp="ddccbbaa44332211")])
    diff = _svc.diff(base, curr)
    delta = diff.shape_deltas[0]
    assert "formatting_fingerprint" in delta.changed_fields
    assert "formatting_changed" in delta.delta_categories


def test_no_geometry_category_when_only_text_changed():
    base = _make_state([_make_shape(text="A")])
    curr = _make_state([_make_shape(text="B")])
    diff = _svc.diff(base, curr)
    delta = diff.shape_deltas[0]
    assert "geometry_changed" not in delta.delta_categories
    assert "text_changed" in delta.delta_categories


def test_has_changes_reflects_any_change():
    base = _make_state([_make_shape()])
    curr = _make_state([_make_shape()])
    assert not _svc.diff(base, curr).has_changes

    curr2 = _make_state([_make_shape(text="different")])
    assert _svc.diff(base, curr2).has_changes


def test_diff_hashes_recorded():
    base = _make_state([_make_shape()])
    curr = _make_state([_make_shape(text="changed")])
    diff = _svc.diff(base, curr)
    assert diff.base_state_hash == base.state_hash
    assert diff.current_state_hash == curr.state_hash


def test_before_after_shape_state_preserved():
    base = _make_state([_make_shape(text="before")])
    curr = _make_state([_make_shape(text="after")])
    diff = _svc.diff(base, curr)
    delta = diff.shape_deltas[0]
    assert delta.before.text == "before"  # type: ignore[union-attr]
    assert delta.after.text == "after"   # type: ignore[union-attr]
