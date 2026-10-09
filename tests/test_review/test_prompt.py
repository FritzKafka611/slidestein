"""Tests for review/prompt.py — pure function tests, no mocking (v1.1)."""

from __future__ import annotations

from slidestein.review.prompt import _SYSTEM_PROMPT, build_review_prompt
from tests.test_review.conftest import make_brief


_SLOT_SPECS = [
    {"key": "K1", "role": "title", "label": "Title", "action": "replace",
     "text": "Digital investment should focus on top-3 channels.",
     "character_count": 50, "capacity_characters": 70, "capacity_utilization": 0.71,
     "explicit_line_count": 1, "max_lines_estimate": 1, "group_id": None, "sequence_index": None},
    {"key": "K2", "role": "body_text", "label": "Body", "action": "replace",
     "text": "Channel A saves 15%. Channel B saves 12%. Channel C saves 10%.",
     "character_count": 60, "capacity_characters": 388, "capacity_utilization": 0.15,
     "explicit_line_count": 3, "max_lines_estimate": 8, "group_id": None, "sequence_index": None},
    {"key": "K3", "role": "supporting", "label": "Note", "action": "clear", "text": None,
     "character_count": 0, "capacity_characters": 50, "capacity_utilization": 0.0,
     "explicit_line_count": 0, "max_lines_estimate": 2, "group_id": None, "sequence_index": None},
    {"key": "K4", "role": "supporting", "label": "Source", "action": "needs_input", "text": None,
     "character_count": 0, "capacity_characters": 50, "capacity_utilization": 0.0,
     "explicit_line_count": 0, "max_lines_estimate": 2, "group_id": None, "sequence_index": None},
]

_GROUP_DESCS = [
    {"group_id": "section_labels", "group_role": "section_header", "semantic_label": "Section labels",
     "member_keys": ["K2", "K3"], "sequence_index": 0},
]


# ---------------------------------------------------------------------------
# System prompt hardening
# ---------------------------------------------------------------------------


def test_system_prompt_text_only() -> None:
    assert "TEXT ONLY" in _SYSTEM_PROMPT


def test_system_prompt_json_only_instruction() -> None:
    assert "valid JSON" in _SYSTEM_PROMPT or "ONLY valid JSON" in _SYSTEM_PROMPT


def test_system_prompt_no_fences_instruction() -> None:
    assert "code fence" in _SYSTEM_PROMPT or "backtick" in _SYSTEM_PROMPT


def test_system_prompt_prompt_injection_boundary() -> None:
    assert "UNTRUSTED" in _SYSTEM_PROMPT or "injection" in _SYSTEM_PROMPT.lower()


def test_system_prompt_no_rewrite_instruction() -> None:
    assert "rewrite" in _SYSTEM_PROMPT.lower() or "not rewrite" in _SYSTEM_PROMPT.lower()


def test_system_prompt_no_invent_facts() -> None:
    assert "invent" in _SYSTEM_PROMPT.lower()


def test_system_prompt_do_not_calculate_average() -> None:
    assert "average" in _SYSTEM_PROMPT.lower()
    assert "not calculate" in _SYSTEM_PROMPT.lower() or "Do not calculate" in _SYSTEM_PROMPT


def test_system_prompt_one_slide_only() -> None:
    assert "ONE slide" in _SYSTEM_PROMPT or "one slide" in _SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# Prompt content — dimensions and structure
# ---------------------------------------------------------------------------


def test_all_six_dimensions_in_prompt() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    for dim in [
        "answer_first_title",
        "core_message_clarity",
        "vertical_logic",
        "exhibit_title_consistency",
        "mece_structure",
        "content_density",
    ]:
        assert dim in prompt or dim.upper().replace("_", " ") in prompt, f"Missing: {dim}"


def test_source_material_none_shows_none_provided() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "(none provided)" in prompt


def test_source_material_text_appears_in_prompt() -> None:
    brief = make_brief()
    material = "Revenue from Channel A is $12M annually."
    prompt = build_review_prompt(brief, material, _SLOT_SPECS)
    assert material in prompt


def test_k_keys_appear_in_prompt() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "K1" in prompt
    assert "K2" in prompt


