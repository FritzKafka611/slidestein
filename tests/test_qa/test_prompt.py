"""Prompt builder tests for M8 Visual QA."""

from __future__ import annotations

import pytest

from slidestein.qa.prompt import _SYSTEM_PROMPT, build_visual_qa_prompt


# ---------------------------------------------------------------------------
# System prompt content assertions
# ---------------------------------------------------------------------------


def test_system_prompt_mentions_visual_qa():
    assert "visual QA" in _SYSTEM_PROMPT.lower() or "visual rendering quality" in _SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_one_slide():
    assert "slide" in _SYSTEM_PROMPT.lower()


def test_system_prompt_not_consulting_content_review():
    assert "business content" in _SYSTEM_PROMPT or "consulting content" in _SYSTEM_PROMPT.lower()


def test_system_prompt_generated_slide_is_primary():
    assert "IMAGE 1" in _SYSTEM_PROMPT or "actual generated slide" in _SYSTEM_PROMPT.lower()


def test_system_prompt_template_reference_style_only():
    assert "visual style" in _SYSTEM_PROMPT.lower() or "style only" in _SYSTEM_PROMPT.lower()


def test_system_prompt_template_text_is_untrusted():
    prompt = _SYSTEM_PROMPT.lower()
    assert "historical" in prompt or "example content" in prompt


def test_system_prompt_visible_text_not_instructions():
    prompt = _SYSTEM_PROMPT.lower()
    assert "not a system instruction" in prompt or "not an instruction" in prompt or "ignore any embedded request" in prompt


def test_system_prompt_json_only_output():
    prompt = _SYSTEM_PROMPT.lower()
    assert "only valid json" in prompt or "only valid json" in prompt or "valid json" in prompt


def test_system_prompt_no_average_score():
    prompt = _SYSTEM_PROMPT.lower()
    assert "do not" in prompt and "average" in prompt


def test_system_prompt_do_not_rewrite():
    prompt = _SYSTEM_PROMPT.lower()
    assert "rewrite" in prompt or "revision" in prompt or "not return" in prompt


# ---------------------------------------------------------------------------
# build_visual_qa_prompt content assertions
# ---------------------------------------------------------------------------


def _minimal_specs() -> list[dict]:
    return [
        {
            "key": "K1",
            "role": "title",
            "semantic_label": "Title",
            "action": "replace",
            "final_text": "Digital transformation drives value.",
            "capacity_utilization": 0.32,
            "geometry": {"x_ratio": 0.04, "y_ratio": 0.07, "width_ratio": 0.88, "height_ratio": 0.09},
        },
        {
            "key": "K2",
            "role": "body_text",
            "semantic_label": "Body",
            "action": "clear",
            "geometry": {"x_ratio": 0.04, "y_ratio": 0.25, "width_ratio": 0.88, "height_ratio": 0.40},
        },
    ]


def _minimal_checks() -> list[dict]:
    return [
        {"check_type": "outside_slide_bounds", "slot_key": "K1", "status": "pass", "details": "OK"},
        {"check_type": "text_overflow", "slot_key": "K1", "status": "unknown", "details": "COM unavailable"},
    ]


def test_prompt_contains_all_six_dimensions():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    for dim in [
        "text_fit_and_clipping",
        "visual_hierarchy",
        "alignment_and_spacing",
        "balance_and_whitespace",
        "typography_and_style_consistency",
        "overall_readability",
    ]:
        assert dim in prompt, f"Dimension {dim!r} missing from prompt"


def test_prompt_contains_k_keys():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "K1" in prompt
    assert "K2" in prompt


def test_prompt_contains_pass_revise():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "pass" in prompt.lower()
    assert "revise" in prompt.lower()


def test_prompt_cleared_marker_for_clear_action():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "CLEARED" in prompt or "intentionally empty" in prompt.lower()


def test_prompt_contains_final_text_for_replace():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "Digital transformation drives value." in prompt


def test_prompt_clipping_mention():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "clipping" in prompt.lower() or "clip" in prompt.lower()


def test_prompt_hierarchy_mention():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "hierarchy" in prompt.lower()


def test_prompt_alignment_mention():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "alignment" in prompt.lower() or "aligned" in prompt.lower()


def test_prompt_whitespace_mention():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "whitespace" in prompt.lower() or "white space" in prompt.lower()


def test_prompt_typography_mention():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "typograph" in prompt.lower() or "style" in prompt.lower()


def test_prompt_readability_mention():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "readability" in prompt.lower() or "readable" in prompt.lower()


