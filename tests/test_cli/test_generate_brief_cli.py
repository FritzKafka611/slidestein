"""Unit tests for the generate-brief CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.briefing.providers.sap_aicore import SlideBriefGenerationError
from slidestein.cli import app
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_PATCH_GENERATOR_FACTORY = "slidestein.briefing.providers.factory.create_slide_brief_generator"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_REQUEST = "Show how five workstreams will be delivered over 12 weeks with milestones."


def _make_brief(**kwargs) -> ConsultingSlideBrief:
    defaults = dict(
        original_request=USER_REQUEST,
        key_message="Five workstreams delivered over 12 weeks with milestones.",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SHOW_TIMELINE,
        secondary_communication_jobs=[CommunicationJob.SHOW_PROCESS],
        storyline_roles=[StorylineRole.SITUATION],
        required_content_elements=["five workstreams", "12-week timeline", "milestones"],
        preferred_visual_archetypes=[VisualArchetype.ROADMAP],
        density=DensityLevel.MEDIUM,
        assumptions=["Assumed implementation stage."],
        open_questions=[],
    )
    defaults.update(kwargs)
    return ConsultingSlideBrief(**defaults)


def _mock_generator(brief: ConsultingSlideBrief | None = None) -> MagicMock:
    gen = MagicMock()
    gen.generate.return_value = brief or _make_brief()
    return gen


def _invoke(args: list[str], generator: MagicMock | None = None) -> object:
    gen = generator or _mock_generator()
    with patch(_PATCH_GENERATOR_FACTORY, return_value=gen):
        return runner.invoke(app, ["generate-brief"] + args)


# ---------------------------------------------------------------------------
# Basic success
# ---------------------------------------------------------------------------

class TestBasicSuccess:
    def test_exits_zero(self):
        result = _invoke([USER_REQUEST])
        assert result.exit_code == 0, result.output

    def test_key_message_rendered(self):
        result = _invoke([USER_REQUEST])
        assert "Five workstreams" in result.output

    def test_slide_function_rendered(self):
        result = _invoke([USER_REQUEST])
        assert "content" in result.output.lower()

    def test_primary_communication_job_rendered(self):
        result = _invoke([USER_REQUEST])
        assert "show_timeline" in result.output

    def test_secondary_jobs_rendered(self):
        result = _invoke([USER_REQUEST])
        assert "show_process" in result.output

    def test_storyline_roles_rendered(self):
        result = _invoke([USER_REQUEST])
        assert "situation" in result.output

    def test_density_rendered(self):
        result = _invoke([USER_REQUEST])
        assert "medium" in result.output


# ---------------------------------------------------------------------------
# None / empty optional fields
# ---------------------------------------------------------------------------

class TestNullOptionalFields:
    def test_null_primary_job_renders_as_none_safely(self):
        brief = _make_brief(
            slide_function=SlideFunction.COVER,
            primary_communication_job=None,
            secondary_communication_jobs=[],
        )
        gen = _mock_generator(brief)
        result = _invoke([USER_REQUEST], generator=gen)
        assert result.exit_code == 0, result.output
        assert "(none)" in result.output

    def test_null_density_renders_as_unspecified(self):
        brief = _make_brief(density=None)
        gen = _mock_generator(brief)
        result = _invoke([USER_REQUEST], generator=gen)
        assert "unspecified" in result.output


# ---------------------------------------------------------------------------
# Blank request guard
# ---------------------------------------------------------------------------

class TestBlankRequestGuard:
    def test_blank_request_exits_1(self):
        gen = MagicMock()
        with patch(_PATCH_GENERATOR_FACTORY, return_value=gen):
            result = runner.invoke(app, ["generate-brief", "   "])
        assert result.exit_code != 0
        gen.generate.assert_not_called()

    def test_blank_request_error_message(self):
        gen = MagicMock()
        with patch(_PATCH_GENERATOR_FACTORY, return_value=gen):
            result = runner.invoke(app, ["generate-brief", "   "])
        assert "blank" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# --output flag
# ---------------------------------------------------------------------------

class TestOutputFlag:
    def test_output_writes_valid_json(self, tmp_path: Path):
        out = tmp_path / "brief.json"
        _invoke([USER_REQUEST, "--output", str(out)])
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "key_message" in data

    def test_output_json_round_trips(self, tmp_path: Path):
        out = tmp_path / "brief.json"
        brief = _make_brief()
        gen = _mock_generator(brief)
        _invoke([USER_REQUEST, "--output", str(out)], generator=gen)
        loaded = ConsultingSlideBrief.model_validate_json(out.read_text(encoding="utf-8"))
        assert loaded.key_message == brief.key_message
        assert loaded.slide_function == brief.slide_function


# ---------------------------------------------------------------------------
# --show-retrieval-request flag
# ---------------------------------------------------------------------------

class TestShowRetrievalRequest:
    def test_show_retrieval_request_displays_query_text(self):
        result = _invoke([USER_REQUEST, "--show-retrieval-request"])
        assert "query_text" in result.output

    def test_query_text_equals_original_request(self):
        result = _invoke([USER_REQUEST, "--show-retrieval-request"])
        import re
        # Rich may wrap and pad long lines; collapse whitespace before asserting
        output_flat = re.sub(r"\s+", " ", result.output)
        assert USER_REQUEST in output_flat

    def test_key_message_not_used_as_query(self):
        brief = _make_brief()
        gen = _mock_generator(brief)
        result = _invoke([USER_REQUEST, "--show-retrieval-request"], generator=gen)
        assert brief.key_message not in result.output.split("query_text")[1][:100]

    def test_secondary_jobs_not_forwarded_note_present(self):
        result = _invoke([USER_REQUEST, "--show-retrieval-request"])
        assert "secondary" in result.output.lower()
        assert "not forwarded" in result.output.lower() or "M5.1" in result.output


# ---------------------------------------------------------------------------
# cp1252 safety
# ---------------------------------------------------------------------------

class TestCp1252Safety:
    def test_output_contains_only_cp1252_safe_characters(self):
        result = _invoke([USER_REQUEST])
        try:
            result.output.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(f"Output contains cp1252-unsafe characters: {exc}")
