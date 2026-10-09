"""Tests for SlideLibrary slot map persistence (M5.2 slide_slot_maps table)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slidestein.library.store import SlideLibrary
from slidestein.slots.models import TemplateSlotMap
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def library(tmp_path: Path) -> SlideLibrary:
    db = tmp_path / "test.db"
    with SlideLibrary(db, str(tmp_path / "lancedb")) as lib:
        yield lib


def _make_slot_map_json(slide_id: str = "slide-abc") -> str:
    return TemplateSlotMap(
        slide_id=slide_id,
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
        slots=[],
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Test.",
        slot_analysis_input_fingerprint="fp-test-123",
    ).model_dump_json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpsertSlotMap:
    def test_insert_succeeds(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp123",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        result = library.get_slot_map("slide-abc", SLOT_MAP_SCHEMA_VERSION)
        assert result is not None

    def test_upsert_replaces_existing(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp-old",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp-new",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        result = library.get_slot_map("slide-abc", SLOT_MAP_SCHEMA_VERSION)
        assert result[1] == "fp-new"


class TestGetSlotMap:
    def test_get_returns_json_fingerprint_and_timestamp(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp123",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        result = library.get_slot_map("slide-abc", SLOT_MAP_SCHEMA_VERSION)
        assert result is not None
        slot_map_json, fp, analyzed_at = result
        assert fp == "fp123"
        assert json.loads(slot_map_json)["slide_id"] == "slide-abc"

    def test_get_missing_returns_none(self, library):
        result = library.get_slot_map("nonexistent", SLOT_MAP_SCHEMA_VERSION)
        assert result is None

    def test_get_wrong_version_returns_none(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp123",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        result = library.get_slot_map("slide-abc", "99.0")
        assert result is None

    def test_json_round_trips_through_model(self, library):
        original = _make_slot_map_json()
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp123",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=original,
        )
        slot_map_json, _, _ = library.get_slot_map("slide-abc", SLOT_MAP_SCHEMA_VERSION)
        loaded = TemplateSlotMap.model_validate_json(slot_map_json)
        assert loaded.slide_id == "slide-abc"


class TestSlotMapIsCurrent:
    def test_matching_fingerprint_returns_true(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp-exact",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        assert library.slot_map_is_current("slide-abc", SLOT_MAP_SCHEMA_VERSION, "fp-exact") is True

    def test_different_fingerprint_returns_false(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp-old",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="test-model",
            slot_map_json=_make_slot_map_json(),
        )
        assert library.slot_map_is_current("slide-abc", SLOT_MAP_SCHEMA_VERSION, "fp-new") is False

    def test_missing_entry_returns_false(self, library):
        assert library.slot_map_is_current("nonexistent", SLOT_MAP_SCHEMA_VERSION, "fp") is False

    def test_same_provider_and_model_returns_true(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc", version=SLOT_MAP_SCHEMA_VERSION, fingerprint="fp-exact",
            prompt_version="1.0", provider="sap_ai_core", model="anthropic--claude-4.5-sonnet",
            slot_map_json=_make_slot_map_json(),
        )
        assert library.slot_map_is_current(
            "slide-abc", SLOT_MAP_SCHEMA_VERSION, "fp-exact",
            provider="sap_ai_core", model="anthropic--claude-4.5-sonnet",
        ) is True

    def test_provider_change_returns_false(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc", version=SLOT_MAP_SCHEMA_VERSION, fingerprint="fp-exact",
            prompt_version="1.0", provider="sap_ai_core", model="anthropic--claude-4.5-sonnet",
            slot_map_json=_make_slot_map_json(),
        )
        assert library.slot_map_is_current(
            "slide-abc", SLOT_MAP_SCHEMA_VERSION, "fp-exact",
            provider="other_provider", model="anthropic--claude-4.5-sonnet",
        ) is False

    def test_model_change_returns_false(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc", version=SLOT_MAP_SCHEMA_VERSION, fingerprint="fp-exact",
            prompt_version="1.0", provider="sap_ai_core", model="anthropic--claude-4.5-sonnet",
            slot_map_json=_make_slot_map_json(),
        )
        assert library.slot_map_is_current(
            "slide-abc", SLOT_MAP_SCHEMA_VERSION, "fp-exact",
            provider="sap_ai_core", model="new-model",
        ) is False

    def test_no_provider_model_args_still_matches_fingerprint_only(self, library):
        """Omitting provider/model args keeps backward-compatible behaviour."""
        library.upsert_slot_map(
            slide_id="slide-abc", version=SLOT_MAP_SCHEMA_VERSION, fingerprint="fp-exact",
            prompt_version="1.0", provider="sap_ai_core", model="anthropic--claude-4.5-sonnet",
            slot_map_json=_make_slot_map_json(),
        )
        assert library.slot_map_is_current(
            "slide-abc", SLOT_MAP_SCHEMA_VERSION, "fp-exact",
        ) is True


class TestListSlotMaps:
    def test_list_all_returns_entries(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp1",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="m1",
            slot_map_json=_make_slot_map_json("slide-abc"),
        )
        library.upsert_slot_map(
            slide_id="slide-def",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp2",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="m1",
            slot_map_json=_make_slot_map_json("slide-def"),
        )
        rows = library.list_slot_maps()
        assert len(rows) == 2

    def test_list_by_version_filters(self, library):
        library.upsert_slot_map(
            slide_id="slide-abc",
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint="fp1",
            prompt_version="1.0",
            provider="sap_ai_core",
            model="m1",
            slot_map_json=_make_slot_map_json(),
        )
        rows = library.list_slot_maps(version="99.0")
        assert len(rows) == 0

    def test_list_empty_when_no_maps(self, library):
        rows = library.list_slot_maps()
        assert rows == []
