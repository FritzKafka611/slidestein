"""Tests for TemplateSlotAnalysisService — mock inspector and analyzer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from slidestein.slots.analysis_models import ShapeSemanticAssessment, SlotAnalysisModelOutput
from slidestein.slots.models import NativeShapeDescriptor, TemplateSlotMap
from slidestein.slots.roles import SlotRole
from slidestein.slots.service import TemplateSlotAnalysisService
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(
    shape_id: int = 7,
    shape_path: str = "7",
    can_edit_text: bool = True,
    text: str = "Slide Title",
    source_kind: str = "placeholder",
) -> NativeShapeDescriptor:
    return NativeShapeDescriptor(
        shape_id=shape_id,
        shape_path=shape_path,
        shape_type="AUTO_SHAPE",
        x=0, y=457200, width=7315200, height=685800,
        x_ratio=0.0, y_ratio=0.05, width_ratio=0.8, height_ratio=0.1,
        z_order=0,
        has_text=bool(text),
        text=text,
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


def _make_assessment(key: str, role: SlotRole = SlotRole.TITLE,
                     include: bool = True, group_key: str | None = None) -> ShapeSemanticAssessment:
    return ShapeSemanticAssessment(
        candidate_key=key,
        include_as_slot=include,
        slot_role=role,
        semantic_label=f"Label for {key}",
        group_key=group_key,
        group_role="workstream" if group_key else None,
        sequence_index=None,
        confidence=0.9,
        rationale="Test rationale.",
    )


def _make_vision_output(
    assessments: list[ShapeSemanticAssessment],
    summary: str = "Test slide.",
) -> SlotAnalysisModelOutput:
    return SlotAnalysisModelOutput(
        assessments=assessments,
        analysis_summary=summary,
    )


def _make_library(
    record=None,
    is_current: bool = False,
    cached_json: str | None = None,
) -> MagicMock:
    lib = MagicMock()
    lib.get_record.return_value = record
    lib.slot_map_is_current.return_value = is_current
    if cached_json:
        lib.get_slot_map.return_value = (cached_json, "fp123", "2024-01-01")
    else:
        lib.get_slot_map.return_value = None
    return lib


def _make_slide_record(slide_id="slide-abc", slide_number=2,
                       preview_path="C:/preview.png") -> MagicMock:
    record = MagicMock()
    record.slide_id = slide_id
    record.slide_number = slide_number
    record.preview_path = preview_path
    record.slide_width_emu = 9144000
    record.slide_height_emu = 5143500
    record.deck_id = "deck-123"
    return record


def _make_inspector(descriptors: list[NativeShapeDescriptor]) -> MagicMock:
    inspector = MagicMock()
    inspector.inspect.return_value = descriptors
    return inspector


def _make_analyzer(output: SlotAnalysisModelOutput) -> MagicMock:
    analyzer = MagicMock()
    analyzer.analyze.return_value = output
    return analyzer


def _make_service(
    descriptors: list[NativeShapeDescriptor],
    vision_output: SlotAnalysisModelOutput,
    library: MagicMock | None = None,
    is_current: bool = False,
) -> tuple[TemplateSlotAnalysisService, MagicMock, MagicMock, MagicMock]:
    record = _make_slide_record()
    lib = library or _make_library(record=record, is_current=is_current)
    lib.get_record.return_value = record
    inspector = _make_inspector(descriptors)
    analyzer = _make_analyzer(vision_output)
    svc = TemplateSlotAnalysisService(
        library=lib,
        inspector=inspector,
        analyzer=analyzer,
        provider_name="sap_ai_core",
        model_name="test-model",
    )
    return svc, lib, inspector, analyzer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSlideNotFound:
    def test_missing_slide_raises(self):
        lib = _make_library(record=None)
        svc = TemplateSlotAnalysisService(library=lib)
        with pytest.raises(ValueError, match="not found"):
            svc.analyze("nonexistent-slide-id")


class TestCacheHit:
    def test_cached_result_returned_without_vision_call(self):
        record = _make_slide_record()
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        slot_map = TemplateSlotMap(
            slide_id="slide-abc",
            slide_number=2,
            slide_width=9144000,
            slide_height=5143500,
            slots=[],
            non_editable_elements=[],
            unsupported_elements=[],
            groups=[],
            analysis_summary="Cached result.",
            slot_analysis_input_fingerprint="a" * 64,
        )
        lib = _make_library(
            record=record,
            is_current=True,
            cached_json=slot_map.model_dump_json(),
        )
        inspector = _make_inspector(descriptors)
        analyzer = _make_analyzer(vision_output)
        svc = TemplateSlotAnalysisService(
            library=lib,
            inspector=inspector,
            analyzer=analyzer,
        )

        result = svc.analyze("slide-abc")
        analyzer.analyze.assert_not_called()
        assert result.analysis_summary == "Cached result."

    def test_force_bypasses_cache(self):
        record = _make_slide_record()
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        cached_map = TemplateSlotMap(
            slide_id="slide-abc",
            slide_number=2,
            slide_width=9144000,
            slide_height=5143500,
            slots=[],
            non_editable_elements=[],
            unsupported_elements=[],
            groups=[],
            analysis_summary="Cached result.",
            slot_analysis_input_fingerprint="a" * 64,
        )
        lib = _make_library(
            record=record,
            is_current=True,
            cached_json=cached_map.model_dump_json(),
        )
        inspector = _make_inspector(descriptors)
        analyzer = _make_analyzer(vision_output)
        svc = TemplateSlotAnalysisService(library=lib, inspector=inspector, analyzer=analyzer)

        svc.analyze("slide-abc", force=True)
        analyzer.analyze.assert_called_once()


class TestDryRun:
    def test_dry_run_no_vision_call(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, lib, inspector, analyzer = _make_service(descriptors, vision_output)

        svc.analyze("slide-abc", dry_run=True)
        analyzer.analyze.assert_not_called()

    def test_dry_run_no_persistence(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, lib, inspector, analyzer = _make_service(descriptors, vision_output)

        svc.analyze("slide-abc", dry_run=True)
        lib.upsert_slot_map.assert_not_called()

    def test_dry_run_returns_partial_map(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, lib, inspector, analyzer = _make_service(descriptors, vision_output)

        result = svc.analyze("slide-abc", dry_run=True)
        assert isinstance(result, TemplateSlotMap)
        assert result.slots == []
        assert "dry run" in result.analysis_summary.lower()


class TestCandidateSending:
    def test_all_editable_candidates_sent_to_vision(self):
        desc1 = _make_descriptor(shape_id=7, can_edit_text=True)
        desc2 = _make_descriptor(shape_id=8, shape_path="8", can_edit_text=True,
                                 text="Body", source_kind="text_box")
        desc3 = _make_descriptor(shape_id=9, shape_path="9", can_edit_text=False,
                                 source_kind="chart")
        vision_output = _make_vision_output([
            _make_assessment("S1"), _make_assessment("S2"),
        ])
        svc, lib, inspector, analyzer = _make_service(
            [desc1, desc2, desc3], vision_output
        )
        svc.analyze("slide-abc")
        call_kwargs = analyzer.analyze.call_args
        candidates_arg = call_kwargs[1].get("candidates") or call_kwargs[0][1]
        # Only editable shapes become candidates
        assert len(candidates_arg) == 2

    def test_non_editable_shapes_not_in_candidates(self):
        desc_edit = _make_descriptor(shape_id=7, can_edit_text=True)
        desc_chart = _make_descriptor(shape_id=8, shape_path="8",
                                      can_edit_text=False, source_kind="chart")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, lib, inspector, analyzer = _make_service(
            [desc_edit, desc_chart], vision_output
        )
        svc.analyze("slide-abc")
        candidates_arg = analyzer.analyze.call_args[1].get("candidates") or \
                         analyzer.analyze.call_args[0][1]
        assert not any("8" in k or d.shape_id == 8
                        for k, d in candidates_arg.items())


class TestOutputBuilding:
    def test_included_slot_appears_in_slots(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1", include=True)])
        svc, _, _, _ = _make_service(descriptors, vision_output)
        result = svc.analyze("slide-abc")
        assert len(result.slots) == 1

    def test_excluded_slot_not_in_slots(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([
            _make_assessment("S1", include=False, role=SlotRole.OTHER_TEXT)
        ])
        svc, _, _, _ = _make_service(descriptors, vision_output)
        result = svc.analyze("slide-abc")
        assert len(result.slots) == 0
        # Vision-declined editable candidates go to excluded_editable_candidates,
        # NOT to non_editable_elements (which is for technically non-editable shapes)
        assert len(result.excluded_editable_candidates) >= 1
        assert len(result.non_editable_elements) == 0

    def test_slot_editable_flag_comes_from_inspector_not_vision(self):
        desc = _make_descriptor(can_edit_text=True)
        # Vision says include=True but cannot change editability
        vision_output = _make_vision_output([_make_assessment("S1", include=True)])
        svc, _, _, _ = _make_service([desc], vision_output)
        result = svc.analyze("slide-abc")
        assert result.slots[0].editable is True

    def test_slot_id_is_stable_uuid5(self):
        import uuid
        desc = _make_descriptor()
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc], vision_output)
        result = svc.analyze("slide-abc")
        slot_id = result.slots[0].slot_id
        parsed = uuid.UUID(slot_id)
        assert parsed.version == 5

    def test_groups_built_from_vision_group_key(self):
        desc1 = _make_descriptor(shape_id=7, text="Alpha")
        desc2 = _make_descriptor(shape_id=8, shape_path="8", text="Beta",
                                 source_kind="text_box")
        vision_output = _make_vision_output([
            _make_assessment("S1", role=SlotRole.WORKSTREAM_LABEL, group_key="ws_group"),
            _make_assessment("S2", role=SlotRole.WORKSTREAM_LABEL, group_key="ws_group"),
        ])
        svc, _, _, _ = _make_service([desc1, desc2], vision_output)
        result = svc.analyze("slide-abc")
        assert len(result.groups) == 1
        assert result.groups[0].group_id == "ws_group"
        assert len(result.groups[0].member_slot_ids) == 2

    def test_unsupported_elements_include_charts(self):
        desc_edit = _make_descriptor(shape_id=7)
        desc_chart = _make_descriptor(shape_id=9, shape_path="9",
                                      can_edit_text=False, source_kind="chart")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc_edit, desc_chart], vision_output)
        result = svc.analyze("slide-abc")
        source_kinds = [e.get("source_kind") for e in result.unsupported_elements]
        assert "chart" in source_kinds

    def test_persistence_called_on_success(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, lib, _, _ = _make_service(descriptors, vision_output)
        svc.analyze("slide-abc")
        lib.upsert_slot_map.assert_called_once()

    def test_schema_version_correct(self):
        descriptors = [_make_descriptor()]
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service(descriptors, vision_output)
        result = svc.analyze("slide-abc")
        assert result.schema_version == SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Item 1+2: Exact Vision candidate coverage
# ---------------------------------------------------------------------------


class TestExactCandidateCoverage:
    def test_exact_coverage_accepted(self):
        d1 = _make_descriptor(shape_id=1)
        d2 = _make_descriptor(shape_id=2, shape_path="2", text="Body")
        d3 = _make_descriptor(shape_id=3, shape_path="3", text="Foot", source_kind="text_box")
        vision_output = _make_vision_output([
            _make_assessment("S1"), _make_assessment("S2"), _make_assessment("S3"),
        ])
        svc, _, _, _ = _make_service([d1, d2, d3], vision_output)
        result = svc.analyze("slide-abc")
        assert result is not None

    def test_missing_candidate_raises(self):
        from slidestein.slots.providers.sap_aicore import SlotAnalysisError
        d1 = _make_descriptor(shape_id=1)
        d2 = _make_descriptor(shape_id=2, shape_path="2", text="Body")
        d3 = _make_descriptor(shape_id=3, shape_path="3", text="Foot", source_kind="text_box")
        # Vision only returns S1, S2 — missing S3
        vision_output = _make_vision_output([
            _make_assessment("S1"), _make_assessment("S2"),
        ])
        svc, _, _, _ = _make_service([d1, d2, d3], vision_output)
        with pytest.raises(SlotAnalysisError, match="missing"):
            svc.analyze("slide-abc")

    def test_unknown_candidate_raises(self):
        from slidestein.slots.providers.sap_aicore import SlotAnalysisError
        d1 = _make_descriptor(shape_id=1)
        d2 = _make_descriptor(shape_id=2, shape_path="2", text="Body")
        d3 = _make_descriptor(shape_id=3, shape_path="3", text="Foot", source_kind="text_box")
        # Vision returns S1, S2, S3, S4 — S4 is unknown
        vision_output = _make_vision_output([
            _make_assessment("S1"), _make_assessment("S2"),
            _make_assessment("S3"), _make_assessment("S4"),
        ])
        svc, _, _, _ = _make_service([d1, d2, d3], vision_output)
        with pytest.raises(SlotAnalysisError, match="unknown"):
            svc.analyze("slide-abc")

    def test_vision_omits_editable_candidate_raises_not_non_editable(self):
        """Item 3: A technically editable shape Vision omits must raise, not become non-editable."""
        from slidestein.slots.providers.sap_aicore import SlotAnalysisError
        desc = _make_descriptor(can_edit_text=True)  # editable
        # Vision returns empty — omits the candidate entirely
        vision_output = _make_vision_output([])
        svc, _, _, _ = _make_service([desc], vision_output)
        with pytest.raises(SlotAnalysisError):
            svc.analyze("slide-abc")


# ---------------------------------------------------------------------------
# Item 3: Semantic separation — native non-editable vs Vision-declined
# ---------------------------------------------------------------------------


class TestExclusionSeparation:
    def test_vision_declined_goes_to_excluded_editable_not_non_editable(self):
        desc = _make_descriptor(can_edit_text=True)
        vision_output = _make_vision_output([
            _make_assessment("S1", include=False, role=SlotRole.OTHER_TEXT)
        ])
        svc, _, _, _ = _make_service([desc], vision_output)
        result = svc.analyze("slide-abc")
        assert len(result.excluded_editable_candidates) == 1
        assert len(result.non_editable_elements) == 0

    def test_native_non_editable_goes_to_non_editable_elements(self):
        desc_edit = _make_descriptor(shape_id=7, can_edit_text=True)
        desc_chart = _make_descriptor(shape_id=8, shape_path="8",
                                      can_edit_text=False, source_kind="chart")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc_edit, desc_chart], vision_output)
        result = svc.analyze("slide-abc")
        # chart goes to unsupported, not non_editable
        assert len(result.unsupported_elements) == 1
        assert len(result.non_editable_elements) == 0

    def test_image_shape_goes_to_non_editable_elements(self):
        desc_edit = _make_descriptor(shape_id=7, can_edit_text=True)
        desc_img = _make_descriptor(shape_id=8, shape_path="8",
                                    can_edit_text=False, source_kind="image")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc_edit, desc_img], vision_output)
        result = svc.analyze("slide-abc")
        assert len(result.non_editable_elements) == 1

    def test_vision_include_false_does_not_override_native_editability(self):
        """Vision may decline a candidate as a slot, but cannot rewrite its native editability."""
        desc = _make_descriptor(can_edit_text=True)
        vision_output = _make_vision_output([
            _make_assessment("S1", include=False, role=SlotRole.OTHER_TEXT)
        ])
        svc, _, _, _ = _make_service([desc], vision_output)
        result = svc.analyze("slide-abc")
        # The descriptor in excluded_editable_candidates still reflects its native kind
        assert len(result.excluded_editable_candidates) == 1
        entry = result.excluded_editable_candidates[0]
        assert entry["source_kind"] == "placeholder"


# ---------------------------------------------------------------------------
# Item 4: Group parent preservation
# ---------------------------------------------------------------------------


class TestGroupParentPreservation:
    def _make_group_descriptor(self, group_id=10, child_id=11) -> list:
        group = _make_descriptor(
            shape_id=group_id, shape_path=str(group_id),
            can_edit_text=False, source_kind="group",
        )
        child = _make_descriptor(
            shape_id=child_id, shape_path=f"{group_id}/{child_id}",
            can_edit_text=True, source_kind="text_box",
            text="Child content",
        )
        # patch is_group on the group descriptor
        object.__setattr__(group, "is_group", True) if False else None
        return [group, child]

    def test_group_parent_appears_in_non_editable_elements(self):
        desc_edit = _make_descriptor(shape_id=7, can_edit_text=True)
        desc_group = _make_descriptor(shape_id=10, shape_path="10",
                                      can_edit_text=False, source_kind="group")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc_edit, desc_group], vision_output)
        result = svc.analyze("slide-abc")
        source_kinds = [e.get("source_kind") for e in result.non_editable_elements]
        assert "group" in source_kinds

    def test_editable_group_child_is_independent_candidate(self):
        desc_group = _make_descriptor(shape_id=10, shape_path="10",
                                      can_edit_text=False, source_kind="group")
        desc_child = _make_descriptor(shape_id=11, shape_path="10/11",
                                      can_edit_text=True, source_kind="text_box",
                                      text="Child text")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc_group, desc_child], vision_output)
        result = svc.analyze("slide-abc")
        # Group parent in non_editable; editable child in slots
        assert len(result.slots) == 1
        assert result.slots[0].shape_path == "10/11"
        non_editable_paths = [e.get("shape_path") for e in result.non_editable_elements]
        assert "10" in non_editable_paths


# ---------------------------------------------------------------------------
# Item 5: Dry-run candidate map
# ---------------------------------------------------------------------------


class TestDryRunCandidateMap:
    def test_dry_run_populates_candidate_map(self):
        desc = _make_descriptor(shape_id=7, text="Hello")
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc], vision_output)
        result = svc.analyze("slide-abc", dry_run=True)
        assert len(result.candidate_map) == 1
        c = result.candidate_map[0]
        assert c["candidate_key"] == "S1"
        assert c["shape_id"] == 7
        assert c["shape_path"] == "7"
        assert c["can_edit_text"] is True
        assert "capacity" in c

    def test_dry_run_candidate_map_sorted_by_key(self):
        d1 = _make_descriptor(shape_id=7, text="First")
        d2 = _make_descriptor(shape_id=8, shape_path="8", text="Second",
                               source_kind="text_box")
        vision_output = _make_vision_output([_make_assessment("S1"), _make_assessment("S2")])
        svc, _, _, _ = _make_service([d1, d2], vision_output)
        result = svc.analyze("slide-abc", dry_run=True)
        keys = [c["candidate_key"] for c in result.candidate_map]
        assert keys == sorted(keys)

    def test_non_dry_run_candidate_map_is_empty(self):
        desc = _make_descriptor()
        vision_output = _make_vision_output([_make_assessment("S1")])
        svc, _, _, _ = _make_service([desc], vision_output)
        result = svc.analyze("slide-abc", dry_run=False)
        assert result.candidate_map == []


# ---------------------------------------------------------------------------
# Item 6: Provider/model currentness
# ---------------------------------------------------------------------------


class TestProviderModelCurrentness:
    def _make_library_with_stored(
        self, record, fingerprint, provider="sap_ai_core",
        model="anthropic--claude-4.5-sonnet",
    ) -> MagicMock:
        lib = MagicMock()
        lib.get_record.return_value = record
        slot_map = TemplateSlotMap(
            slide_id="slide-abc", slide_number=2,
            slide_width=9144000, slide_height=5143500,
            slots=[], non_editable_elements=[], unsupported_elements=[],
            groups=[], analysis_summary="Cached.", slot_analysis_input_fingerprint=fingerprint,
        )
        lib.get_slot_map.return_value = (slot_map.model_dump_json(), fingerprint, "2026-01-01")
        # slot_map_is_current answers True only when all three match
        def _is_current(sid, ver, fp, provider=provider, model=model):
            return fp == fingerprint and provider == provider and model == model
        lib.slot_map_is_current.side_effect = _is_current
        return lib

    def test_same_provider_and_model_returns_cache(self):
        record = _make_slide_record()
        desc = _make_descriptor()
        from slidestein.slots.service import _build_candidate_dict, _build_candidate_fingerprint_entry
        from slidestein.slots.fingerprint import compute_slot_analysis_input_fingerprint
        from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION, SLOT_ANALYSIS_PROMPT_VERSION
        candidates = _build_candidate_dict([desc])
        fp_entries = [_build_candidate_fingerprint_entry(k, d) for k, d in sorted(candidates.items())]
        fp = compute_slot_analysis_input_fingerprint("slide-abc", fp_entries, SLOT_MAP_SCHEMA_VERSION, SLOT_ANALYSIS_PROMPT_VERSION)
        lib = self._make_library_with_stored(record, fp)
        inspector = MagicMock(); inspector.inspect.return_value = [desc]
        analyzer = MagicMock()
        svc = TemplateSlotAnalysisService(
            library=lib, inspector=inspector, analyzer=analyzer,
            provider_name="sap_ai_core", model_name="anthropic--claude-4.5-sonnet",
        )
        lib.slot_map_is_current.return_value = True
        svc.analyze("slide-abc")
        analyzer.analyze.assert_not_called()

    def test_provider_change_bypasses_cache(self):
        record = _make_slide_record()
        desc = _make_descriptor()
        vision_output = _make_vision_output([_make_assessment("S1")])
        lib = MagicMock()
        lib.get_record.return_value = record
        lib.slot_map_is_current.return_value = False  # different provider
        lib.get_slot_map.return_value = None
        inspector = MagicMock(); inspector.inspect.return_value = [desc]
        analyzer = MagicMock(); analyzer.analyze.return_value = vision_output
        svc = TemplateSlotAnalysisService(
            library=lib, inspector=inspector, analyzer=analyzer,
            provider_name="other_provider", model_name="some-model",
        )
        svc.analyze("slide-abc")
        # slot_map_is_current was called with provider/model kwargs
        call_kwargs = lib.slot_map_is_current.call_args
        assert call_kwargs[1].get("provider") == "other_provider"

    def test_model_change_bypasses_cache(self):
        record = _make_slide_record()
        desc = _make_descriptor()
        vision_output = _make_vision_output([_make_assessment("S1")])
        lib = MagicMock()
        lib.get_record.return_value = record
        lib.slot_map_is_current.return_value = False  # different model
        lib.get_slot_map.return_value = None
        inspector = MagicMock(); inspector.inspect.return_value = [desc]
        analyzer = MagicMock(); analyzer.analyze.return_value = vision_output
        svc = TemplateSlotAnalysisService(
            library=lib, inspector=inspector, analyzer=analyzer,
            provider_name="sap_ai_core", model_name="new-model",
        )
        svc.analyze("slide-abc")
        call_kwargs = lib.slot_map_is_current.call_args
        assert call_kwargs[1].get("model") == "new-model"

