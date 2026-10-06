"""Tests for build_slide_classification_input and structural metadata helpers.

No Anthropic API calls and no PowerPoint COM calls are made here.
All tests use minimal PPTX files created in-memory with python-pptx.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches

from slidestein.classification.input_builder import (
    build_slide_classification_input,
    _build_structural_metadata,
    _extract_text,
)
from slidestein.domain.models import SlideClassificationInput, make_slide_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def single_slide_pptx(tmp_path: Path) -> Path:
    """One-slide PPTX with a title placeholder and a text box."""
    prs = Presentation()
    layout = prs.slide_layouts[0]  # Title Slide layout (title + subtitle placeholders)
    slide = prs.slides.add_slide(layout)

    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 0:
            ph.text = "Revenue Declined 15% QoQ"
        elif ph.placeholder_format.idx == 1:
            ph.text = "Drivers: macro headwinds and pricing pressure"

    pptx_path = tmp_path / "single.pptx"
    prs.save(str(pptx_path))
    return pptx_path


@pytest.fixture
def blank_slide_pptx(tmp_path: Path) -> Path:
    """One-slide PPTX with a blank layout (no placeholders, one text box)."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank layout
    txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    txBox.text_frame.text = "Standalone text box"
    pptx_path = tmp_path / "blank.pptx"
    prs.save(str(pptx_path))
    return pptx_path


# ---------------------------------------------------------------------------
# FileNotFoundError and ValueError — pre-parsing guard
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_missing_pptx_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            build_slide_classification_input(tmp_path / "ghost.pptx", 1)

    def test_non_pptx_suffix_raises_value_error(self, tmp_path: Path) -> None:
        pdf = tmp_path / "deck.pdf"
        pdf.write_bytes(b"%%PDF-1.4")
        with pytest.raises(ValueError, match=".pdf"):
            build_slide_classification_input(pdf, 1)

    def test_slide_number_zero_raises_value_error(self, single_slide_pptx: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            build_slide_classification_input(single_slide_pptx, 0)

    def test_slide_number_too_high_raises_value_error(self, single_slide_pptx: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            build_slide_classification_input(single_slide_pptx, 99)

    def test_out_of_range_message_mentions_slide_count(self, single_slide_pptx: Path) -> None:
        with pytest.raises(ValueError, match="contains 1 slide"):
            build_slide_classification_input(single_slide_pptx, 5)


# ---------------------------------------------------------------------------
# Slide ID stability and scheme
# ---------------------------------------------------------------------------


class TestSlideIdGeneration:
    def test_slide_id_is_deterministic(self, single_slide_pptx: Path) -> None:
        result_a = build_slide_classification_input(single_slide_pptx, 1)
        result_b = build_slide_classification_input(single_slide_pptx, 1)
        assert result_a.slide_id == result_b.slide_id

    def test_slide_id_matches_make_slide_id_scheme(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        fingerprint = hashlib.sha256(single_slide_pptx.read_bytes()).hexdigest()
        expected = make_slide_id(fingerprint, 1)
        assert result.slide_id == expected

    def test_different_slide_numbers_produce_different_ids(
        self, three_slide_pptx: Path
    ) -> None:
        r1 = build_slide_classification_input(three_slide_pptx, 1)
        r2 = build_slide_classification_input(three_slide_pptx, 2)
        assert r1.slide_id != r2.slide_id


# ---------------------------------------------------------------------------
# Extracted text
# ---------------------------------------------------------------------------


class TestExtractedText:
    def test_extracted_text_is_included(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        assert isinstance(result.extracted_text, str)
        assert len(result.extracted_text) > 0

    def test_extracted_text_contains_title(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        assert "Revenue Declined" in result.extracted_text

    def test_blank_slide_extracted_text_is_string(self, blank_slide_pptx: Path) -> None:
        result = build_slide_classification_input(blank_slide_pptx, 1)
        assert isinstance(result.extracted_text, str)


# ---------------------------------------------------------------------------
# Structural metadata
# ---------------------------------------------------------------------------


class TestStructuralMetadata:
    def test_metadata_contains_required_top_level_keys(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        md = result.structural_metadata
        for key in (
            "slide_number",
            "slide_width",
            "slide_height",
            "shape_count",
            "text_shape_count",
            "chart_count",
            "table_count",
            "picture_count",
            "group_count",
            "text_shapes",
        ):
            assert key in md, f"Missing metadata key: {key!r}"

    def test_metadata_is_json_serialisable(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        # Should not raise
        serialised = json.dumps(result.structural_metadata)
        assert len(serialised) > 2

    def test_slide_number_in_metadata_matches_argument(
        self, three_slide_pptx: Path
    ) -> None:
        for n in (1, 2, 3):
            result = build_slide_classification_input(three_slide_pptx, n)
            assert result.structural_metadata["slide_number"] == n

    def test_shape_counts_are_non_negative_ints(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        md = result.structural_metadata
        for key in ("shape_count", "text_shape_count", "chart_count", "table_count",
                    "picture_count", "group_count"):
            assert isinstance(md[key], int) and md[key] >= 0

    def test_text_shapes_is_a_list(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        assert isinstance(result.structural_metadata["text_shapes"], list)

    def test_text_shape_entries_have_required_fields(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        for entry in result.structural_metadata["text_shapes"]:
            for field in ("shape_id", "shape_name", "text", "left", "top",
                          "width", "height", "placeholder_type"):
                assert field in entry, f"text_shape missing field {field!r}"

    def test_slide_dimensions_are_positive_ints(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        assert result.structural_metadata["slide_width"] > 0
        assert result.structural_metadata["slide_height"] > 0


# ---------------------------------------------------------------------------
# Preview path forwarding
# ---------------------------------------------------------------------------


class TestPreviewPath:
    def test_preview_path_forwarded_to_result(
        self, single_slide_pptx: Path, tmp_path: Path
    ) -> None:
        preview = tmp_path / "preview.png"
        result = build_slide_classification_input(single_slide_pptx, 1, preview_path=preview)
        assert result.preview_path == preview

    def test_no_preview_path_defaults_to_none(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        assert result.preview_path is None

    def test_preview_path_need_not_exist_at_call_time(
        self, single_slide_pptx: Path, tmp_path: Path
    ) -> None:
        nonexistent = tmp_path / "future_preview.png"
        assert not nonexistent.exists()
        # Should not raise even though the file does not exist yet.
        result = build_slide_classification_input(single_slide_pptx, 1, preview_path=nonexistent)
        assert result.preview_path == nonexistent


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_slide_classification_input(self, single_slide_pptx: Path) -> None:
        result = build_slide_classification_input(single_slide_pptx, 1)
        assert isinstance(result, SlideClassificationInput)
