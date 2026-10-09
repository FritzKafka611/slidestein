"""Tests for SlideContentDraftService — no real LLM calls."""

from __future__ import annotations

import json
from typing import Optional
from unittest.mock import MagicMock

import pytest

from slidestein.drafting.analysis_models import (
    ContentDraftModelOutput,
    SlotContentGap,
    SlotReplacement,
)
from slidestein.drafting.models import SlotDraftAction, SlideContentDraft
from slidestein.drafting.providers.sap_aicore import ContentDraftGenerationError
from slidestein.drafting.service import (
    SlideContentDraftService,
    build_groups_context,
    build_slot_key_mapping,
    build_slot_specs,
)
from slidestein.slots.models import SlotCapacity, SlotGroup, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _capacity(max_chars: int = 120, max_lines: int = 2) -> SlotCapacity:
    return SlotCapacity(
        max_characters_estimate=max_chars,
        max_lines_estimate=max_lines,
        current_character_count=10,
        current_line_count=1,
        relative_capacity="medium",
    )


def _slot(
    slot_id: str,
    *,
    y: float = 0.1,
    x: float = 0.1,
    role: SlotRole = SlotRole.TITLE,
    label: str = "Title",
    text: str = "Example",
    seq: Optional[int] = None,
    group: Optional[str] = None,
    max_chars: int = 120,
    max_lines: int = 2,
) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=hash(slot_id) % 1000,
        shape_path=f"Slide/{slot_id}",
        slot_role=role,
        semantic_label=label,
        editable=True,
        confidence=0.9,
        current_text=text,
        geometry={"x_ratio": x, "y_ratio": y, "width_ratio": 0.5, "height_ratio": 0.1},
        capacity=_capacity(max_chars, max_lines),
        group_id=group,
        sequence_index=seq,
    )


def _slot_map(slots: list[TemplateSlot], groups: list[SlotGroup] | None = None) -> TemplateSlotMap:
    return TemplateSlotMap(
        slide_id="slide-abc",
        slide_number=3,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots,
        non_editable_elements=[],
        excluded_editable_candidates=[],
        unsupported_elements=[],
        groups=groups or [],
        analysis_summary="Test slot map.",
        slot_analysis_input_fingerprint="fp1",
    )


class _FakeBrief:
    original_request = "Show deal status."
    key_message = "Deal is on track."
    slide_function = type("", (), {"value": "content"})()
    primary_communication_job = None
    preferred_visual_archetypes = []
    required_content_elements = []


def _brief():
    return _FakeBrief()


def _model_output_all_replace(keys: list[str]) -> ContentDraftModelOutput:
    return ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key=k, text=f"Draft for {k}") for k in keys],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="All replaced.",
    )


def _make_generator(output: ContentDraftModelOutput):
    gen = MagicMock()
    gen.generate.return_value = output
    return gen


# ---------------------------------------------------------------------------
# build_slot_key_mapping
# ---------------------------------------------------------------------------


def test_key_mapping_stable_sort():
    s1 = _slot("s1", y=0.5, x=0.1)
    s2 = _slot("s2", y=0.1, x=0.5)
    s3 = _slot("s3", y=0.1, x=0.1)
    mapping = build_slot_key_mapping([s1, s2, s3])
    # sorted by y first: s3(y=0.1,x=0.1), s2(y=0.1,x=0.5), s1(y=0.5)
    keys = list(mapping.keys())
    assert keys == ["K1", "K2", "K3"]
    assert mapping["K1"].slot_id == "s3"
    assert mapping["K2"].slot_id == "s2"
    assert mapping["K3"].slot_id == "s1"


def test_key_mapping_sequence_index_tiebreaker():
    s1 = _slot("s1", y=0.1, x=0.1, seq=2)
    s2 = _slot("s2", y=0.1, x=0.1, seq=1)
    mapping = build_slot_key_mapping([s1, s2])
    assert mapping["K1"].slot_id == "s2"  # seq=1 comes first


def test_key_mapping_none_sequence_sorts_last():
    s1 = _slot("s1", y=0.1, x=0.1, seq=None)
    s2 = _slot("s2", y=0.1, x=0.1, seq=1)
    mapping = build_slot_key_mapping([s1, s2])
    assert mapping["K1"].slot_id == "s2"
    assert mapping["K2"].slot_id == "s1"


