"""Tests verifying the V2 classification prompt contains required calibration rules.

These are semantic fragment checks — not brittle full-text assertions.
Each test targets a distinct required concept the model must receive.
"""

from __future__ import annotations

import pytest

from slidestein.classification.prompt import build_classification_prompt, _PROMPT_TEMPLATE
from slidestein.domain.models import SlideClassificationInput


def _make_input(**overrides) -> SlideClassificationInput:
    defaults = dict(
        slide_id="test-v2-001",
        extracted_text="Project objective and scope.",
        structural_metadata={"shape_count": 5},
    )
    defaults.update(overrides)
    return SlideClassificationInput(**defaults)


def _full_prompt(slide_id: str = "test-v2-001") -> str:
    return build_classification_prompt(_make_input(slide_id=slide_id))


class TestPromptV2SlideFunction:
    def test_prompt_contains_slide_function_section(self) -> None:
        p = _full_prompt()
        assert "slide_function" in p

    def test_prompt_lists_content_function(self) -> None:
        p = _full_prompt()
        assert "content" in p

    def test_prompt_lists_section_divider_function(self) -> None:
        p = _full_prompt()
        assert "section_divider" in p

    def test_prompt_lists_cover_function(self) -> None:
        p = _full_prompt()
        assert "cover" in p

    def test_prompt_lists_closing_function(self) -> None:
        p = _full_prompt()
        assert "closing" in p

    def test_prompt_says_null_for_navigational(self) -> None:
        p = _full_prompt()
        assert "null" in p

    def test_prompt_schema_version_is_2(self) -> None:
        p = _full_prompt()
        assert '"2.0"' in p

    def test_prompt_shows_null_primary_job_example(self) -> None:
        p = _full_prompt()
        assert '"primary_communication_job": null' in p


class TestPromptV2VisualStructureFirst:
    def test_prompt_says_visual_structure_takes_precedence(self) -> None:
        p = _full_prompt()
        assert "VISUAL STRUCTURE" in p.upper() or "visual structure" in p.lower()

    def test_prompt_warns_against_topic_word_inference(self) -> None:
        p = _full_prompt()
        # Must explicitly warn not to infer from topic words
        assert "topic" in p.lower() or "words" in p.lower()


class TestPromptV2ShowProcess:
    def test_prompt_requires_explicit_sequence_for_show_process(self) -> None:
        p = _full_prompt()
        assert "sequence" in p.lower() or "flow" in p.lower()

    def test_prompt_flags_deliverables_not_process(self) -> None:
        p = _full_prompt()
        # Must say something like "NOT applicable to workstream summaries / deliverables"
        assert "deliverable" in p.lower()

    def test_prompt_flags_project_charter_not_process(self) -> None:
        p = _full_prompt()
        assert "charter" in p.lower() or "workstream" in p.lower()


class TestPromptV2ShowTimeline:
    def test_prompt_requires_time_visually_encoded_for_show_timeline(self) -> None:
        p = _full_prompt()
        assert "calendar" in p.lower() or "time axis" in p.lower() or "spatially" in p.lower()

    def test_prompt_says_section_divider_titled_timeline_is_not_show_timeline(self) -> None:
        p = _full_prompt()
        assert "section" in p.lower() and "divider" in p.lower()


class TestPromptV2StructuredOnePager:
    def test_prompt_defines_structured_one_pager(self) -> None:
        p = _full_prompt()
        assert "structured_one_pager" in p

    def test_prompt_distinguishes_structured_one_pager_from_text_heavy(self) -> None:
        p = _full_prompt()
        # Must instruct to use structured_one_pager INSTEAD of text_heavy
        assert "text_heavy" in p
        assert "instead" in p.lower() or "do not" in p.lower()


class TestPromptV2HierarchyVsOrgChart:
    def test_prompt_defines_org_chart_as_reporting_relationships(self) -> None:
        p = _full_prompt()
        assert "reporting" in p.lower()

    def test_prompt_defines_hierarchy_as_layered_levels(self) -> None:
        p = _full_prompt()
        assert "hierarchy" in p.lower()
        assert "governance" in p.lower() or "authority" in p.lower() or "layered" in p.lower()


class TestPromptV2ReasoningSteps:
    def test_prompt_contains_step_1(self) -> None:
        p = _full_prompt()
        assert "STEP 1" in p

    def test_prompt_contains_step_3_conditional(self) -> None:
        p = _full_prompt()
        assert "STEP 3" in p

    def test_prompt_explains_job_only_for_content(self) -> None:
        p = _full_prompt()
        assert "content" in p and "null" in p