def test_approve_revise_appear_in_prompt() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "approve" in prompt
    assert "revise" in prompt


def test_brief_key_message_in_prompt() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert brief.key_message in prompt


def test_original_request_in_prompt() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert brief.original_request in prompt


def test_cleared_marker_for_clear_action() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "[CLEARED" in prompt


def test_missing_marker_for_needs_input() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "[MISSING" in prompt


def test_output_schema_section_present() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "OUTPUT SCHEMA" in prompt


def test_executive_summary_field_in_schema() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "executive_summary" in prompt


def test_recommendation_rule_section_present() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "RECOMMENDATION RULE" in prompt


# ---------------------------------------------------------------------------
# Recommendation: qualitative — no numeric threshold
# ---------------------------------------------------------------------------


def test_no_numeric_threshold_in_recommendation_rule() -> None:
    """v1.1 removes the 'average >= 4.0' threshold — must not appear in prompt."""
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "4.0" not in prompt
    assert ">= 4" not in prompt
    assert "average >= " not in prompt


def test_recommendation_is_qualitative() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    lower = prompt.lower()
    assert "qualitative" in lower or "senior-manager" in lower or "senior manager" in lower


def test_minor_issues_compatible_with_approve() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    lower = prompt.lower()
    assert "minor" in lower and "approve" in lower


def test_average_score_application_owned_note_in_schema() -> None:
    """Schema section must state that average_score is not returned by the model."""
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "average_score" in prompt
    lower = prompt.lower()
    assert "application" in lower or "compute" in lower or "do not" in lower


# ---------------------------------------------------------------------------
# Capacity data in draft content
# ---------------------------------------------------------------------------


def test_capacity_data_in_prompt_for_replace_slot() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    # capacity data for K1 (50/70 chars)
    assert "50" in prompt and "70" in prompt


def test_cleared_slot_intentionally_unused_label() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "intentionally" in prompt.lower() or "CLEARED" in prompt


# ---------------------------------------------------------------------------
# Group context section
# ---------------------------------------------------------------------------


def test_group_context_section_present_when_groups_given() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS, _GROUP_DESCS)
    assert "GROUP CONTEXT" in prompt or "group" in prompt.lower()


def test_group_context_absent_when_no_groups() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS, [])
    assert "GROUP CONTEXT" not in prompt


def test_group_member_keys_in_prompt() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS, _GROUP_DESCS)
    assert "K2" in prompt
    assert "K3" in prompt


# ---------------------------------------------------------------------------
# Exhibit/body consistency rubric
# ---------------------------------------------------------------------------


def test_exhibit_rubric_does_not_require_charts() -> None:
    """v1.1 rubric must NOT say 'If no exhibits, score 3 neutral'."""
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert "score 3 (not applicable" not in prompt
    assert "If no exhibits are present, score 3" not in prompt


def test_exhibit_rubric_mentions_body() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    lower = prompt.lower()
    assert "body" in lower or "structured" in lower


# ---------------------------------------------------------------------------
# MECE boundary
# ---------------------------------------------------------------------------


def test_mece_rubric_does_not_demand_generic_dimensions() -> None:
    """v1.1 MECE rubric must guide the model NOT to penalise for missing How/Who/Risk."""
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    lower = prompt.lower()
    assert "do not penali" in lower or "not penali" in lower


# ---------------------------------------------------------------------------
# Severity guidance
# ---------------------------------------------------------------------------


def test_severity_calibration_section_present() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    lower = prompt.lower()
    assert "severity" in lower and ("critical" in lower) and ("major" in lower) and ("minor" in lower)


def test_severity_guide_says_suboptimal_title_is_major() -> None:
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    lower = prompt.lower()
    assert "major" in lower
    assert "critical" in lower


# ---------------------------------------------------------------------------
# factual_flags schema
# ---------------------------------------------------------------------------


def test_factual_flags_schema_is_object_array() -> None:
    """Output schema must show factual_flags as array of objects, not strings."""
    brief = make_brief()
    prompt = build_review_prompt(brief, None, _SLOT_SPECS)
    assert '"factual_grounding"' in prompt or "factual_grounding" in prompt
    assert '"severity"' in prompt or "severity" in prompt
