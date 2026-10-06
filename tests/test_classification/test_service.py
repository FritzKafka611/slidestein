"""Tests for SlideClassificationService (spec section 16 items 1–14).

No Anthropic API calls are made.  All tests inject mock classifier and renderer.
The source PPTX is a minimal in-memory fixture; python-pptx runs for real.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from slidestein.classification.classifier import SlideClassificationError
from slidestein.classification.service import SlideClassificationService
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideClassificationInput,
    SlideSemanticProfile,
    StorylineRole,
    VisualArchetype,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_profile() -> SlideSemanticProfile:
    return SlideSemanticProfile(
        slide_id="placeholder-001",
        primary_communication_job=CommunicationJob.EXPLAIN,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.BAR_CHART,
        structural_pattern="Full-width bar chart with insight callout.",
        density=DensityLevel.MEDIUM,
        description="Quarterly revenue exhibit.",
    )


@pytest.fixture
def mock_renderer() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_classifier(fake_profile: SlideSemanticProfile) -> MagicMock:
    c = MagicMock()
    c.classify.return_value = fake_profile
    return c


@pytest.fixture
def service(
    mock_classifier: MagicMock, mock_renderer: MagicMock
) -> SlideClassificationService:
    return SlideClassificationService(
        classifier=mock_classifier,
        renderer=mock_renderer,
    )


# ---------------------------------------------------------------------------
# Spec item 1 — correct slide number passed to extraction
# ---------------------------------------------------------------------------


class TestSlideNumberForwarding:
    def test_slide_number_in_structural_metadata(
        self, service: SlideClassificationService, mock_classifier: MagicMock,
        three_slide_pptx: Path
    ) -> None:
        service.classify_slide(three_slide_pptx, 2)
        inp: SlideClassificationInput = mock_classifier.classify.call_args[0][0]
        assert inp.structural_metadata["slide_number"] == 2


# ---------------------------------------------------------------------------
# Spec item 2 — stable slide ID
# ---------------------------------------------------------------------------


class TestSlideIdStability:
    def test_same_pptx_and_slide_number_produces_same_id(
        self, service: SlideClassificationService, mock_classifier: MagicMock,
        three_slide_pptx: Path
    ) -> None:
        service.classify_slide(three_slide_pptx, 1)
        id1 = mock_classifier.classify.call_args[0][0].slide_id
        service.classify_slide(three_slide_pptx, 1)
        id2 = mock_classifier.classify.call_args[0][0].slide_id
        assert id1 == id2 and id1 != ""


# ---------------------------------------------------------------------------
# Spec items 3–4 — extracted text and metadata in input
# ---------------------------------------------------------------------------


class TestClassificationInputContents:
    def test_extracted_text_in_classification_input(
        self, service: SlideClassificationService, mock_classifier: MagicMock,
        three_slide_pptx: Path
    ) -> None:
        service.classify_slide(three_slide_pptx, 1)
        inp: SlideClassificationInput = mock_classifier.classify.call_args[0][0]
        assert isinstance(inp.extracted_text, str)
        assert len(inp.extracted_text) > 0  # fixture slides have titles

    def test_structural_metadata_included_in_input(
        self, service: SlideClassificationService, mock_classifier: MagicMock,
        three_slide_pptx: Path
    ) -> None:
        service.classify_slide(three_slide_pptx, 1)
        inp: SlideClassificationInput = mock_classifier.classify.call_args[0][0]
        assert "shape_count" in inp.structural_metadata
        assert "text_shapes" in inp.structural_metadata


# ---------------------------------------------------------------------------
# Spec item 5 — rendered preview path included
# ---------------------------------------------------------------------------


class TestPreviewPathInInput:
    def test_preview_path_set_in_classification_input(
        self, service: SlideClassificationService, mock_classifier: MagicMock,
        three_slide_pptx: Path
    ) -> None:
        service.classify_slide(three_slide_pptx, 1)
        inp: SlideClassificationInput = mock_classifier.classify.call_args[0][0]
        assert inp.preview_path is not None
        assert inp.preview_path.suffix == ".png"


# ---------------------------------------------------------------------------
# Spec item 6 — classifier receives exactly one SlideClassificationInput
# ---------------------------------------------------------------------------


class TestClassifierCallContract:
    def test_classifier_called_once_with_classification_input(
        self, service: SlideClassificationService, mock_classifier: MagicMock,
        three_slide_pptx: Path
    ) -> None:
        service.classify_slide(three_slide_pptx, 1)
        mock_classifier.classify.assert_called_once()
        positional_args = mock_classifier.classify.call_args[0]
        assert isinstance(positional_args[0], SlideClassificationInput)


# ---------------------------------------------------------------------------
# Spec item 7 — returned profile propagated unchanged
# ---------------------------------------------------------------------------


class TestProfilePropagation:
    def test_returned_profile_is_classifiers_return_value(
        self,
        service: SlideClassificationService,
        mock_classifier: MagicMock,
        fake_profile: SlideSemanticProfile,
        three_slide_pptx: Path,
    ) -> None:
        result = service.classify_slide(three_slide_pptx, 1)
        assert result is fake_profile


# ---------------------------------------------------------------------------
# Spec items 8–9 — invalid inputs rejected before any API call
# ---------------------------------------------------------------------------


class TestInputRejection:
    def test_invalid_slide_number_raises_value_error(
        self, service: SlideClassificationService, three_slide_pptx: Path
    ) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            service.classify_slide(three_slide_pptx, 99)

    def test_missing_pptx_raises_file_not_found(
        self, service: SlideClassificationService, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            service.classify_slide(tmp_path / "ghost.pptx", 1)


# ---------------------------------------------------------------------------
# Spec item 10 — extraction failure propagated
# ---------------------------------------------------------------------------


class TestExtractionFailure:
    def test_extraction_value_error_propagates(
        self, service: SlideClassificationService, three_slide_pptx: Path
    ) -> None:
        with patch(
            "slidestein.classification.service.build_slide_classification_input",
            side_effect=ValueError("corrupted PPTX"),
        ):
            with pytest.raises(ValueError, match="corrupted PPTX"):
                service.classify_slide(three_slide_pptx, 1)


# ---------------------------------------------------------------------------
# Spec item 11 — rendering failure propagated
# ---------------------------------------------------------------------------


class TestRenderingFailure:
    def test_rendering_runtime_error_propagates(
        self,
        service: SlideClassificationService,
        mock_renderer: MagicMock,
        three_slide_pptx: Path,
    ) -> None:
        mock_renderer.render_preview.side_effect = RuntimeError("No rendering backend")
        with pytest.raises(RuntimeError, match="No rendering backend"):
            service.classify_slide(three_slide_pptx, 1)


# ---------------------------------------------------------------------------
# Spec item 12 — classifier failure propagated
# ---------------------------------------------------------------------------


class TestClassificationFailure:
    def test_classification_error_propagates(
        self,
        service: SlideClassificationService,
        mock_classifier: MagicMock,
        three_slide_pptx: Path,
    ) -> None:
        mock_classifier.classify.side_effect = SlideClassificationError("API down")
        with pytest.raises(SlideClassificationError, match="API down"):
            service.classify_slide(three_slide_pptx, 1)


# ---------------------------------------------------------------------------
# Spec item 13 — temporary directory cleaned up
# ---------------------------------------------------------------------------


class TestTemporaryDirectoryCleanup:
    def test_temp_directory_deleted_after_classify_slide(
        self, service: SlideClassificationService, three_slide_pptx: Path
    ) -> None:
        recorded: list[Path] = []
        _Real = TemporaryDirectory

        class _Tracking:
            def __init__(self) -> None:
                self._real = _Real()

            def __enter__(self) -> str:
                tmp_str: str = self._real.__enter__()
                recorded.append(Path(tmp_str))
                return tmp_str

            def __exit__(self, *args: object) -> None:
                self._real.__exit__(*args)

        with patch("slidestein.classification.service.TemporaryDirectory", _Tracking):
            service.classify_slide(three_slide_pptx, 1)

        assert len(recorded) == 1
        assert not recorded[0].exists(), "Temp directory must be cleaned up after classify_slide"


# ---------------------------------------------------------------------------
# Spec item 14 — source presentation not modified
# ---------------------------------------------------------------------------


class TestSourceNotModified:
    def test_source_pptx_bytes_unchanged_after_classification(
        self, service: SlideClassificationService, three_slide_pptx: Path
    ) -> None:
        before = three_slide_pptx.read_bytes()
        service.classify_slide(three_slide_pptx, 1)
        after = three_slide_pptx.read_bytes()
        assert before == after, "Source PPTX must not be modified during classification"
