"""Tests for normalize_cached_slot_map (M5.2.1)."""

from __future__ import annotations

import pytest

from slidestein.slots.migration import exclusion_changed, normalize_cached_slot_map
from slidestein.slots.models import NativeShapeDescriptor, TemplateSlotMap
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    shape_id: int,
    shape_path: str,
    can_edit_text: bool,
    source_kind: str = "placeholder",
) -> NativeShapeDescriptor:
    return NativeShapeDescriptor(
        shape_id=shape_id,
        shape_path=shape_path,
        shape_type="AUTO_SHAPE",
        x=0, y=0, width=7315200, height=685800,
        x_ratio=0.0, y_ratio=0.0, width_ratio=0.8, height_ratio=0.1,
        z_order=0,
        has_text=True,
        text="text",
        is_placeholder=(source_kind == "placeholder"),
        placeholder_type=15 if source_kind == "placeholder" else None,
        placeholder_idx=0 if source_kind == "placeholder" else None,
        is_group=(source_kind == "group"),
        is_table=(source_kind == "table"),
        has_text_frame=can_edit_text,
        font_size_pt=12.0,
        can_edit_text=can_edit_text,
        source_kind=source_kind,
    )


def _entry(shape_path: str, source_kind: str = "placeholder") -> dict:
    return {
        "shape_id": int(shape_path),
        "shape_path": shape_path,
        "source_kind": source_kind,
        "x_ratio": 0.0, "y_ratio": 0.0,
        "width_ratio": 0.1, "height_ratio": 0.1,
        "text": "",
    }


def _make_slot_map(
    non_editable: list[dict],
    excluded_editable: list[dict],
    unsupported: list[dict] | None = None,
) -> TemplateSlotMap:
    return TemplateSlotMap(
        schema_version=SLOT_MAP_SCHEMA_VERSION,
        slide_id="slide-test",
        slide_number=1,
        slide_width=9144000,
        slide_height=5143500,
        slots=[],
        non_editable_elements=non_editable,
        excluded_editable_candidates=excluded_editable,
        unsupported_elements=unsupported or [],
        groups=[],
        analysis_summary="Test.",
        slot_analysis_input_fingerprint="fp-test",
    )


# Descriptors reused across tests:
# shape A (path "1") = non-editable (image)
# shape B (path "2") = editable (text box, Vision-declined)
# shape C (path "3") = non-editable (image)
_DESC_A = _make_descriptor(1, "1", can_edit_text=False, source_kind="image")
_DESC_B = _make_descriptor(2, "2", can_edit_text=True, source_kind="text_box")
_DESC_C = _make_descriptor(3, "3", can_edit_text=False, source_kind="image")

_DESCRIPTORS = [_DESC_A, _DESC_B, _DESC_C]


# ---------------------------------------------------------------------------
# Case A — legacy mixed map: both A and B in non_editable_elements
# ---------------------------------------------------------------------------


