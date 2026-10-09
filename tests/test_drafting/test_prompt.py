"""Tests for draft prompt builder — pure Python, no SDK dependencies."""

from __future__ import annotations

import pytest

from slidestein.drafting.prompt import (
    _ROLE_GUIDANCE,
    _SYSTEM_PROMPT,
    build_brief_summary,
    build_draft_prompt,
    preferred_target_characters,
)
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Helpers — minimal brief-like objects
# ---------------------------------------------------------------------------


class _FakeJob:
    def __init__(self, v):
        self.value = v


class _FakeArch:
    def __init__(self, v):
        self.value = v


class _FakeFn:
    def __init__(self, v):
        self.value = v


class _FakeBrief:
    def __init__(self):
        self.original_request = "Show the project governance structure."
        self.key_message = "The deal team is on track."
        self.slide_function = _FakeFn("content")
        self.primary_communication_job = _FakeJob("show_process")
        self.preferred_visual_archetypes = [_FakeArch("roadmap")]
        self.required_content_elements = ["Milestones", "Owners"]


class _FakeBriefMinimal:
    def __init__(self):
        self.original_request = "Show cover slide."
        self.key_message = "Minimal brief."
        self.slide_function = _FakeFn("cover")
        self.primary_communication_job = None
        self.preferred_visual_archetypes = []
        self.required_content_elements = []


def _slot_specs():
    return [
        {
            "key": "K1",
            "role": "title",
            "label": "Slide title",
            "group": "",
            "sequence": None,
            "hard_max_characters": 120,
            "preferred_target_characters": 102,
            "hard_max_lines": 2,
            "example": "Current Example Text",
        },
        {
            "key": "K2",
            "role": "workstream_label",
            "label": "Workstream name",
            "group": "ws_group",
            "sequence": 1,
            "hard_max_characters": 30,
            "preferred_target_characters": 25,
            "hard_max_lines": 1,
            "example": "Data & Technology",
        },
    ]


def _groups():
    return [
        {
            "group_id": "ws_group",
            "group_role": "workstream_labels",
            "semantic_label": "Workstream names",
            "member_keys": ["K2"],
        }
    ]


# ---------------------------------------------------------------------------
# System prompt invariants
# ---------------------------------------------------------------------------


def test_system_prompt_template_not_factual():
    assert "STRUCTURAL EXAMPLE" in _SYSTEM_PROMPT
    assert "NOT FACTUAL" in _SYSTEM_PROMPT


def test_system_prompt_needs_input_for_missing_facts_only():
    assert "needs_input" in _SYSTEM_PROMPT
    assert "NEVER" in _SYSTEM_PROMPT
    assert "wording" in _SYSTEM_PROMPT.lower() or "too long" in _SYSTEM_PROMPT.lower()


def test_system_prompt_capacity_is_application_enforced():
    assert "REJECTED by the application" in _SYSTEM_PROMPT or "rejected" in _SYSTEM_PROMPT.lower()


def test_system_prompt_compress_rephrase_guidance():
    # Must instruct to compress/shorten/rephrase rather than use needs_input
    assert "compress" in _SYSTEM_PROMPT.lower()
    assert "rephrase" in _SYSTEM_PROMPT.lower()


def test_system_prompt_no_invention_instruction():
    assert "NOT invent" in _SYSTEM_PROMPT or "Do NOT invent" in _SYSTEM_PROMPT


def test_system_prompt_json_only_instruction():
    assert "ONLY valid JSON" in _SYSTEM_PROMPT or "only valid JSON" in _SYSTEM_PROMPT.lower()


def test_system_prompt_no_fences():
    assert "fences" in _SYSTEM_PROMPT or "backticks" in _SYSTEM_PROMPT


def test_system_prompt_injection_guard():
    assert "injection" in _SYSTEM_PROMPT.lower() or "untrusted" in _SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# Role guidance
# ---------------------------------------------------------------------------


def test_role_guidance_all_roles_present():
    for role in SlotRole:
        assert role.value in _ROLE_GUIDANCE, f"Missing role in _ROLE_GUIDANCE: {role.value}"


# ---------------------------------------------------------------------------
# preferred_target_characters — deterministic calculation
# ---------------------------------------------------------------------------


def test_preferred_target_hard_max_100():
    assert preferred_target_characters(100) == 85


def test_preferred_target_hard_max_13():
    assert preferred_target_characters(13) == 11


def test_preferred_target_hard_max_1():
    # floor(1 * 0.85) = 0 → clamped to minimum 1
    assert preferred_target_characters(1) == 1


def test_preferred_target_hard_max_10():
    assert preferred_target_characters(10) == 8


def test_preferred_target_hard_max_120():
    assert preferred_target_characters(120) == 102


def test_preferred_target_hard_max_0():
    # Edge case: 0-char slot → minimum 1
    assert preferred_target_characters(0) == 1


# ---------------------------------------------------------------------------
# build_draft_prompt — structural guarantees
# ---------------------------------------------------------------------------


def test_prompt_contains_slot_keys():
    prompt = build_draft_prompt(
        brief_summary="Key message: x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=_groups(),
    )
    assert "K1" in prompt
    assert "K2" in prompt


