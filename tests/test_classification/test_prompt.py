"""Tests for the classification prompt builder and image encoding helpers.

No Anthropic API calls are made in this module.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from slidestein.classification.prompt import (
    SUPPORTED_MEDIA_TYPES,
    build_classification_prompt,
    build_messages,
    encode_image,
)
from slidestein.domain.models import SlideClassificationInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(**overrides) -> SlideClassificationInput:
    defaults: dict = dict(
        slide_id="abc123-001",
        extracted_text="Revenue declined 15% QoQ.",
        structural_metadata={"shape_count": 3, "chart_count": 1},
    )
    defaults.update(overrides)
    return SlideClassificationInput(**defaults)


# ---------------------------------------------------------------------------
# Prompt tests (spec items 1–6)
# ---------------------------------------------------------------------------


class TestBuildClassificationPrompt:
    def test_prompt_contains_slide_id(self) -> None:
        inp = _make_input(slide_id="test-slide-42")
        prompt = build_classification_prompt(inp)
        assert "test-slide-42" in prompt

    def test_prompt_contains_extracted_text(self) -> None:
        inp = _make_input(extracted_text="Key insight: margins are declining sharply.")
        prompt = build_classification_prompt(inp)
        assert "Key insight: margins are declining sharply." in prompt

    def test_prompt_contains_deterministic_structural_metadata(self) -> None:
        inp = _make_input(structural_metadata={"z_count": 2, "a_count": 1})
        prompt = build_classification_prompt(inp)
        # Serialised with sort_keys=True, so a_count comes before z_count
        expected_json = json.dumps({"a_count": 1, "z_count": 2}, indent=2, sort_keys=True)
        assert expected_json in prompt

    def test_prompt_explains_canonical_communication_jobs(self) -> None:
        inp = _make_input()
        prompt = build_classification_prompt(inp)
        for job in ("explain", "summarise", "recommend", "show_relationship", "show_drivers"):
            assert job in prompt, f"Expected communication job {job!r} in prompt"

    def test_prompt_explains_canonical_storyline_roles(self) -> None:
        inp = _make_input()
        prompt = build_classification_prompt(inp)
        for role in ("context", "diagnosis", "insight", "implication", "recommendation"):
            assert role in prompt, f"Expected storyline role {role!r} in prompt"

    def test_prompt_explains_canonical_visual_archetypes(self) -> None:
        inp = _make_input()
        prompt = build_classification_prompt(inp)
        for archetype in ("bar_chart", "waterfall", "mixed_exhibit", "matrix", "pyramid"):
            assert archetype in prompt, f"Expected visual archetype {archetype!r} in prompt"

    def test_prompt_distinguishes_structural_pattern_from_business_content(self) -> None:
        inp = _make_input()
        prompt = build_classification_prompt(inp)
        # Prompt must explicitly guide on layout grammar vs business content
        lower = prompt.lower()
        assert "layout" in lower or "layout grammar" in lower
        assert "business content" in lower or "not" in lower

    def test_prompt_indicates_preview_available_yes(self, tmp_path: Path) -> None:
        preview = tmp_path / "slide.png"
        preview.write_bytes(b"FAKEPNG")
        inp = _make_input(preview_path=preview)
        prompt = build_classification_prompt(inp)
        assert "VISUAL PREVIEW AVAILABLE: yes" in prompt

    def test_prompt_indicates_preview_available_no(self) -> None:
        inp = _make_input()
        prompt = build_classification_prompt(inp)
        assert "VISUAL PREVIEW AVAILABLE: no" in prompt

    def test_no_extracted_text_handled_gracefully(self) -> None:
        inp = _make_input(extracted_text="   ")
        prompt = build_classification_prompt(inp)
        assert "(no extracted text)" in prompt


# ---------------------------------------------------------------------------
# encode_image tests (spec items 7–8)
# ---------------------------------------------------------------------------


class TestEncodeImage:
    def test_png_encoded_with_image_png(self, tmp_path: Path) -> None:
        p = tmp_path / "slide.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        media_type, b64 = encode_image(p)
        assert media_type == "image/png"
        assert base64.b64decode(b64) == b"\x89PNG\r\n\x1a\nFAKE"

    def test_jpg_encoded_with_image_jpeg(self, tmp_path: Path) -> None:
        p = tmp_path / "slide.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0FAKEJPEG")
        media_type, b64 = encode_image(p)
        assert media_type == "image/jpeg"

    def test_jpeg_ext_encoded_with_image_jpeg(self, tmp_path: Path) -> None:
        p = tmp_path / "slide.jpeg"
        p.write_bytes(b"FAKEJPEG")
        media_type, _ = encode_image(p)
        assert media_type == "image/jpeg"

    def test_unsupported_extension_raises_value_error(self, tmp_path: Path) -> None:
        p = tmp_path / "slide.gif"
        p.write_bytes(b"GIF89a")
        with pytest.raises(ValueError, match="Unsupported preview image type"):
            encode_image(p)

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.png"
        with pytest.raises(FileNotFoundError, match="not found"):
            encode_image(p)

    def test_supported_media_types_has_three_entries(self) -> None:
        assert ".png" in SUPPORTED_MEDIA_TYPES
        assert ".jpg" in SUPPORTED_MEDIA_TYPES
        assert ".jpeg" in SUPPORTED_MEDIA_TYPES


# ---------------------------------------------------------------------------
# build_messages tests (spec item 11)
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_image_block_before_text_block(self, tmp_path: Path) -> None:
        preview = tmp_path / "slide.png"
        preview.write_bytes(b"FAKEPNG")
        inp = _make_input(preview_path=preview)
        messages = build_messages(inp)
        assert len(messages) == 1
        content = messages[0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "image", "image block must come first"
        assert content[1]["type"] == "text"

    def test_no_preview_produces_single_text_block(self) -> None:
        inp = _make_input()
        messages = build_messages(inp)
        content = messages[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"

    def test_image_block_has_correct_structure(self, tmp_path: Path) -> None:
        preview = tmp_path / "slide.png"
        preview.write_bytes(b"FAKEPNG")
        inp = _make_input(preview_path=preview)
        messages = build_messages(inp)
        img_block = messages[0]["content"][0]
        assert img_block["source"]["type"] == "base64"
        assert img_block["source"]["media_type"] == "image/png"
        assert img_block["source"]["data"] == base64.b64encode(b"FAKEPNG").decode("ascii")

    def test_missing_preview_propagates_file_not_found(self, tmp_path: Path) -> None:
        inp = _make_input(preview_path=tmp_path / "missing.png")
        with pytest.raises(FileNotFoundError):
            build_messages(inp)

    def test_unsupported_type_propagates_value_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "slide.bmp"
        bad.write_bytes(b"BM")
        inp = _make_input(preview_path=bad)
        with pytest.raises(ValueError, match="Unsupported"):
            build_messages(inp)