def test_key_mapping_deterministic():
    slots = [_slot(f"s{i}", y=i * 0.1) for i in range(5)]
    m1 = build_slot_key_mapping(slots)
    m2 = build_slot_key_mapping(list(reversed(slots)))
    assert list(m1.keys()) == list(m2.keys())
    assert [s.slot_id for s in m1.values()] == [s.slot_id for s in m2.values()]


# ---------------------------------------------------------------------------
# build_slot_specs
# ---------------------------------------------------------------------------


def test_slot_specs_have_required_fields():
    mapping = {"K1": _slot("s1", text="Example")}
    specs = build_slot_specs(mapping)
    assert len(specs) == 1
    s = specs[0]
    assert s["key"] == "K1"
    assert s["role"] == SlotRole.TITLE.value
    assert "hard_max_characters" in s
    assert "preferred_target_characters" in s
    assert "hard_max_lines" in s
    assert "example" in s


def test_slot_specs_preferred_target_is_85_percent():
    mapping = {"K1": _slot("s1", max_chars=100)}
    specs = build_slot_specs(mapping)
    assert specs[0]["preferred_target_characters"] == 85


def test_slot_specs_preferred_target_hard_max_13():
    mapping = {"K1": _slot("s1", max_chars=13)}
    specs = build_slot_specs(mapping)
    assert specs[0]["preferred_target_characters"] == 11


def test_slot_specs_example_truncated_at_80():
    long_text = "A" * 200
    mapping = {"K1": _slot("s1", text=long_text)}
    specs = build_slot_specs(mapping)
    assert len(specs[0]["example"]) == 80


# ---------------------------------------------------------------------------
# build_groups_context
# ---------------------------------------------------------------------------


def test_groups_context_maps_slot_ids_to_keys():
    s1 = _slot("s1", group="g1")
    s2 = _slot("s2", group="g1")
    mapping = {"K1": s1, "K2": s2}
    group = SlotGroup(
        group_id="g1",
        group_role="workstream_labels",
        member_slot_ids=["s1", "s2"],
        semantic_label="Workstreams",
    )
    ctx = build_groups_context([group], mapping)
    assert len(ctx) == 1
    assert set(ctx[0]["member_keys"]) == {"K1", "K2"}


def test_groups_context_empty_when_no_members_in_map():
    mapping = {"K1": _slot("s1")}
    group = SlotGroup(
        group_id="g1",
        group_role="labels",
        member_slot_ids=["s99"],  # not in mapping
        semantic_label="X",
    )
    ctx = build_groups_context([group], mapping)
    assert ctx == []


# ---------------------------------------------------------------------------
# Service.draft() — generator called once
# ---------------------------------------------------------------------------


def test_generator_called_exactly_once():
    slots = [_slot("s1")]
    gen = _make_generator(_model_output_all_replace(["K1"]))
    service = SlideContentDraftService(generator=gen)
    service.draft(brief=_brief(), slot_map=_slot_map(slots))
    gen.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Service.draft() — is_complete derivation
# ---------------------------------------------------------------------------


def test_is_complete_true_when_no_needs_input():
    slots = [_slot("s1"), _slot("s2")]
    out = ContentDraftModelOutput(
        replacements=[
            SlotReplacement(slot_key="K1", text="Title text"),
            SlotReplacement(slot_key="K2", text="Subtitle"),
        ],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="Done.",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.is_complete is True


def test_is_complete_false_when_needs_input():
    slots = [_slot("s1"), _slot("s2")]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="Title")],
        clear_slots=[],
        needs_input=[SlotContentGap(slot_key="K2", missing_information="Need data.")],
        open_questions=[],
        drafting_summary="Partial.",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.is_complete is False


# ---------------------------------------------------------------------------
# Service.draft() — exact slot coverage validation
# ---------------------------------------------------------------------------