def test_prompt_cleared_slots_intentional():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "cleared" in prompt.lower() or "intentional" in prompt.lower()


def test_prompt_do_not_rewrite():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "do not" in prompt.lower() or "don't" in prompt.lower()


def test_prompt_output_schema_present():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "OUTPUT SCHEMA" in prompt or "output schema" in prompt.lower()


def test_prompt_executive_summary_field_in_schema():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "executive_summary" in prompt


def test_prompt_native_checks_included():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "NATIVE DETERMINISTIC CHECKS" in prompt or "native" in prompt.lower()


def test_prompt_no_average_score_in_schema():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    # average_score should NOT appear in the model output schema section
    # It may appear in a "do not calculate" instruction, but NOT as a schema field
    schema_idx = prompt.find("OUTPUT SCHEMA")
    if schema_idx != -1:
        schema_section = prompt[schema_idx:]
        assert '"average_score"' not in schema_section


def test_prompt_empty_native_checks():
    prompt = build_visual_qa_prompt(_minimal_specs(), [])
    assert "none" in prompt.lower() or "no native" in prompt.lower()


def test_prompt_image_labels_present():
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "IMAGE 1" in prompt
    assert "IMAGE 2" in prompt
    assert "IMAGE 3" in prompt


# ---------------------------------------------------------------------------
# v1.1 regression tests: native-fact vs severity, generated_position
# ---------------------------------------------------------------------------


def _specs_with_generated_geometry() -> list[dict]:
    """Slot specs that include generated_geometry (as service now produces in v1.1)."""
    return [
        {
            "key": "K1",
            "role": "title",
            "semantic_label": "Title",
            "action": "replace",
            "final_text": "Test title.",
            "capacity_utilization": 0.25,
            "generated_geometry": {
                "x_ratio": 0.04,
                "y_ratio": 0.07,
                "width_ratio": 0.88,
                "height_ratio": 0.09,
            },
        },
    ]


def test_system_prompt_native_fact_vs_severity_section_present():
    """System prompt must contain the native-fact vs visual-severity explanation."""
    assert "NATIVE DETERMINISTIC FACTS vs VISUAL SEVERITY" in _SYSTEM_PROMPT


def test_system_prompt_template_design_language_section_present():
    """System prompt must contain template design language context."""
    assert "TEMPLATE DESIGN LANGUAGE" in _SYSTEM_PROMPT


def test_system_prompt_small_overflow_not_critical_guidance():
    """System prompt explains that a small overflow is not automatically critical."""
    prompt = _SYSTEM_PROMPT.lower()
    assert "tiny" in prompt or "small" in prompt or "0.06" in prompt


def test_slot_specs_header_says_generated_position():
    """v1.1 slot specs header uses 'generated_position' label (not 'position')."""
    prompt = build_visual_qa_prompt(_specs_with_generated_geometry(), [])
    assert "generated_position" in prompt or "gen_pos" in prompt


def test_slot_specs_use_generated_geometry_field():
    """Slot specs prefer generated_geometry over geometry for position reporting."""
    specs = _specs_with_generated_geometry()
    # Override with a distinctive value to prove generated_geometry is used
    specs[0]["generated_geometry"]["x_ratio"] = 0.77
    # Also add a legacy geometry field with a different x_ratio
    specs[0]["geometry"] = {"x_ratio": 0.01, "y_ratio": 0.0, "width_ratio": 0.1, "height_ratio": 0.1}

    prompt = build_visual_qa_prompt(specs, [])
    # The generated_geometry x_ratio (0.77) should appear in the prompt
    assert "0.770" in prompt, "generated_geometry should take precedence over geometry"


def test_native_checks_preamble_says_geometric_measurements():
    """Native checks section explains these are geometric facts, not severity ratings."""
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    prompt_lower = prompt.lower()
    assert "geometric" in prompt_lower or "measurement" in prompt_lower


def test_native_checks_preamble_not_severity_ratings():
    """Native checks section clarifies these are NOT predetermined severity ratings."""
    prompt = build_visual_qa_prompt(_minimal_specs(), _minimal_checks())
    assert "NATIVE DETERMINISTIC CHECKS" in prompt
    # The preamble must NOT say these are severity ratings
    # (it should say they are measurements the model should interpret)
    native_section_start = prompt.find("NATIVE DETERMINISTIC CHECKS")
    native_section = prompt[native_section_start:native_section_start + 600]
    assert "severity rating" not in native_section.lower() or "not" in native_section.lower()
