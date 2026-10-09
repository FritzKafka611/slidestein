"""Capacity estimator for editable template slots (M5.2).

Deterministic — no LLM calls.  Estimates are based on shape geometry and
the font size extracted by the inspector.
"""

from __future__ import annotations

from slidestein.slots.models import NativeShapeDescriptor, SlotCapacity

_EMU_PER_PT: float = 12700.0   # 1 pt = 12700 EMU
_DEFAULT_FONT_PT: float = 12.0
_CHAR_WIDTH_RATIO: float = 0.6  # average character width as fraction of font size
_LINE_HEIGHT_RATIO: float = 1.2  # line height as fraction of font size


def estimate_slot_capacity(descriptor: NativeShapeDescriptor) -> SlotCapacity:
    """Estimate the text capacity of an editable slot from shape geometry.

    All arithmetic is deterministic and depends only on the descriptor fields;
    no randomness, no LLM calls.
    """
    text = descriptor.text or ""
    current_chars = len(text)
    current_lines = text.count("\n") + 1 if text else 0

    font_pt = descriptor.font_size_pt if descriptor.font_size_pt else _DEFAULT_FONT_PT

    width_pt = descriptor.width / _EMU_PER_PT
    height_pt = descriptor.height / _EMU_PER_PT

    chars_per_line = max(1, int(width_pt / (font_pt * _CHAR_WIDTH_RATIO)))
    max_lines = max(1, int(height_pt / (font_pt * _LINE_HEIGHT_RATIO)))
    max_chars = chars_per_line * max_lines

    if max_chars < 50:
        relative = "small"
    elif max_chars < 200:
        relative = "medium"
    else:
        relative = "large"

    return SlotCapacity(
        max_characters_estimate=max_chars,
        max_lines_estimate=max_lines,
        current_character_count=current_chars,
        current_line_count=current_lines,
        relative_capacity=relative,
    )
