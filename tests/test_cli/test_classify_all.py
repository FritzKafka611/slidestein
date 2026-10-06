"""Tests for the classify-all CLI command.

No real Anthropic API calls — classifier is mocked throughout.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.classification.classifier import SlideClassificationError
from slidestein.cli import app
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideRecord,
    SlideSemanticProfile,
    StorylineRole,
    VisualArchetype,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(slide_id: str, slide_number: int = 1) -> SlideRecord:
    return SlideRecord(
        slide_id=slide_id,
        deck_fingerprint="fp-test",
        source_deck_path=Path("/fake/deck.pptx"),
        slide_number=slide_number,
        deck_id="deck-uuid4",
        native_slide_id=256 + slide_number,
        content_fingerprint="cfp-" + slide_id,
        structure_fingerprint="sfp-" + slide_id,
        is_active=True,
    )


def _make_profile(slide_id: str) -> SlideSemanticProfile:
    return SlideSemanticProfile(
        slide_id=slide_id,
        primary_communication_job=CommunicationJob.EXPLAIN,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.TEXT_HEAVY,
        structural_pattern="Bullet list under headline.",
        density=DensityLevel.MEDIUM,
        description="A slide with bullets.",
    )


def _invoke_classify_all(
    args: list[str],
    active_records: list[SlideRecord],
    classify_side_effects: list | None = None,
    is_current_map: dict[str, bool] | None = None,
) -> MagicMock:
    """Invoke classify-all with library and service fully mocked."""
    mock_lib = MagicMock()
    mock_lib.__enter__.return_value = mock_lib
    mock_lib.list_active_slides.return_value = active_records

    # By default nothing is current
    def _is_current(slide_id, version, fp):
        if is_current_map is None:
            return False
        return is_current_map.get(slide_id, False)

    mock_lib.classification_is_current.side_effect = _is_current
    mock_lib.upsert_classification.return_value = None

    mock_svc = MagicMock()
    mock_svc._classifier._model = "claude-test"

    if classify_side_effects is not None:
        mock_svc.classify_slide.side_effect = classify_side_effects
    else:
        # Default: return a profile for every record
        def _classify(pptx_path, slide_number, slide_id=None, existing_preview_path=None):
            return _make_profile(slide_id or "fallback")
        mock_svc.classify_slide.side_effect = _classify

    with (
        patch("slidestein.library.store.SlideLibrary", return_value=mock_lib),
        patch("slidestein.classification.service.SlideClassificationService", return_value=mock_svc),
        patch("slidestein.classification.classifier.AnthropicSlideClassifier"),
        patch("slidestein.pptx.python_pptx_adapter.PythonPptxAdapter"),
    ):
        result = runner.invoke(app, ["classify-all"] + args)

    return result, mock_lib, mock_svc


# ---------------------------------------------------------------------------
# Basic tests
# ---------------------------------------------------------------------------


class TestClassifyAllCommand:
    def test_help_exits_zero(self):
        result = runner.invoke(app, ["classify-all", "--help"])
        assert result.exit_code == 0

    def test_empty_library_exits_zero(self):
        result, _, _ = _invoke_classify_all([], active_records=[])
        assert result.exit_code == 0
        assert "No active slides" in result.output

    def test_classifies_unclassified_slides(self):
        records = [_make_record("s1", 1), _make_record("s2", 2)]
        result, mock_lib, mock_svc = _invoke_classify_all([], active_records=records)
        assert result.exit_code == 0
        assert mock_svc.classify_slide.call_count == 2
        assert mock_lib.upsert_classification.call_count == 2

    def test_skips_current_classifications(self):
        records = [_make_record("s1", 1)]
        result, mock_lib, mock_svc = _invoke_classify_all(
            [],
            active_records=records,
            is_current_map={"s1": True},
        )
        assert result.exit_code == 0
        mock_svc.classify_slide.assert_not_called()
        assert "1" in result.output  # skipped count

    def test_force_reclassifies_current(self):
        records = [_make_record("s1", 1)]
        result, mock_lib, mock_svc = _invoke_classify_all(
            ["--force"],
            active_records=records,
            is_current_map={"s1": True},
        )
        assert result.exit_code == 0
        mock_svc.classify_slide.assert_called_once()

    def test_one_failure_does_not_abort(self):
        records = [_make_record("s1", 1), _make_record("s2", 2)]

        # First call fails, second succeeds
        side_effects = [
            SlideClassificationError("API error"),
            _make_profile("s2"),
        ]
        result, mock_lib, mock_svc = _invoke_classify_all(
            [],
            active_records=records,
            classify_side_effects=side_effects,
        )
        # exit code 1 because there was a failure
        assert result.exit_code == 1
        # But the second slide was still processed
        assert mock_lib.upsert_classification.call_count == 1

    def test_summary_shows_counts(self):
        records = [_make_record("s1", 1), _make_record("s2", 2)]
        result, _, _ = _invoke_classify_all([], active_records=records)
        assert result.exit_code == 0
        assert "2" in result.output  # classified count

    def test_upsert_called_with_correct_slide_id(self):
        records = [_make_record("slide-uuid-001", 1)]
        result, mock_lib, _ = _invoke_classify_all([], active_records=records)
        assert result.exit_code == 0
        call_kwargs = mock_lib.upsert_classification.call_args.kwargs
        assert call_kwargs.get("slide_id") == "slide-uuid-001"
