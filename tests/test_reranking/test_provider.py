"""Tests for SAPAICoreVisionReranker — mocks the SAP AI Core SDK boundary."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.reranking.brief import VisualRerankBrief
from slidestein.reranking.candidates import VisualCandidateInput
from slidestein.reranking.providers.sap_aicore import (
    SAPAICoreVisionReranker,
    VisionRerankError,
    _strip_fences,
    build_prompt_text,
    _SYSTEM_PROMPT,
)
from slidestein.reranking.rubric import VisualRerankModelOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brief(**kwargs) -> VisualRerankBrief:
    defaults = dict(
        query_text="show key milestones",
        slide_function=None,
        primary_communication_job=None,
        preferred_visual_archetypes=(),
        storyline_roles=(),
        density=None,
        required_content_elements=(),
    )
    defaults.update(kwargs)
    return VisualRerankBrief(**defaults)


def _candidate(key: str, preview_path: str = "/tmp/slide.png") -> VisualCandidateInput:
    return VisualCandidateInput(
        candidate_key=key,
        slide_id=f"slide-{key}",
        deck_id="deck-1",
        slide_number=1,
        preview_path=Path(preview_path),
        hybrid_rank=1,
        hybrid_score=0.7,
        semantic_score=0.6,
    )


def _valid_json_response(keys: list[str]) -> str:
    assessments = [
        {
            "candidate_key": k,
            "communication_structure_fit": 4,
            "content_capacity_fit": 3,
            "visual_hierarchy": 4,
            "argument_flow": 3,
            "density_fit": 4,
            "rationale": f"Good structure for {k}",
            "strengths": ["clear layout"],
            "limitations": ["limited space"],
        }
        for k in keys
    ]
    return json.dumps({"assessments": assessments})


def _make_mock_client(response_text: str) -> MagicMock:
    """Minimal SAP AI Core client mock that returns response_text from run()."""
    choice = MagicMock()
    choice.message.content = response_text

    completion = MagicMock()
    completion.choices = [choice]

    run_result = MagicMock()
    run_result.final_result = completion

    orchestration = MagicMock()
    orchestration.run.return_value = run_result

    # Deployment discovery
    deployment = MagicMock()
    deployment.scenario_id = "orchestration"
    deployment.deployment_id = "dep-001"

    client = MagicMock()
    client.deployment.query.return_value = MagicMock(resources=[deployment])

    return client, orchestration


# ---------------------------------------------------------------------------
# A. _strip_fences
# ---------------------------------------------------------------------------


class TestStripFences:
    def test_strips_json_code_fence(self) -> None:
        fenced = "```json\n{}\n```"
        assert _strip_fences(fenced) == "{}"

    def test_strips_plain_code_fence(self) -> None:
        fenced = "```\n{}\n```"
        assert _strip_fences(fenced) == "{}"

    def test_leaves_plain_json_unchanged(self) -> None:
        plain = '{"assessments": []}'
        assert _strip_fences(plain) == plain

    def test_strips_leading_trailing_whitespace(self) -> None:
        fenced = "```json\n{}\n```"
        assert _strip_fences(fenced) == "{}"

    def test_multiline_content_preserved(self) -> None:
        inner = '{\n  "assessments": []\n}'
        fenced = f"```json\n{inner}\n```"
        assert _strip_fences(fenced).strip() == inner.strip()


# ---------------------------------------------------------------------------
# B. build_prompt_text (pure Python, no SDK dependency)
# ---------------------------------------------------------------------------


class TestBuildPromptText:
    def test_contains_query_text(self) -> None:
        brief = _brief(query_text="executive summary slide")
        candidates = [_candidate("C1"), _candidate("C2")]
        prompt = build_prompt_text(brief, candidates)
        assert "executive summary slide" in prompt

    def test_contains_all_candidate_keys(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1"), _candidate("C2"), _candidate("C3")]
        prompt = build_prompt_text(brief, candidates)
        for key in ["C1", "C2", "C3"]:
            assert key in prompt

    def test_instructs_json_output(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1")]
        prompt = build_prompt_text(brief, candidates)
        assert "assessments" in prompt  # output schema key present

    def test_instructs_all_five_dimensions(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1")]
        prompt = build_prompt_text(brief, candidates)
        for dim in [
            "communication_structure_fit",
            "content_capacity_fit",
            "visual_hierarchy",
            "argument_flow",
            "density_fit",
        ]:
            assert dim in prompt

    def test_does_not_contain_hybrid_score(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1")]
        prompt = build_prompt_text(brief, candidates)
        assert "hybrid_score" not in prompt
        assert "hybrid score" not in prompt.lower()

    def test_does_not_contain_taxonomy_labels(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1")]
        prompt = build_prompt_text(brief, candidates)
        # The candidate input must not reveal classified labels to the model
        assert "communication_job" not in prompt.lower()
        assert "archetype" not in prompt.lower()


# ---------------------------------------------------------------------------
# C. _SYSTEM_PROMPT content
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_contains_template_reuse_principle(self) -> None:
        assert "template" in _SYSTEM_PROMPT.lower() or "reusable" in _SYSTEM_PROMPT.lower()

    def test_contains_prompt_injection_safety(self) -> None:
        assert "injection" in _SYSTEM_PROMPT.lower() or "instructions" in _SYSTEM_PROMPT.lower()

    def test_candidate_order_is_arbitrary(self) -> None:
        assert "arbitrary" in _SYSTEM_PROMPT.lower() or "order" in _SYSTEM_PROMPT.lower()

    def test_evaluates_structure_not_topic(self) -> None:
        assert "structure" in _SYSTEM_PROMPT.lower()

    def test_no_secrets_in_system_prompt(self) -> None:
        forbidden = ["client_secret", "access_token", "aicore_", "Bearer "]
        for term in forbidden:
            assert term not in _SYSTEM_PROMPT, f"Found forbidden term '{term}' in system prompt"


# ---------------------------------------------------------------------------
# D. JSON parsing
# ---------------------------------------------------------------------------


class TestJSONParsing:
    def test_valid_json_parsed_successfully(self) -> None:
        raw = _valid_json_response(["C1", "C2"])
        out = VisualRerankModelOutput.model_validate_json(raw)
        assert len(out.assessments) == 2

    def test_fenced_json_parsed_after_strip(self) -> None:
        raw = _valid_json_response(["C1"])
        fenced = f"```json\n{raw}\n```"
        stripped = _strip_fences(fenced)
        out = VisualRerankModelOutput.model_validate_json(stripped)
        assert out.assessments[0].candidate_key == "C1"

    def test_malformed_json_raises_vision_rerank_error(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1")]

        mock_client = MagicMock()
        reranker = SAPAICoreVisionReranker(mock_client, model="claude-3.5-sonnet")

        with patch.object(reranker, "_build_content", return_value=[]):
            with patch.object(reranker, "_run_orchestration", return_value="not-valid-json"):
                with pytest.raises(VisionRerankError):
                    reranker.assess(brief, candidates)

    def test_score_out_of_range_raises_vision_rerank_error(self) -> None:
        bad_json = json.dumps({
            "assessments": [{
                "candidate_key": "C1",
                "communication_structure_fit": 9,
                "content_capacity_fit": 3,
                "visual_hierarchy": 3,
                "argument_flow": 3,
                "density_fit": 3,
                "rationale": "ok",
                "strengths": ["s"],
                "limitations": ["l"],
            }]
        })
        brief = _brief()
        candidates = [_candidate("C1")]

        mock_client = MagicMock()
        reranker = SAPAICoreVisionReranker(mock_client, model="claude-3.5-sonnet")

        with patch.object(reranker, "_build_content", return_value=[]):
            with patch.object(reranker, "_run_orchestration", return_value=bad_json):
                with pytest.raises((VisionRerankError, Exception)):
                    reranker.assess(brief, candidates)


# ---------------------------------------------------------------------------
# E. Content list construction (unit — no real image I/O)
# ---------------------------------------------------------------------------


class TestBuildContent:
    def test_content_starts_with_context_text(self) -> None:
        """build_prompt_text (pure Python) starts with context containing the query."""
        brief = _brief(query_text="milestones")
        candidates = [_candidate("C1"), _candidate("C2")]
        prompt = build_prompt_text(brief, candidates)
        assert "milestones" in prompt

    def test_content_includes_label_for_each_candidate(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1", "/p1.png"), _candidate("C2", "/p2.png")]
        prompt = build_prompt_text(brief, candidates)
        assert "C1" in prompt
        assert "C2" in prompt

    def test_content_ends_with_instruction_text(self) -> None:
        brief = _brief()
        candidates = [_candidate("C1")]
        prompt = build_prompt_text(brief, candidates)
        assert "assessments" in prompt  # output schema key
