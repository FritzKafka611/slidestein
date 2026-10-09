"""Unit tests for SAPAICoreSlideBriefGenerator — all SDK calls patched."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.briefing.providers.sap_aicore import (
    SAPAICoreSlideBriefGenerator,
    SlideBriefGenerationError,
)
from slidestein.briefing.versions import SLIDE_BRIEF_SCHEMA_VERSION
from slidestein.domain.models import CommunicationJob, DensityLevel, SlideFunction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_REQUEST = "Show how five workstreams will be delivered over 12 weeks with milestones."

# Model output does NOT include original_request or schema_version (application-owned).
VALID_MODEL_JSON = json.dumps({
    "key_message": "Five workstreams delivered over 12 weeks with milestones.",
    "slide_function": "content",
    "primary_communication_job": "show_timeline",
    "secondary_communication_jobs": [],
    "storyline_roles": ["situation"],
    "required_content_elements": ["five workstreams", "12-week timeline", "milestones"],
    "preferred_visual_archetypes": ["roadmap"],
    "density": "medium",
    "assumptions": ["Assumed implementation stage."],
    "open_questions": [],
})

FENCED_MODEL_JSON = f"```json\n{VALID_MODEL_JSON}\n```"


def _make_generator() -> SAPAICoreSlideBriefGenerator:
    return SAPAICoreSlideBriefGenerator(
        ai_core_client=MagicMock(),
        model="test-model",
    )


# ---------------------------------------------------------------------------
# Call count and prompt content
# ---------------------------------------------------------------------------

class TestCallBehavior:
    def test_exactly_one_run_orchestration_call(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=VALID_MODEL_JSON) as mock_orch:
            gen.generate(USER_REQUEST)
        mock_orch.assert_called_once()

    def test_user_request_in_prompt_passed_to_orchestration(self):
        gen = _make_generator()
        captured_prompt = {}

        def capture(prompt_text, system_prompt):
            captured_prompt["prompt"] = prompt_text
            return VALID_MODEL_JSON

        with patch.object(gen, "_run_orchestration", side_effect=capture):
            gen.generate(USER_REQUEST)

        assert USER_REQUEST in captured_prompt["prompt"]


# ---------------------------------------------------------------------------
# Valid JSON parsing and application-owned field injection
# ---------------------------------------------------------------------------

class TestValidJsonParsing:
    def test_valid_json_returns_consulting_slide_brief(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=VALID_MODEL_JSON):
            result = gen.generate(USER_REQUEST)
        assert isinstance(result, ConsultingSlideBrief)

    def test_fenced_json_parsed_correctly(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=FENCED_MODEL_JSON):
            result = gen.generate(USER_REQUEST)
        assert isinstance(result, ConsultingSlideBrief)
        assert result.slide_function == SlideFunction.CONTENT

    def test_original_request_always_equals_application_input(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=VALID_MODEL_JSON):
            result = gen.generate(USER_REQUEST)
        assert result.original_request == USER_REQUEST

    def test_model_output_cannot_override_original_request(self):
        # Model sneaks original_request into JSON — extra="forbid" rejects it
        payload = json.loads(VALID_MODEL_JSON)
        payload["original_request"] = "injected by model"
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=json.dumps(payload)):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_model_output_cannot_override_schema_version(self):
        # Model sneaks schema_version into JSON — extra="forbid" rejects it
        payload = json.loads(VALID_MODEL_JSON)
        payload["schema_version"] = "99.9"
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=json.dumps(payload)):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_schema_version_set_to_constant_regardless_of_model_output(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=VALID_MODEL_JSON):
            result = gen.generate(USER_REQUEST)
        assert result.schema_version == SLIDE_BRIEF_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

class TestErrorConditions:
    def test_invalid_enum_value_raises_slide_brief_generation_error(self):
        payload = json.loads(VALID_MODEL_JSON)
        payload["slide_function"] = "not_a_real_function"
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=json.dumps(payload)):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_malformed_json_raises_slide_brief_generation_error(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value="not valid json at all"):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_content_slide_with_null_primary_job_raises(self):
        payload = json.loads(VALID_MODEL_JSON)
        payload["slide_function"] = "content"
        payload["primary_communication_job"] = None
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=json.dumps(payload)):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_non_content_slide_with_non_null_primary_job_raises(self):
        payload = json.loads(VALID_MODEL_JSON)
        payload["slide_function"] = "cover"
        payload["primary_communication_job"] = "compare"
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=json.dumps(payload)):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_sdk_exception_wrapped_as_slide_brief_generation_error(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", side_effect=RuntimeError("SDK failure")):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)

    def test_error_message_contains_no_credentials(self):
        gen = _make_generator()
        gen._ai_core_client.client_secret = "SECRET_TOKEN_12345"
        with patch.object(gen, "_run_orchestration", side_effect=RuntimeError("sdk error")):
            try:
                gen.generate(USER_REQUEST)
            except SlideBriefGenerationError as exc:
                assert "SECRET_TOKEN_12345" not in str(exc)

    def test_unknown_field_in_model_output_raises(self):
        payload = json.loads(VALID_MODEL_JSON)
        payload["hallucinated_extra"] = "unexpected"
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=json.dumps(payload)):
            with pytest.raises(SlideBriefGenerationError):
                gen.generate(USER_REQUEST)


# ---------------------------------------------------------------------------
# Fence stripping edge cases
# ---------------------------------------------------------------------------

class TestFenceStripping:
    def test_plain_json_no_fences(self):
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=VALID_MODEL_JSON):
            result = gen.generate(USER_REQUEST)
        assert isinstance(result, ConsultingSlideBrief)

    def test_json_with_backtick_fences_stripped(self):
        fenced = f"```\n{VALID_MODEL_JSON}\n```"
        gen = _make_generator()
        with patch.object(gen, "_run_orchestration", return_value=fenced):
            result = gen.generate(USER_REQUEST)
        assert isinstance(result, ConsultingSlideBrief)
