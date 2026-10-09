"""Tests for the draft-content CLI command.

All LLM calls are mocked via patch on create_content_draft_generator.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.drafting.analysis_models import (
    ContentDraftModelOutput,
    SlotContentGap,
    SlotReplacement,
)
from slidestein.drafting.providers.sap_aicore import ContentDraftGenerationError
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole


runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _capacity() -> SlotCapacity:
    return SlotCapacity(
        max_characters_estimate=120,
        max_lines_estimate=2,
        current_character_count=10,
        current_line_count=1,
        relative_capacity="medium",
    )


def _slot(slot_id: str, role: SlotRole = SlotRole.TITLE) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=1,
        shape_path=f"Slide/{slot_id}",
        slot_role=role,
        semantic_label="Test slot",
        editable=True,
        confidence=0.9,
        current_text="Old text",
        geometry={"x_ratio": 0.1, "y_ratio": 0.1, "width_ratio": 0.5, "height_ratio": 0.1},
        capacity=_capacity(),
    )


def _slot_map(slots: list[TemplateSlot] | None = None) -> TemplateSlotMap:
    return TemplateSlotMap(
        slide_id="slide-test",
        slide_number=5,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots or [_slot("s1")],
        non_editable_elements=[],
        excluded_editable_candidates=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Test map.",
        slot_analysis_input_fingerprint="fp",
    )


def _brief_dict() -> dict:
    return {
        "schema_version": "1.0",
        "original_request": "Show project status.",
        "key_message": "The deal is on track.",
        "slide_function": "content",
        "primary_communication_job": "inform",
        "secondary_communication_jobs": [],
        "storyline_roles": [],
        "required_content_elements": [],
        "preferred_visual_archetypes": [],
        "density": None,
        "assumptions": [],
        "open_questions": [],
    }


def _complete_output() -> ContentDraftModelOutput:
    return ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="The deal is on track.")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="Drafted title from source.",
    )


def _incomplete_output() -> ContentDraftModelOutput:
    return ContentDraftModelOutput(
        replacements=[],
        clear_slots=[],
        needs_input=[SlotContentGap(slot_key="K1", missing_information="Revenue missing.")],
        open_questions=["Who is the sponsor?"],
        drafting_summary="Could not complete.",
    )


# ---------------------------------------------------------------------------
# Helper to write temp files and run command
# ---------------------------------------------------------------------------


def _run(
    tmp_path: Path,
    *extra_args: str,
    brief_dict: dict | None = None,
    slot_map: TemplateSlotMap | None = None,
    generator_return: ContentDraftModelOutput | None = None,
    generator_raises: Exception | None = None,
) -> "typer.testing.Result":  # type: ignore[name-defined]
    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(brief_dict or _brief_dict()), encoding="utf-8")

    sm = slot_map or _slot_map()
    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(sm.model_dump_json(), encoding="utf-8")

    mock_gen = MagicMock()
    if generator_raises:
        mock_gen.generate.side_effect = generator_raises
    else:
        mock_gen.generate.return_value = generator_return or _complete_output()

    with patch(
        "slidestein.drafting.providers.factory.create_content_draft_generator",
        return_value=mock_gen,
    ):
        result = runner.invoke(
            app,
            [
                "draft-content",
                "--brief", str(brief_file),
                "--slot-map", str(sm_file),
                *extra_args,
            ],
            catch_exceptions=False,
        )
    return result


# ---------------------------------------------------------------------------
# Dry-run: zero LLM calls
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero(tmp_path):
    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(_brief_dict()), encoding="utf-8")
    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(_slot_map().model_dump_json(), encoding="utf-8")

    mock_gen = MagicMock()
    with patch(
        "slidestein.drafting.providers.factory.create_content_draft_generator",
        return_value=mock_gen,
    ):
        result = runner.invoke(
            app,
            [
                "draft-content",
                "--brief", str(brief_file),
                "--slot-map", str(sm_file),
                "--dry-run",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_gen.generate.assert_not_called()


def test_dry_run_shows_k_key_mapping(tmp_path):
    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(_brief_dict()), encoding="utf-8")
    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(_slot_map().model_dump_json(), encoding="utf-8")

    with patch(
        "slidestein.drafting.providers.factory.create_content_draft_generator",
        return_value=MagicMock(),
    ):
        result = runner.invoke(
            app,
            [
                "draft-content",
                "--brief", str(brief_file),
                "--slot-map", str(sm_file),
                "--dry-run",
            ],
            catch_exceptions=False,
        )

    assert "K1" in result.output


# ---------------------------------------------------------------------------
# Source material flags
# ---------------------------------------------------------------------------


def test_source_text_flag_accepted(tmp_path):
    result = _run(
        tmp_path,
        "--source-text", "Revenue: $5M.",
    )
    assert result.exit_code == 0


def test_source_file_flag_accepted(tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("Revenue: $5M.", encoding="utf-8")
    result = _run(tmp_path, "--source-file", str(src))
    assert result.exit_code == 0


def test_both_source_flags_rejected(tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("x", encoding="utf-8")

    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(_brief_dict()), encoding="utf-8")
    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(_slot_map().model_dump_json(), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "draft-content",
            "--brief", str(brief_file),
            "--slot-map", str(sm_file),
            "--source-file", str(src),
            "--source-text", "also text",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output.lower() or "mutually exclusive" in result.output


# ---------------------------------------------------------------------------
# Successful draft output
# ---------------------------------------------------------------------------


def test_success_exits_zero(tmp_path):
    result = _run(tmp_path)
    assert result.exit_code == 0


def test_complete_status_shown(tmp_path):
    result = _run(tmp_path, generator_return=_complete_output())
    assert "COMPLETE" in result.output


def test_incomplete_status_shown(tmp_path):
    result = _run(tmp_path, generator_return=_incomplete_output())
    assert "INCOMPLETE" in result.output or "needs_input" in result.output.lower()


def test_needs_input_info_displayed(tmp_path):
    result = _run(tmp_path, generator_return=_incomplete_output())
    assert "Revenue missing" in result.output


# ---------------------------------------------------------------------------
# JSON output roundtrip
# ---------------------------------------------------------------------------


def test_output_flag_writes_json(tmp_path):
    out_file = tmp_path / "draft.json"
    _run(tmp_path, "--output", str(out_file))
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "assignments" in data
    assert "is_complete" in data


def test_output_json_roundtrip(tmp_path):
    from slidestein.drafting.models import SlideContentDraft  # noqa: PLC0415

    out_file = tmp_path / "draft.json"
    _run(tmp_path, "--output", str(out_file))
    draft = SlideContentDraft.model_validate_json(out_file.read_text(encoding="utf-8"))
    assert draft.slide_id == "slide-test"
    assert draft.is_complete is True


# ---------------------------------------------------------------------------
# cp1252 safety
# ---------------------------------------------------------------------------


def test_cp1252_safe_output(tmp_path):
    """Any non-cp1252 chars in slot labels must not crash Rich on Windows."""
    unicode_slot = _slot("s1", role=SlotRole.BODY_TEXT)
    unicode_slot = TemplateSlot(
        slot_id="s1",
        shape_id=1,
        shape_path="Slide/s1",
        slot_role=SlotRole.BODY_TEXT,
        semantic_label="中文标签",  # Chinese chars
        editable=True,
        confidence=0.9,
        current_text="Example",
        geometry={"x_ratio": 0.1, "y_ratio": 0.1, "width_ratio": 0.5, "height_ratio": 0.1},
        capacity=_capacity(),
    )
    output = ContentDraftModelOutput(
        replacements=[SlotReplacement(slot_key="K1", text="Drafted text.")],
        clear_slots=[],
        needs_input=[],
        open_questions=[],
        drafting_summary="Chinese label test.",
    )
    result = _run(tmp_path, slot_map=_slot_map([unicode_slot]), generator_return=output)
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_generation_error_exits_one(tmp_path):
    result = _run(
        tmp_path,
        generator_raises=ContentDraftGenerationError("Mock failure"),
    )
    assert result.exit_code == 1


def test_missing_brief_file_exits_one(tmp_path):
    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(_slot_map().model_dump_json(), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "draft-content",
            "--brief", str(tmp_path / "nonexistent.json"),
            "--slot-map", str(sm_file),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
