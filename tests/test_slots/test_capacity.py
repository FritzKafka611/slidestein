"""Tests for estimate_slot_capacity() — deterministic, no LLM."""

from __future__ import annotations

import pytest

from slidestein.slots.capacity import (
    _DEFAULT_FONT_PT,
    _EMU_PER_PT,
    estimate_slot_capacity,
)
from slidestein.slots.models import NativeShapeDescriptor


_SLIDE_W = 9144000
_SLIDE_H = 5143500


def _make_descriptor(
    width: int = 7315200,
    height: int = 685800,
    text: str = "Hello world",
    font_size_pt: float | None = 12.0,
) -> NativeShapeDescriptor:
    return NativeShapeDescriptor(
        shape_id=1,
        shape_path="1",
        shape_type="AUTO_SHAPE",
        x=0,
        y=0,
        width=width,
        height=height,
        x_ratio=0.0,
        y_ratio=0.0,
        width_ratio=width / _SLIDE_W,
        height_ratio=height / _SLIDE_H,
        z_order=0,
        has_text=bool(text),
        text=text,
        is_placeholder=False,
        is_group=False,
        is_table=False,
        has_text_frame=True,
        font_size_pt=font_size_pt,
        can_edit_text=True,
        source_kind="text_box",
    )


class TestCurrentStats:
    def test_current_character_count(self):
        d = _make_descriptor(text="Hello world")
        cap = estimate_slot_capacity(d)
        assert cap.current_character_count == len("Hello world")

    def test_current_line_count_single_line(self):
        d = _make_descriptor(text="Hello world")
        cap = estimate_slot_capacity(d)
        assert cap.current_line_count == 1

    def test_current_line_count_multiline(self):
        d = _make_descriptor(text="Line 1\nLine 2\nLine 3")
        cap = estimate_slot_capacity(d)
        assert cap.current_line_count == 3

    def test_empty_text_zero_current(self):
        d = _make_descriptor(text="")
        cap = estimate_slot_capacity(d)
        assert cap.current_character_count == 0
        assert cap.current_line_count == 0


class TestMaxEstimates:
    def test_larger_shape_gets_larger_max_chars(self):
        small = _make_descriptor(width=914400, height=457200)
        large = _make_descriptor(width=7315200, height=2286000)
        cap_small = estimate_slot_capacity(small)
        cap_large = estimate_slot_capacity(large)
        assert cap_large.max_characters_estimate > cap_small.max_characters_estimate

    def test_larger_shape_gets_larger_max_lines(self):
        short = _make_descriptor(width=7315200, height=457200)
        tall = _make_descriptor(width=7315200, height=2743200)
        cap_short = estimate_slot_capacity(short)
        cap_tall = estimate_slot_capacity(tall)
        assert cap_tall.max_lines_estimate > cap_short.max_lines_estimate

    def test_smaller_font_fits_more_chars(self):
        d_big_font = _make_descriptor(width=3657600, height=685800, font_size_pt=24.0)
        d_small_font = _make_descriptor(width=3657600, height=685800, font_size_pt=8.0)
        cap_big = estimate_slot_capacity(d_big_font)
        cap_small = estimate_slot_capacity(d_small_font)
        assert cap_small.max_characters_estimate > cap_big.max_characters_estimate

    def test_none_font_uses_default(self):
        d_none = _make_descriptor(font_size_pt=None)
        d_default = _make_descriptor(font_size_pt=_DEFAULT_FONT_PT)
        cap_none = estimate_slot_capacity(d_none)
        cap_default = estimate_slot_capacity(d_default)
        assert cap_none.max_characters_estimate == cap_default.max_characters_estimate


class TestRelativeCapacity:
    def test_small_relative_capacity(self):
        # Very small shape
        d = _make_descriptor(width=228600, height=228600, font_size_pt=12.0)
        cap = estimate_slot_capacity(d)
        assert cap.relative_capacity == "small"

    def test_large_relative_capacity(self):
        # Large body text shape
        d = _make_descriptor(width=7315200, height=2743200, font_size_pt=12.0)
        cap = estimate_slot_capacity(d)
        assert cap.relative_capacity == "large"


class TestDeterminism:
    def test_same_inputs_same_output(self):
        d = _make_descriptor()
        cap1 = estimate_slot_capacity(d)
        cap2 = estimate_slot_capacity(d)
        assert cap1 == cap2

    def test_different_text_different_current_count(self):
        d1 = _make_descriptor(text="Short")
        d2 = _make_descriptor(text="A much longer text that has many more characters")
        cap1 = estimate_slot_capacity(d1)
        cap2 = estimate_slot_capacity(d2)
        assert cap1.current_character_count != cap2.current_character_count
        # Max estimates are shape-based, not text-based — should be equal
        assert cap1.max_characters_estimate == cap2.max_characters_estimate
