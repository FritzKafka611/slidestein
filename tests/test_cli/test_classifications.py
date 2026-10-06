"""Tests for the classifications CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.domain.models import (
    ClassificationRecord,
    CommunicationJob,
    DensityLevel,
    SlideSemanticProfile,
    StorylineRole,
    VisualArchetype,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(slide_id: str = "slide-001") -> SlideSemanticProfile:
    return SlideSemanticProfile(
        slide_id=slide_id,
        primary_communication_job=CommunicationJob.EXPLAIN,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.BAR_CHART,
        structural_pattern="Bar chart.",
        density=DensityLevel.MEDIUM,
        description="A bar chart slide.",
    )


def _make_classification(slide_id: str = "slide-001") -> ClassificationRecord:
    return ClassificationRecord(
        id=1,
        slide_id=slide_id,
        classification_version="1.0",
        model="claude-test",
        prompt_version="1.0",
        input_fingerprint="fp-abc",
        profile=_make_profile(slide_id),
        classified_at="2026-01-01T00:00:00",
    )


def _invoke_classifications(args: list[str], records: list[ClassificationRecord]):
    mock_lib = MagicMock()
    mock_lib.__enter__.return_value = mock_lib
    mock_lib.list_classifications.return_value = records

    with patch("slidestein.library.store.SlideLibrary", return_value=mock_lib):
        return runner.invoke(app, ["classifications"] + args)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClassificationsCommand:
    def test_help_exits_zero(self):
        result = runner.invoke(app, ["classifications", "--help"])
        assert result.exit_code == 0

    def test_table_output_exits_zero(self):
        records = [_make_classification("s1"), _make_classification("s2")]
        result = _invoke_classifications([], records=records)
        assert result.exit_code == 0

    def test_empty_library_exits_zero(self):
        result = _invoke_classifications([], records=[])
        assert result.exit_code == 0

    def test_json_output_written(self, tmp_path):
        records = [_make_classification("slide-001")]
        out = tmp_path / "out.json"
        result = _invoke_classifications(["--output", str(out)], records=records)
        assert result.exit_code == 0
        assert out.exists()

    def test_json_output_is_valid_array(self, tmp_path):
        records = [_make_classification("slide-001"), _make_classification("slide-002")]
        out = tmp_path / "out.json"
        _invoke_classifications(["--output", str(out)], records=records)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2

    def test_json_contains_required_fields(self, tmp_path):
        records = [_make_classification("slide-abc")]
        out = tmp_path / "out.json"
        _invoke_classifications(["--output", str(out)], records=records)
        data = json.loads(out.read_text(encoding="utf-8"))
        entry = data[0]
        assert entry["slide_id"] == "slide-abc"
        assert "profile" in entry
        assert "classification_version" in entry
        assert "classified_at" in entry