def test_prompt_slot_count_in_header():
    prompt = build_draft_prompt(
        brief_summary="Key message: x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "2 slots" in prompt


def test_prompt_hard_maximum_label():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "HARD MAXIMUM" in prompt


def test_prompt_preferred_target_label():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "preferred target" in prompt


def test_prompt_hard_max_value_present():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "120 characters" in prompt
    assert "30 characters" in prompt


def test_prompt_preferred_target_value_present():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    # K1 preferred = 102, K2 preferred = 25
    assert "<=102 characters" in prompt or "102 characters" in prompt
    assert "<=25 characters" in prompt or "25 characters" in prompt


def test_prompt_example_labeled_structural_only():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "STRUCTURAL EXAMPLE ONLY" in prompt


def test_prompt_source_material_block_when_provided():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material="Revenue grew 15%.",
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "Revenue grew 15%" in prompt
    assert "FACTUAL SOURCE MATERIAL" in prompt


def test_prompt_no_source_material_when_none():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "none provided" in prompt.lower() or "(none" in prompt.lower()


def test_prompt_group_context_shown():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=_groups(),
    )
    assert "ws_group" in prompt
    assert "K2" in prompt


def test_prompt_no_group_section_when_empty():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "GROUP CONTEXT" not in prompt


def test_prompt_every_slot_action_listed():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "replace" in prompt.lower()
    assert "clear" in prompt.lower()
    assert "needs_input" in prompt


def test_prompt_needs_input_factual_gap_only():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    # Must state needs_input is for missing factual information only
    prompt_lower = prompt.lower()
    assert "factual" in prompt_lower
    assert "absent" in prompt_lower or "missing" in prompt_lower


def test_prompt_capacity_alone_must_not_cause_needs_input():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    # Must explicitly state NOT to use needs_input for wording length
    assert "NEVER" in prompt
    assert "too long" in prompt.lower() or "wording" in prompt.lower()


def test_prompt_compress_rephrase_in_instructions():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    prompt_lower = prompt.lower()
    assert "compress" in prompt_lower
    assert "rephrase" in prompt_lower


def test_prompt_clear_unused_template_structure():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    prompt_lower = prompt.lower()
    # Must explain clear = structural unit not applicable
    assert "structural" in prompt_lower
    assert "not applicable" in prompt_lower or "does not apply" in prompt_lower


def test_prompt_absent_structural_unit_dependents_cleared():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    # Group coherence: clearing a label → clear dependent slots too
    assert "dependent" in prompt.lower() or "dependent content" in prompt.lower()


def test_prompt_do_not_invent_facts():
    # The no-invention rule is stated in the system prompt
    assert "Do NOT invent" in _SYSTEM_PROMPT or "do not invent" in _SYSTEM_PROMPT.lower()


def test_prompt_application_enforced_rejection_warning():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "REJECTED" in prompt or "rejected" in prompt.lower()


def test_prompt_output_schema_present():
    prompt = build_draft_prompt(
        brief_summary="x",
        source_material=None,
        slot_specs=_slot_specs(),
        groups_context=[],
    )
    assert "replacements" in prompt
    assert "clear_slots" in prompt
    assert "needs_input" in prompt
    assert "drafting_summary" in prompt


def test_prompt_no_sdk_import_possible():
    """Ensures prompt.py can be imported without SDK installed."""
    import importlib
    m = importlib.import_module("slidestein.drafting.prompt")
    assert hasattr(m, "build_draft_prompt")


# ---------------------------------------------------------------------------
# build_brief_summary
# ---------------------------------------------------------------------------


def test_brief_summary_key_message_present():
    brief = _FakeBrief()
    summary = build_brief_summary(brief)
    assert "The deal team is on track" in summary


def test_brief_summary_slide_function_present():
    summary = build_brief_summary(_FakeBrief())
    assert "content" in summary


def test_brief_summary_communication_job_present():
    summary = build_brief_summary(_FakeBrief())
    assert "show_process" in summary


def test_brief_summary_no_crash_when_minimal():
    summary = build_brief_summary(_FakeBriefMinimal())
    assert "Minimal brief" in summary


def test_brief_summary_original_request_present():
    summary = build_brief_summary(_FakeBrief())
    assert "Show the project governance structure." in summary


def test_brief_summary_key_message_still_present():
    summary = build_brief_summary(_FakeBrief())
    assert "The deal team is on track." in summary


def test_brief_summary_original_request_with_special_chars():
    class _BriefWithSpecialChars:
        original_request = 'Request with "quotes"\nand newline'
        key_message = "Key message."
        slide_function = _FakeFn("content")
        primary_communication_job = None
        preferred_visual_archetypes = []
        required_content_elements = []

    summary = build_brief_summary(_BriefWithSpecialChars())
    assert 'Request with "quotes"' in summary
    assert "Key message." in summary


def test_needs_input_no_capacity_exception_in_system_prompt():
    assert "cannot be expressed within" not in _SYSTEM_PROMPT
    assert "shorter equivalent wording does not exist" not in _SYSTEM_PROMPT
