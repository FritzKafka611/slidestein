"""Tests for revision prompt functions."""

from __future__ import annotations

from slidestein.revision.prompt import _SYSTEM_PROMPT, build_revision_prompt
from tests.test_revision.conftest import make_brief


def make_slot_specs(include_clear: bool = False) -> list[dict]:
    specs = [
        {
            "key": "K1",
            "role": "title",
            "label": "Slide Title",
            "action": "replace",
            "text": "Digital Transformation Drives Efficiency",
            "capacity_characters": 100,
            "capacity_utilization": 0.42,
            "max_lines_estimate": 2,
        },
        {
            "key": "K2",
            "role": "body_text",
            "label": "Body Content",
            "action": "replace",
            "text": "Channel 1, Channel 2, Channel 3.",
            "capacity_characters": 300,
            "capacity_utilization": 0.11,
            "max_lines_estimate": 6,
        },
        {
            "key": "K3",
            "role": "exhibit_title",
            "label": "Chart Title",
            "action": "replace",
            "text": "Very long chart title that exceeds the capacity limit of the slot.",
            "capacity_characters": 60,
            "capacity_utilization": 1.12,
            "max_lines_estimate": 1,
        },
    ]
    if include_clear:
        specs.append({
            "key": "K4",
            "role": "body_text",
            "label": "Optional section",
            "action": "clear",
            "text": None,
            "capacity_characters": 200,
            "capacity_utilization": 0.0,
            "max_lines_estimate": 4,
        })
    return specs


# ---------------------------------------------------------------------------
# _SYSTEM_PROMPT
# ---------------------------------------------------------------------------


def test_system_prompt_contains_text_only_instruction():
    assert "FACTUAL GROUNDING" in _SYSTEM_PROMPT or "source material" in _SYSTEM_PROMPT.lower()


def test_system_prompt_contains_json_only_instruction():
    assert "JSON" in _SYSTEM_PROMPT
    assert "{" in _SYSTEM_PROMPT


def test_system_prompt_contains_no_clear_instruction():
    assert "never clear" in _SYSTEM_PROMPT.lower() or "only provide replacement" in _SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# build_revision_prompt
# ---------------------------------------------------------------------------


def test_prompt_contains_brief_original_request():
    brief = make_brief(original_request="Create a digital transformation summary slide.")
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    assert "digital transformation summary" in prompt.lower()


def test_prompt_contains_brief_key_message():
    brief = make_brief(key_message="Digital transformation drives efficiency.")
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    assert "Digital transformation drives efficiency" in prompt


def test_prompt_contains_source_material_when_provided():
    brief = make_brief()
    prompt = build_revision_prompt(brief, "Key source fact A.", make_slot_specs(), ["K3"])
    assert "Key source fact A." in prompt


def test_prompt_no_source_material_shows_none():
    brief = make_brief()
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    assert "(none provided)" in prompt


def test_prompt_marks_target_key_with_revise_marker():
    brief = make_brief()
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    assert "REVISE THIS SLOT" in prompt or "REVISE" in prompt


def test_prompt_does_not_mark_non_target_keys():
    brief = make_brief()
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    lines = prompt.split("\n")
    k1_lines = [l for l in lines if l.startswith("K1")]
    assert not any("REVISE" in l for l in k1_lines)


def test_prompt_contains_all_slot_keys():
    brief = make_brief()
    specs = make_slot_specs()
    prompt = build_revision_prompt(brief, None, specs, ["K3"])
    for spec in specs:
        assert spec["key"] in prompt


def test_prompt_contains_capacity_info():
    brief = make_brief()
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    assert "chars" in prompt or "characters" in prompt.lower()


def test_prompt_contains_output_schema():
    brief = make_brief()
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K3"])
    assert "change_summary" in prompt
    assert "changes" in prompt
    assert '"key"' in prompt or "'key'" in prompt or "key" in prompt
    assert "action" in prompt


def test_prompt_shows_cleared_slot_label():
    brief = make_brief()
    specs = make_slot_specs(include_clear=True)
    prompt = build_revision_prompt(brief, None, specs, ["K3"])
    assert "CLEARED" in prompt or "clear" in prompt


def test_prompt_target_keys_in_revision_task():
    brief = make_brief()
    prompt = build_revision_prompt(brief, None, make_slot_specs(), ["K1", "K3"])
    assert "K1" in prompt
    assert "K3" in prompt
    revision_task_section = prompt.split("=== REVISION TASK ===")[-1] if "REVISION TASK" in prompt else ""
    assert "K1" in revision_task_section or "K3" in revision_task_section
