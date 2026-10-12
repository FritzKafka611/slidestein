"""Unit tests for the canonical SHA-256 state hash."""

from __future__ import annotations

from slidestein.interactive.hashing import compute_slide_state_hash
from slidestein.interactive.models import ShapeState


def _make_shape(path="5", shape_id=5, text="Hello", x=1000, y=2000, w=5000, h=1000) -> ShapeState:
    return ShapeState(
        shape_id=shape_id,
        shape_path=path,
        name=f"S{shape_id}",
        shape_type="text_box",
        text=text,
        x=x,
        y=y,
        width=w,
        height=h,
    )


_W = 9144000
_H = 6858000


def test_same_shapes_same_hash():
    shapes = [_make_shape()]
    h1 = compute_slide_state_hash(shapes, _W, _H)
    h2 = compute_slide_state_hash(shapes, _W, _H)
    assert h1 == h2


def test_different_text_different_hash():
    shapes_a = [_make_shape(text="Hello")]
    shapes_b = [_make_shape(text="Goodbye")]
    assert compute_slide_state_hash(shapes_a, _W, _H) != compute_slide_state_hash(shapes_b, _W, _H)


def test_different_x_different_hash():
    shapes_a = [_make_shape(x=1000)]
    shapes_b = [_make_shape(x=2000)]
    assert compute_slide_state_hash(shapes_a, _W, _H) != compute_slide_state_hash(shapes_b, _W, _H)


def test_adding_shape_changes_hash():
    s1 = _make_shape(path="5", shape_id=5)
    s2 = _make_shape(path="6", shape_id=6)
    h1 = compute_slide_state_hash([s1], _W, _H)
    h2 = compute_slide_state_hash([s1, s2], _W, _H)
    assert h1 != h2


def test_slide_width_change_changes_hash():
    shapes = [_make_shape()]
    h1 = compute_slide_state_hash(shapes, _W, _H)
    h2 = compute_slide_state_hash(shapes, _W + 1, _H)
    assert h1 != h2


def test_shape_order_does_not_affect_hash():
    s1 = _make_shape(path="5", shape_id=5)
    s2 = _make_shape(path="6", shape_id=6)
    h_forward = compute_slide_state_hash([s1, s2], _W, _H)
    h_reverse = compute_slide_state_hash([s2, s1], _W, _H)
    assert h_forward == h_reverse


def test_hash_is_64_char_hex():
    h = compute_slide_state_hash([_make_shape()], _W, _H)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_captured_at_excluded_from_hash():
    """captured_at is not passed to compute_slide_state_hash — excluded by design."""
    from slidestein.interactive.models import SlideState

    shapes = [_make_shape()]
    h = compute_slide_state_hash(shapes, _W, _H)
    # Construct two SlideState objects with different captured_at, same shapes
    s1 = SlideState(
        slide_number=1, slide_width=_W, slide_height=_H,
        shapes=shapes, state_hash=h, captured_at="2026-01-01T00:00:00+00:00",
    )
    s2 = SlideState(
        slide_number=1, slide_width=_W, slide_height=_H,
        shapes=shapes, state_hash=h, captured_at="2099-12-31T23:59:59+00:00",
    )
    # Both have the same state_hash because captured_at is excluded
    assert s1.state_hash == s2.state_hash


def test_none_text_and_non_none_text_differ():
    s_with_text = _make_shape(text="something")
    s_without_text = ShapeState(
        shape_id=5, shape_path="5", name="S5", shape_type="text_box",
        text=None, x=1000, y=2000, width=5000, height=1000,
    )
    h1 = compute_slide_state_hash([s_with_text], _W, _H)
    h2 = compute_slide_state_hash([s_without_text], _W, _H)
    assert h1 != h2


def test_formatting_fingerprint_affects_hash():
    s_no_fp = _make_shape()
    s_with_fp = ShapeState(
        shape_id=5, shape_path="5", name="S5", shape_type="text_box",
        text="Hello", x=1000, y=2000, width=5000, height=1000,
        formatting_fingerprint="abcd1234abcd1234",
    )
    h1 = compute_slide_state_hash([s_no_fp], _W, _H)
    h2 = compute_slide_state_hash([s_with_fp], _W, _H)
    assert h1 != h2
