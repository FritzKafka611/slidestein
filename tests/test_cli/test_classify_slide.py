"""Tests for the classify-slide CLI command (spec section 17 items 15–22).

No real Anthropic API calls or PowerPoint rendering.
The service is mocked at the module level so tests run offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.classification.classifier import SlideClassificationError
from slidestein.cli import app
from slidestein.domain.models import (
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


def _fake_profile(slide_id: str = "abc123def456-001") -> SlideSemanticProfile:
    return SlideSemanticProfile(
        slide_id=slide_id,
        primary_communication_job=CommunicationJob.COMPARE,
        storyline_roles=[StorylineRole.INSIGHT],
        visual_archetype=VisualArchetype.COMPARISON,
        structural_pattern="Two-column side-by-side comparison.",
        density=DensityLevel.MEDIUM,
        description="Comparison of two strategic options.",
    )


def _invoke(
    args: list[str],
    profile: SlideSemanticProfile | None = None,
    side_effect: BaseException | None = None,
) -> "Result":
    """Invoke the classify-slide command with service, classifier, and library mocked."""
    mock_svc = MagicMock()
    if side_effect is not None:
        mock_svc.classify_slide.side_effect = side_effect
    else:
        mock_svc.classify_slide.return_value = profile or _fake_profile()

    # Mock SlideLibrary so the command doesn't touch a real DB.
    # The slide is not indexed (returns None), so persistence is skipped.
    mock_lib = MagicMock()
    mock_lib.__enter__.return_value.get_record_by_deck_and_slide.return_value = None

    with (
        patch(
            "slidestein.classification.service.SlideClassificationService",
            return_value=mock_svc,
        ),
        patch("slidestein.classification.classifier.AnthropicSlideClassifier"),
        patch("slidestein.library.store.SlideLibrary", return_value=mock_lib),
    ):
        return runner.invoke(app, args), mock_svc


# ---------------------------------------------------------------------------
# Spec item 15 — command exists
# ---------------------------------------------------------------------------


class TestCommandExists:
    def test_classify_slide_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["classify-slide", "--help"])
        assert result.exit_code == 0
        assert "classify" in result.output.lower()


# ---------------------------------------------------------------------------
# Spec item 16 — slide number forwarded correctly
# ---------------------------------------------------------------------------


class TestSlideNumberForwarding:
    def test_slide_number_passed_to_service(self, three_slide_pptx: Path) -> None:
        result, mock_svc = _invoke([
            "classify-slide", str(three_slide_pptx), "2",
        ])
        assert result.exit_code == 0
        mock_svc.classify_slide.assert_called_once()
        assert mock_svc.classify_slide.call_args.kwargs["slide_number"] == 2


# ---------------------------------------------------------------------------
# Spec item 17 — JSON printed to stdout when no --output
# ---------------------------------------------------------------------------


class TestJsonToStdout:
    def test_json_to_stdout_without_output(self, three_slide_pptx: Path) -> None:
        profile = _fake_profile()
        result, _ = _invoke(["classify-slide", str(three_slide_pptx), "1"], profile=profile)
        assert result.exit_code == 0
        # stdout should be parseable JSON only (no other content in success path)
        parsed = json.loads(result.output)
        assert parsed["slide_id"] == profile.slide_id
        assert parsed["visual_archetype"] == profile.visual_archetype.value


# ---------------------------------------------------------------------------
# Spec item 18 — --output writes valid JSON
# ---------------------------------------------------------------------------


class TestOutputFileWritten:
    def test_output_file_is_written(self, three_slide_pptx: Path, tmp_path: Path) -> None:
        out = tmp_path / "profile.json"
        result, _ = _invoke([
            "classify-slide", str(three_slide_pptx), "1",
            "--output", str(out),
        ])
        assert result.exit_code == 0
        assert out.exists()
        # Parseable JSON
        json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Spec item 19 — output validates as SlideSemanticProfile
# ---------------------------------------------------------------------------


class TestOutputValidatesAsSemanticProfile:
    def test_written_json_validates_as_semantic_profile(
        self, three_slide_pptx: Path, tmp_path: Path
    ) -> None:
        profile = _fake_profile()
        out = tmp_path / "profile.json"
        _invoke([
            "classify-slide", str(three_slide_pptx), "1",
            "--output", str(out),
        ], profile=profile)

        loaded = SlideSemanticProfile.model_validate_json(out.read_text(encoding="utf-8"))
        assert loaded.slide_id == profile.slide_id
        assert loaded.visual_archetype == profile.visual_archetype
        assert loaded.primary_communication_job == profile.primary_communication_job


# ---------------------------------------------------------------------------
# Spec item 20 — classification failure exits non-zero
# ---------------------------------------------------------------------------


class TestClassificationFailureExitsNonZero:
    def test_classification_error_gives_exit_code_1(
        self, three_slide_pptx: Path
    ) -> None:
        result, _ = _invoke(
            ["classify-slide", str(three_slide_pptx), "1"],
            side_effect=SlideClassificationError("Claude API unavailable"),
        )
        assert result.exit_code == 1
        assert "classification error" in result.output.lower()


# ---------------------------------------------------------------------------
# Spec item 21 — invalid slide number exits non-zero
# ---------------------------------------------------------------------------


class TestInvalidSlideNumberExitsNonZero:
    def test_zero_slide_number_exits_1(self, three_slide_pptx: Path) -> None:
        # slide_number=0 is caught by the CLI guard (no service call).
        result = runner.invoke(app, ["classify-slide", str(three_slide_pptx), "0"])
        assert result.exit_code == 1

    def test_out_of_range_slide_number_exits_1(self, three_slide_pptx: Path) -> None:
        result, _ = _invoke(
            ["classify-slide", str(three_slide_pptx), "99"],
            side_effect=ValueError("Slide 99 does not exist; presentation contains 3 slide(s)."),
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Spec item 22 — missing PPTX exits non-zero
# ---------------------------------------------------------------------------


class TestMissingPptxExitsNonZero:
    def test_nonexistent_pptx_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "classify-slide",
            str(tmp_path / "nonexistent.pptx"),
            "1",
        ])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()
