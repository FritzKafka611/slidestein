"""Tests for vision rerank prompt content — system prompt and build_prompt_text."""

from __future__ import annotations

import pytest

from slidestein.reranking.brief import VisualRerankBrief
from slidestein.reranking.candidates import VisualCandidateInput
from slidestein.reranking.providers.sap_aicore import (
    _SYSTEM_PROMPT,
    build_prompt_text,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brief(**kwargs) -> VisualRerankBrief:
    defaults = dict(
        query_text="test query",
        slide_function=None,
        primary_communication_job=None,
        preferred_visual_archetypes=(),
        storyline_roles=(),
        density=None,
        required_content_elements=(),
    )
    defaults.update(kwargs)
    return VisualRerankBrief(**defaults)


def _candidate(key: str, preview: str = "/tmp/slide.png") -> VisualCandidateInput:
    return VisualCandidateInput(
        candidate_key=key,
        slide_id=f"slide-{key}",
        deck_id="deck-1",
        slide_number=1,
        preview_path=Path(preview),
        hybrid_rank=1,
        hybrid_score=0.7,
        semantic_score=0.6,
    )


# ---------------------------------------------------------------------------
# A. _SYSTEM_PROMPT content checks
# ---------------------------------------------------------------------------


class TestSystemPromptFragments:
    def test_template_reuse_principle_present(self) -> None:
        text = _SYSTEM_PROMPT.upper()
        assert "TEMPLATE REUSE" in text or "REUSABLE" in text

    def test_treat_content_as_placeholder(self) -> None:
        text = _SYSTEM_PROMPT.lower()
        assert "placeholder" in text

    def test_structure_over_topic_wording(self) -> None:
        text = _SYSTEM_PROMPT.lower()
        assert "structure" in text

    def test_prompt_injection_safety_block_present(self) -> None:
        text = _SYSTEM_PROMPT.lower()
        assert "injection" in text or ("instructions" in text and "image" in text)

    def test_images_are_data_not_instructions(self) -> None:
        text = _SYSTEM_PROMPT.lower()
        assert "data" in text

    def test_candidate_order_arbitrary_stated(self) -> None:
        text = _SYSTEM_PROMPT.lower()
        assert "arbitrary" in text

    def test_do_not_assume_earlier_better(self) -> None:
        text = _SYSTEM_PROMPT.lower()
        assert "earlier" in text or "order" in text

    def test_no_credentials_in_system_prompt(self) -> None:
        for forbidden in [
            "client_secret",
            "access_token",
            "Bearer ",
            "aicore_client_id",
            "aicore_base_url",
        ]:
            assert forbidden not in _SYSTEM_PROMPT, (
                f"System prompt must not contain credential: {forbidden!r}"
            )


# ---------------------------------------------------------------------------
# B. build_prompt_text fragments
# ---------------------------------------------------------------------------


class TestBuildPromptTextFragments:
    def test_query_text_included(self) -> None:
        brief = _brief(query_text="timeline of key decisions")
        prompt = build_prompt_text(brief, [_candidate("C1")])
        assert "timeline of key decisions" in prompt

    def test_candidate_key_separator_included(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1"), _candidate("C2")])
        assert "C1" in prompt
        assert "C2" in prompt

    def test_five_rubric_dimensions_listed(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        for dim in [
            "communication_structure_fit",
            "content_capacity_fit",
            "visual_hierarchy",
            "argument_flow",
            "density_fit",
        ]:
            assert dim in prompt, f"Dimension '{dim}' missing from prompt"

    def test_json_output_instruction_included(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        assert "assessments" in prompt  # schema key is present

    def test_assessments_key_in_output_schema(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        assert "assessments" in prompt

    def test_hybrid_score_not_revealed_in_prompt(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1"), _candidate("C2")]
        prompt = build_prompt_text(brief, candidates)
        assert "hybrid_score" not in prompt
        assert "hybrid score" not in prompt.lower()
        assert "0.7" not in prompt  # the actual hybrid_score value

    def test_candidate_ranking_metadata_not_in_prompt(self) -> None:
        """Candidate hybrid_rank, hybrid_score, semantic_score must not appear."""
        brief = _brief()
        c = _candidate("C1")  # hybrid_rank=1, hybrid_score=0.7, semantic_score=0.6
        prompt = build_prompt_text(brief, [c])
        assert "hybrid_rank" not in prompt
        assert "semantic_score" not in prompt
        # actual float values must also be absent
        assert "0.7" not in prompt
        assert "0.6" not in prompt

    def test_rationale_field_requested(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        assert "rationale" in prompt

    def test_strengths_field_requested(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        assert "strengths" in prompt

    def test_limitations_field_requested(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        assert "limitations" in prompt

    def test_integer_score_range_1_to_5_stated(self) -> None:
        prompt = build_prompt_text(_brief(), [_candidate("C1")])
        assert "1" in prompt and "5" in prompt

    def test_all_candidate_keys_in_prompt(self) -> None:
        candidates = [_candidate(f"C{i}") for i in range(1, 6)]
        prompt = build_prompt_text(_brief(), candidates)
        for c in candidates:
            assert c.candidate_key in prompt

    def test_prompt_is_deterministic(self) -> None:
        brief = _brief(query_text="board update")
        candidates = [_candidate("C1"), _candidate("C2")]
        assert build_prompt_text(brief, candidates) == build_prompt_text(brief, candidates)