def test_missing_slot_raises():
    slots = [_slot("s1"), _slot("s2")]
    out = _model_output_all_replace(["K1"])  # K2 missing
    service = SlideContentDraftService(_make_generator(out))
    with pytest.raises(ContentDraftGenerationError, match="missing"):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))


def test_unknown_slot_raises():
    slots = [_slot("s1")]
    out = _model_output_all_replace(["K1", "K99"])  # K99 not in map
    service = SlideContentDraftService(_make_generator(out))
    with pytest.raises(ContentDraftGenerationError, match="unknown"):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))


# ---------------------------------------------------------------------------
# Service.draft() — capacity validation
# ---------------------------------------------------------------------------


def test_capacity_exceeded_raises():
    slots = [_slot("s1", max_chars=10)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="This text is way too long.")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    with pytest.raises(ContentDraftGenerationError, match="capacity"):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))


def test_line_limit_exceeded_raises():
    slots = [_slot("s1", max_lines=1)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="Line one\nLine two")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    with pytest.raises(ContentDraftGenerationError, match="line"):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))


def test_capacity_within_limit_ok():
    slots = [_slot("s1", max_chars=100)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="Short text.")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.assignments[0].action == SlotDraftAction.REPLACE


# ---------------------------------------------------------------------------
# Service.draft() — output fields
# ---------------------------------------------------------------------------


def test_draft_contains_slide_metadata():
    slots = [_slot("s1")]
    out = _model_output_all_replace(["K1"])
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.slide_id == "slide-abc"
    assert draft.slide_number == 3
    assert draft.brief_key_message == "Deal is on track."


def test_draft_open_questions_forwarded():
    slots = [_slot("s1")]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="Hi")],
        clear_slots=[],
        needs_input=[],
        open_questions=["Who approves?"],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert "Who approves?" in draft.open_questions


def test_clear_assignment_built():
    slots = [_slot("s1"), _slot("s2")]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="Title")],
        clear_slots=["K2"],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    actions = {a.slot_id: a.action for a in draft.assignments}
    # K2 maps to whichever slot has that key — find by position
    clear_assignments = [a for a in draft.assignments if a.action == SlotDraftAction.CLEAR]
    assert len(clear_assignments) == 1


def test_needs_input_assignment_built():
    slots = [_slot("s1")]
    out = ContentDraftModelOutput(
        replacements=[],
        clear_slots=[],
        needs_input=[SlotContentGap(slot_key="K1", missing_information="Revenue.")],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.assignments[0].action == SlotDraftAction.NEEDS_INPUT
    assert draft.assignments[0].missing_information == "Revenue."


# ---------------------------------------------------------------------------
# Service.draft() — no retry (generator called once even on failure)
# ---------------------------------------------------------------------------


def test_no_retry_on_coverage_failure():
    slots = [_slot("s1")]
    gen = MagicMock()
    gen.generate.return_value = _model_output_all_replace([])  # empty — missing K1
    service = SlideContentDraftService(gen)
    with pytest.raises(ContentDraftGenerationError):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert gen.generate.call_count == 1


# ---------------------------------------------------------------------------
# Service.draft() — line limit enforcement (max_lines=0 means unlimited)
# ---------------------------------------------------------------------------


def test_line_limit_max_lines_1_single_line_accepted():
    slots = [_slot("s1", max_lines=1)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="line one")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.assignments[0].action == SlotDraftAction.REPLACE


def test_line_limit_max_lines_1_two_lines_rejected():
    slots = [_slot("s1", max_lines=1)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="line one\nline two")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    with pytest.raises(ContentDraftGenerationError, match="line"):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))


def test_line_limit_max_lines_2_two_lines_accepted():
    slots = [_slot("s1", max_lines=2)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="line one\nline two")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    draft = service.draft(brief=_brief(), slot_map=_slot_map(slots))
    assert draft.assignments[0].action == SlotDraftAction.REPLACE


def test_line_limit_max_lines_2_three_lines_rejected():
    slots = [_slot("s1", max_lines=2)]
    out = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="line one\nline two\nline three")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="d",
    )
    service = SlideContentDraftService(_make_generator(out))
    with pytest.raises(ContentDraftGenerationError, match="line"):
        service.draft(brief=_brief(), slot_map=_slot_map(slots))