class TestCaseALegacyMixedMap:
    def test_native_entry_stays_in_non_editable(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        ne_paths = {e["shape_path"] for e in result.non_editable_elements}
        assert "1" in ne_paths

    def test_editable_entry_moves_to_excluded_editable(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        exc_paths = {e["shape_path"] for e in result.excluded_editable_candidates}
        assert "2" in exc_paths

    def test_original_non_editable_count_reduced(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert len(result.non_editable_elements) == 1
        assert len(result.excluded_editable_candidates) == 1

    def test_full_partition_matches_expected(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2"), _entry("3")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        ne_paths = {e["shape_path"] for e in result.non_editable_elements}
        exc_paths = {e["shape_path"] for e in result.excluded_editable_candidates}
        assert ne_paths == {"1", "3"}
        assert exc_paths == {"2"}


# ---------------------------------------------------------------------------
# Case B — already correct map: no change expected
# ---------------------------------------------------------------------------


class TestCaseBAlreadyCorrectMap:
    def test_already_correct_non_editable_unchanged(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1")],
            excluded_editable=[_entry("2")],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        ne_paths = {e["shape_path"] for e in result.non_editable_elements}
        exc_paths = {e["shape_path"] for e in result.excluded_editable_candidates}
        assert ne_paths == {"1"}
        assert exc_paths == {"2"}

    def test_exclusion_changed_returns_false_for_correct_map(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1")],
            excluded_editable=[_entry("2")],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert exclusion_changed(slot_map, result) is False

    def test_exclusion_changed_returns_true_for_legacy_map(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert exclusion_changed(slot_map, result) is True


# ---------------------------------------------------------------------------
# Case C — idempotency
# ---------------------------------------------------------------------------


class TestCaseCIdempotency:
    def test_double_normalize_equals_single_on_legacy(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        once = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        twice = normalize_cached_slot_map(once, _DESCRIPTORS)
        assert {e["shape_path"] for e in twice.non_editable_elements} == \
               {e["shape_path"] for e in once.non_editable_elements}
        assert {e["shape_path"] for e in twice.excluded_editable_candidates} == \
               {e["shape_path"] for e in once.excluded_editable_candidates}

    def test_double_normalize_equals_single_on_correct_map(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1")],
            excluded_editable=[_entry("2")],
        )
        once = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        twice = normalize_cached_slot_map(once, _DESCRIPTORS)
        assert {e["shape_path"] for e in twice.non_editable_elements} == \
               {e["shape_path"] for e in once.non_editable_elements}
        assert {e["shape_path"] for e in twice.excluded_editable_candidates} == \
               {e["shape_path"] for e in once.excluded_editable_candidates}

    def test_exclusion_changed_false_after_second_normalize(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        once = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        twice = normalize_cached_slot_map(once, _DESCRIPTORS)
        assert exclusion_changed(once, twice) is False


# ---------------------------------------------------------------------------
# Case D — slot content unchanged
# ---------------------------------------------------------------------------


class TestCaseDSlotsUnchanged:
    def test_fingerprint_preserved(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert result.slot_analysis_input_fingerprint == slot_map.slot_analysis_input_fingerprint

    def test_analysis_summary_preserved(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert result.analysis_summary == slot_map.analysis_summary

    def test_slide_id_preserved(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert result.slide_id == slot_map.slide_id

    def test_schema_version_preserved(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert result.schema_version == slot_map.schema_version

    def test_groups_preserved(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert result.groups == slot_map.groups


# ---------------------------------------------------------------------------
# Case E — unsupported elements unchanged
# ---------------------------------------------------------------------------


class TestCaseEUnsupportedUnchanged:
    def test_unsupported_not_moved(self):
        chart_entry = _entry("99", source_kind="chart")
        desc_chart = _make_descriptor(99, "99", can_edit_text=False, source_kind="chart")
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("2")],
            excluded_editable=[],
            unsupported=[chart_entry],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS + [desc_chart])
        # chart is not moved to either exclusion list
        ne_paths = {e["shape_path"] for e in result.non_editable_elements}
        exc_paths = {e["shape_path"] for e in result.excluded_editable_candidates}
        assert "99" not in ne_paths
        assert "99" not in exc_paths
        # unsupported_elements unchanged
        assert result.unsupported_elements == slot_map.unsupported_elements

    def test_unsupported_count_unchanged(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1")],
            excluded_editable=[],
            unsupported=[_entry("99", source_kind="chart"), _entry("98", source_kind="table")],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert len(result.unsupported_elements) == 2


# ---------------------------------------------------------------------------
# Case F — empty exclusions are legitimate (all native)
# ---------------------------------------------------------------------------


class TestCaseFEmptyExclusionsLegitimate:
    def test_all_native_excluded_editable_stays_empty(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("3")],  # both native non-editable
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        # shape "2" is editable but not in the exclusion lists → stays out
        assert result.excluded_editable_candidates == []

    def test_all_native_non_editable_count_unchanged(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("3")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert len(result.non_editable_elements) == 2

    def test_exclusion_changed_false_for_all_native(self):
        slot_map = _make_slot_map(
            non_editable=[_entry("1"), _entry("3")],
            excluded_editable=[],
        )
        result = normalize_cached_slot_map(slot_map, _DESCRIPTORS)
        assert exclusion_changed(slot_map, result) is False
