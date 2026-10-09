"""Tests for SlotDraftAssignment and SlideContentDraft domain models."""

from __future__ import annotations

import pytest

from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.drafting.versions import CONTENT_DRAFT_SCHEMA_VERSION
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assignment(**overrides) -> dict:
    base = {
        "slot_id": "s1",
        "shape_id": 10,
        "shape_path": "Slide/Shape",
        "slot_role": SlotRole.TITLE,
        "semantic_label": "Slide title",
        "action": SlotDraftAction.REPLACE,
        "text": "The key message",
        "missing_information": None,
        "character_count": 15,
        "capacity_characters": 120,
        "capacity_utilization": 0.125,
        "explicit_line_count": 1,
        "max_lines_estimate": 2,
    }
    base.update(overrides)
    return base


def _make(action: SlotDraftAction, text=None, missing=None, **kw) -> SlotDraftAssignment:
    d = _assignment(action=action, text=text, missing_information=missing)
    d.update(kw)
    return SlotDraftAssignment(**d)


# ---------------------------------------------------------------------------
# replace action
# ---------------------------------------------------------------------------


def test_replace_valid():
    a = _make(SlotDraftAction.REPLACE, text="Hello")
    assert a.action == SlotDraftAction.REPLACE
    assert a.text == "Hello"
    assert a.missing_information is None


def test_replace_blank_text_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.REPLACE, text="   ")


def test_replace_none_text_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.REPLACE, text=None)


def test_replace_with_missing_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.REPLACE, text="Hello", missing="something")


# ---------------------------------------------------------------------------
# clear action
# ---------------------------------------------------------------------------


def test_clear_valid():
    a = SlotDraftAssignment(
        slot_id="s2",
        shape_id=10,
        shape_path="Slide/Shape",
        slot_role=SlotRole.LABEL,
        semantic_label="Label",
        action=SlotDraftAction.CLEAR,
        text=None,
        missing_information=None,
        character_count=0,
        capacity_characters=40,
        capacity_utilization=0.0,
        explicit_line_count=0,
        max_lines_estimate=1,
    )
    assert a.action == SlotDraftAction.CLEAR
    assert a.text is None
    assert a.missing_information is None


def test_clear_with_text_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.CLEAR, text="some text")


def test_clear_with_missing_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.CLEAR, missing="explain")


# ---------------------------------------------------------------------------
# needs_input action
# ---------------------------------------------------------------------------


def test_needs_input_valid():
    a = SlotDraftAssignment(
        slot_id="s3",
        shape_id=10,
        shape_path="Slide/Shape",
        slot_role=SlotRole.METRIC,
        semantic_label="Revenue metric",
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
        missing_information="Revenue figure not supplied.",
        character_count=0,
        capacity_characters=20,
        capacity_utilization=0.0,
        explicit_line_count=0,
        max_lines_estimate=1,
    )
    assert a.action == SlotDraftAction.NEEDS_INPUT
    assert a.missing_information == "Revenue figure not supplied."


def test_needs_input_with_text_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.NEEDS_INPUT, text="something", missing="something else")


def test_needs_input_blank_missing_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.NEEDS_INPUT, missing="   ")


def test_needs_input_none_missing_rejected():
    with pytest.raises(Exception):
        _make(SlotDraftAction.NEEDS_INPUT, missing=None)


# ---------------------------------------------------------------------------
# SlideContentDraft
# ---------------------------------------------------------------------------


