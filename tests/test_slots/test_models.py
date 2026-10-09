"""Tests for SlotRole enum, NativeShapeDescriptor, SlotCapacity, TemplateSlot,
SlotGroup, and TemplateSlotMap domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.slots.models import (
    NativeShapeDescriptor,
    SlotCapacity,
    SlotGroup,
    TemplateSlot,
    TemplateSlotMap,
)
from slidestein.slots.roles import SlotRole
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(**kwargs) -> NativeShapeDescriptor:
    defaults = dict(
        shape_id=7,
        shape_path="7",
        shape_type="AUTO_SHAPE",
        x=914400, y=457200, width=7315200, height=685800,
        x_ratio=0.1, y_ratio=0.05, width_ratio=0.8, height_ratio=0.1,
        z_order=0,
        has_text=True,
        text="Slide Title",
        is_placeholder=True,
        placeholder_type=1,
        placeholder_idx=0,
        is_group=False,
        is_table=False,
        has_text_frame=True,
        font_size_pt=28.0,
        can_edit_text=True,
        source_kind="placeholder",
    )
    defaults.update(kwargs)
    return NativeShapeDescriptor(**defaults)


def _make_capacity(**kwargs) -> SlotCapacity:
    defaults = dict(
        max_characters_estimate=300,
        max_lines_estimate=5,
        current_character_count=11,
        current_line_count=1,
        relative_capacity="large",
    )
    defaults.update(kwargs)
    return SlotCapacity(**defaults)


def _make_slot(**kwargs) -> TemplateSlot:
    defaults = dict(
        slot_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        shape_id=7,
        shape_path="7",
        slot_role=SlotRole.TITLE,
        semantic_label="Slide title",
        editable=True,
        confidence=0.95,
        current_text="Slide Title",
        geometry={"x": 914400, "y": 457200, "width": 7315200, "height": 685800,
                  "x_ratio": 0.1, "y_ratio": 0.05, "width_ratio": 0.8, "height_ratio": 0.1},
        capacity=_make_capacity(),
        group_id=None,
        sequence_index=None,
        notes="Large title shape at top.",
    )
    defaults.update(kwargs)
    return TemplateSlot(**defaults)


def _make_slot_map(**kwargs) -> TemplateSlotMap:
    defaults = dict(
        slide_id="abc123",
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
        slots=[_make_slot()],
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Title slide with one content placeholder.",
        slot_analysis_input_fingerprint="a" * 64,
    )
    defaults.update(kwargs)
    return TemplateSlotMap(**defaults)


# ---------------------------------------------------------------------------
# SlotRole
# ---------------------------------------------------------------------------

class TestSlotRole:
    def test_all_values_are_strings(self):
        for role in SlotRole:
            assert isinstance(role.value, str)

    def test_title_value(self):
        assert SlotRole.TITLE.value == "title"

    def test_workstream_label_value(self):
        assert SlotRole.WORKSTREAM_LABEL.value == "workstream_label"

    def test_has_at_least_15_roles(self):
        assert len(list(SlotRole)) >= 15


# ---------------------------------------------------------------------------
# NativeShapeDescriptor
# ---------------------------------------------------------------------------

class TestNativeShapeDescriptor:
    def test_valid_descriptor_accepted(self):
        d = _make_descriptor()
        assert d.shape_id == 7
        assert d.source_kind == "placeholder"
        assert d.can_edit_text is True

    def test_group_descriptor_accepted(self):
        d = _make_descriptor(
            is_group=True, source_kind="group", can_edit_text=False,
            has_text_frame=False, has_text=False, text="",
            is_placeholder=False, placeholder_type=None, placeholder_idx=None,
        )
        assert d.is_group is True
        assert d.can_edit_text is False

    def test_table_descriptor_accepted(self):
        d = _make_descriptor(
            is_table=True, source_kind="table", can_edit_text=False,
            table_rows=3, table_columns=4, is_placeholder=False,
            placeholder_type=None, placeholder_idx=None,
        )
        assert d.table_rows == 3
        assert d.table_columns == 4

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            _make_descriptor(hallucinated_extra_field="oops")  # type: ignore[call-arg]

    def test_parent_shape_path_for_group_child(self):
        d = _make_descriptor(shape_path="10/7", parent_shape_path="10")
        assert d.parent_shape_path == "10"

    def test_no_parent_for_top_level(self):
        d = _make_descriptor()
        assert d.parent_shape_path is None

    def test_font_size_optional(self):
        d = _make_descriptor(font_size_pt=None)
        assert d.font_size_pt is None

    def test_z_order_stored(self):
        d = _make_descriptor(z_order=3)
        assert d.z_order == 3


# ---------------------------------------------------------------------------
# SlotCapacity
# ---------------------------------------------------------------------------

class TestSlotCapacity:
    def test_valid_capacity_accepted(self):
        cap = _make_capacity()
        assert cap.max_characters_estimate == 300
        assert cap.relative_capacity == "large"

    def test_small_capacity(self):
        cap = _make_capacity(max_characters_estimate=30, relative_capacity="small")
        assert cap.relative_capacity == "small"

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            SlotCapacity(
                max_characters_estimate=100,
                max_lines_estimate=3,
                current_character_count=5,
                current_line_count=1,
                relative_capacity="large",
                extra_field="bad",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# TemplateSlot
# ---------------------------------------------------------------------------

class TestTemplateSlot:
    def test_valid_slot_accepted(self):
        slot = _make_slot()
        assert slot.slot_role == SlotRole.TITLE
        assert slot.editable is True

    def test_non_editable_slot_accepted(self):
        slot = _make_slot(editable=False, slot_role=SlotRole.LABEL)
        assert slot.editable is False

    def test_group_id_optional(self):
        slot = _make_slot()
        assert slot.group_id is None

    def test_sequence_index_optional(self):
        slot = _make_slot()
        assert slot.sequence_index is None

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            _make_slot(phantom_field="bad")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# SlotGroup
# ---------------------------------------------------------------------------

class TestSlotGroup:
    def test_valid_group_accepted(self):
        g = SlotGroup(
            group_id="workstream_1",
            group_role="workstream",
            member_slot_ids=["uuid-1", "uuid-2"],
            sequence_index=0,
            semantic_label="Workstream group",
        )
        assert len(g.member_slot_ids) == 2

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            SlotGroup(
                group_id="g1",
                group_role="row",
                member_slot_ids=[],
                semantic_label="test",
                phantom="bad",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# TemplateSlotMap
# ---------------------------------------------------------------------------

class TestTemplateSlotMap:
    def test_valid_map_accepted(self):
        m = _make_slot_map()
        assert m.schema_version == SLOT_MAP_SCHEMA_VERSION
        assert m.slide_id == "abc123"

    def test_schema_version_defaults_to_constant(self):
        m = _make_slot_map()
        assert m.schema_version == SLOT_MAP_SCHEMA_VERSION

    def test_duplicate_slot_id_rejected(self):
        slot_a = _make_slot(slot_id="same-id")
        slot_b = _make_slot(slot_id="same-id", shape_path="8", shape_id=8)
        with pytest.raises(ValidationError):
            _make_slot_map(slots=[slot_a, slot_b])

    def test_unique_slot_ids_accepted(self):
        slot_a = _make_slot(slot_id="id-a")
        slot_b = _make_slot(slot_id="id-b", shape_path="8", shape_id=8)
        m = _make_slot_map(slots=[slot_a, slot_b])
        assert len(m.slots) == 2

    def test_empty_slots_accepted(self):
        m = _make_slot_map(slots=[])
        assert m.slots == []

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            _make_slot_map(phantom="bad")  # type: ignore[call-arg]

    def test_deck_id_optional(self):
        m = _make_slot_map()
        assert m.deck_id is None

    def test_json_round_trip(self):
        m = _make_slot_map()
        serialised = m.model_dump_json()
        m2 = TemplateSlotMap.model_validate_json(serialised)
        assert m2.slide_id == m.slide_id
        assert len(m2.slots) == len(m.slots)
