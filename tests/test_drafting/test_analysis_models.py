"""Tests for ContentDraftModelOutput (compact LLM parse target)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.drafting.analysis_models import (
    ContentDraftModelOutput,
    SlotContentGap,
    SlotReplacement,
)


def _make(**overrides) -> ContentDraftModelOutput:
    base = {
        "replacements": [],
        "clear_slots": [],
        "needs_input": [],
        "open_questions": [],
        "drafting_summary": "Summary.",
    }
    base.update(overrides)
    return ContentDraftModelOutput(**base)


# ---------------------------------------------------------------------------
# Valid construction
# ---------------------------------------------------------------------------


def test_all_empty_lists_valid():
    out = _make()
    assert out.replacements == []
    assert out.clear_slots == []
    assert out.needs_input == []


def test_replacements_only():
    out = _make(replacements=[SlotReplacement(slot_key="K1", text="Hello")])
    assert len(out.replacements) == 1


def test_clear_slots_only():
    out = _make(clear_slots=["K2"])
    assert out.clear_slots == ["K2"]


def test_needs_input_only():
    out = _make(needs_input=[SlotContentGap(slot_key="K3", missing_information="Revenue.")])
    assert len(out.needs_input) == 1


def test_mixed_disjoint_valid():
    out = _make(
        replacements=[SlotReplacement(slot_key="K1", text="Hi")],
        clear_slots=["K2"],
        needs_input=[SlotContentGap(slot_key="K3", missing_information="x")],
    )
    assert len(out.replacements) + len(out.clear_slots) + len(out.needs_input) == 3


# ---------------------------------------------------------------------------
# Within-category duplicates
# ---------------------------------------------------------------------------


def test_duplicate_in_replacements_rejected():
    with pytest.raises(ValidationError, match="K1"):
        _make(replacements=[
            SlotReplacement(slot_key="K1", text="First"),
            SlotReplacement(slot_key="K1", text="Second"),
        ])


def test_duplicate_in_clear_slots_rejected():
    with pytest.raises(ValidationError, match="K2"):
        _make(clear_slots=["K2", "K2"])


def test_duplicate_in_needs_input_rejected():
    with pytest.raises(ValidationError, match="K3"):
        _make(needs_input=[
            SlotContentGap(slot_key="K3", missing_information="x"),
            SlotContentGap(slot_key="K3", missing_information="y"),
        ])


# ---------------------------------------------------------------------------
# Cross-category overlaps
# ---------------------------------------------------------------------------


def test_overlap_replace_and_clear_rejected():
    with pytest.raises(ValidationError):
        _make(
            replacements=[SlotReplacement(slot_key="K1", text="Hi")],
            clear_slots=["K1"],
        )


def test_overlap_replace_and_needs_input_rejected():
    with pytest.raises(ValidationError):
        _make(
            replacements=[SlotReplacement(slot_key="K4", text="Hi")],
            needs_input=[SlotContentGap(slot_key="K4", missing_information="x")],
        )


def test_overlap_clear_and_needs_input_rejected():
    with pytest.raises(ValidationError):
        _make(
            clear_slots=["K5"],
            needs_input=[SlotContentGap(slot_key="K5", missing_information="x")],
        )


def test_triple_overlap_rejected():
    with pytest.raises(ValidationError):
        _make(
            replacements=[SlotReplacement(slot_key="K1", text="Hi")],
            clear_slots=["K1"],
            needs_input=[SlotContentGap(slot_key="K1", missing_information="x")],
        )


# ---------------------------------------------------------------------------
# Extra fields forbidden
# ---------------------------------------------------------------------------


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        ContentDraftModelOutput(
            replacements=[],
            clear_slots=[],
            needs_input=[],
            open_questions=[],
            drafting_summary="d",
            unexpected_field="boom",
        )


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip():
    out = _make(
        replacements=[SlotReplacement(slot_key="K1", text="Answer-first title.")],
        clear_slots=["K2"],
        needs_input=[SlotContentGap(slot_key="K3", missing_information="Need owner.")],
        open_questions=["Who is the executive sponsor?"],
        drafting_summary="Drafted title; K3 needs owner.",
    )
    restored = ContentDraftModelOutput.model_validate_json(out.model_dump_json())
    assert restored.replacements[0].slot_key == "K1"
    assert restored.clear_slots == ["K2"]
    assert restored.needs_input[0].slot_key == "K3"