def _draft_assignment(slot_id: str, action: SlotDraftAction) -> SlotDraftAssignment:
    if action == SlotDraftAction.REPLACE:
        return SlotDraftAssignment(
            slot_id=slot_id, shape_id=1, shape_path="S", slot_role=SlotRole.TITLE,
            semantic_label="x", action=action, text="Some text",
            character_count=9, capacity_characters=100,
            capacity_utilization=0.09, explicit_line_count=1, max_lines_estimate=2,
        )
    elif action == SlotDraftAction.CLEAR:
        return SlotDraftAssignment(
            slot_id=slot_id, shape_id=2, shape_path="S", slot_role=SlotRole.LABEL,
            semantic_label="y", action=action,
            character_count=0, capacity_characters=50,
            capacity_utilization=0.0, explicit_line_count=0, max_lines_estimate=1,
        )
    else:
        return SlotDraftAssignment(
            slot_id=slot_id, shape_id=3, shape_path="S", slot_role=SlotRole.METRIC,
            semantic_label="z", action=action, missing_information="Need revenue.",
            character_count=0, capacity_characters=30,
            capacity_utilization=0.0, explicit_line_count=0, max_lines_estimate=1,
        )


def test_is_complete_true():
    draft = SlideContentDraft(
        slide_id="abc", slide_number=1, brief_key_message="msg",
        assignments=[
            _draft_assignment("s1", SlotDraftAction.REPLACE),
            _draft_assignment("s2", SlotDraftAction.CLEAR),
        ],
        drafting_summary="All done.",
        is_complete=True,
    )
    assert draft.is_complete is True


def test_is_complete_false_when_needs_input():
    draft = SlideContentDraft(
        slide_id="abc", slide_number=1, brief_key_message="msg",
        assignments=[
            _draft_assignment("s1", SlotDraftAction.REPLACE),
            _draft_assignment("s2", SlotDraftAction.NEEDS_INPUT),
        ],
        drafting_summary="Partial.",
        is_complete=False,
    )
    assert draft.is_complete is False


def test_schema_version_default():
    draft = SlideContentDraft(
        slide_id="x", slide_number=1, brief_key_message="m",
        assignments=[_draft_assignment("s1", SlotDraftAction.REPLACE)],
        drafting_summary="d", is_complete=True,
    )
    assert draft.schema_version == CONTENT_DRAFT_SCHEMA_VERSION


def test_draft_extra_fields_forbidden():
    with pytest.raises(Exception):
        SlideContentDraft(
            slide_id="x", slide_number=1, brief_key_message="m",
            assignments=[], drafting_summary="d", is_complete=True,
            extra_unexpected_field="boom",
        )


# ---------------------------------------------------------------------------
# is_complete consistency validator
# ---------------------------------------------------------------------------


def test_is_complete_true_consistent():
    draft = SlideContentDraft(
        slide_id="abc", slide_number=1, brief_key_message="msg",
        assignments=[
            _draft_assignment("s1", SlotDraftAction.REPLACE),
            _draft_assignment("s2", SlotDraftAction.CLEAR),
        ],
        drafting_summary="All done.",
        is_complete=True,
    )
    assert draft.is_complete is True


def test_is_complete_false_consistent():
    draft = SlideContentDraft(
        slide_id="abc", slide_number=1, brief_key_message="msg",
        assignments=[
            _draft_assignment("s1", SlotDraftAction.REPLACE),
            _draft_assignment("s2", SlotDraftAction.NEEDS_INPUT),
        ],
        drafting_summary="Partial.",
        is_complete=False,
    )
    assert draft.is_complete is False


def test_is_complete_true_with_needs_input_rejected():
    with pytest.raises(Exception, match="is_complete=True is inconsistent"):
        SlideContentDraft(
            slide_id="abc", slide_number=1, brief_key_message="msg",
            assignments=[
                _draft_assignment("s1", SlotDraftAction.REPLACE),
                _draft_assignment("s2", SlotDraftAction.NEEDS_INPUT),
            ],
            drafting_summary="Partial.",
            is_complete=True,
        )


def test_is_complete_false_without_needs_input_rejected():
    with pytest.raises(Exception, match="is_complete=False is inconsistent"):
        SlideContentDraft(
            slide_id="abc", slide_number=1, brief_key_message="msg",
            assignments=[
                _draft_assignment("s1", SlotDraftAction.REPLACE),
                _draft_assignment("s2", SlotDraftAction.CLEAR),
            ],
            drafting_summary="All done.",
            is_complete=False,
        )
