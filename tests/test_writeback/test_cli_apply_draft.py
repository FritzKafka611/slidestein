"""Tests for the apply-draft CLI command (M6).

PowerPointWritebackService is fully mocked — no real COM, no real PPTX files.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.drafting.models import (
    SlideContentDraft,
    SlotDraftAction,
    SlotDraftAssignment,
)
from slidestein.slots.models import SlotCapacity, TemplateSlot, TemplateSlotMap
from slidestein.slots.roles import SlotRole
from slidestein.writeback.errors import PowerPointWritebackError
from slidestein.writeback.models import WritebackOperation, WritebackPlan, PowerPointWritebackResult
from slidestein.writeback.versions import WRITEBACK_SCHEMA_VERSION


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


def _slot(slot_id: str = "s1", shape_id: int = 7) -> TemplateSlot:
    return TemplateSlot(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=str(shape_id),
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        editable=True,
        confidence=0.9,
        current_text="Old title",
        geometry={"x_ratio": 0.05, "y_ratio": 0.04, "width_ratio": 0.9, "height_ratio": 0.1},
        capacity=_capacity(),
    )


def _slot_map(slots: list[TemplateSlot] | None = None) -> TemplateSlotMap:
    return TemplateSlotMap(
        slide_id="slide-test",
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
        slots=slots or [_slot()],
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="Test map.",
        slot_analysis_input_fingerprint="fp-test",
    )


def _assignment(slot_id: str = "s1", shape_id: int = 7) -> SlotDraftAssignment:
    return SlotDraftAssignment(
        slot_id=slot_id,
        shape_id=shape_id,
        shape_path=str(shape_id),
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        action=SlotDraftAction.REPLACE,
        text="New title text",
        capacity_characters=120,
        capacity_utilization=0.1,
        max_lines_estimate=2,
    )


def _complete_draft(is_complete: bool = True) -> SlideContentDraft:
    return SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Test key message.",
        assignments=[_assignment()],
        drafting_summary="Test draft.",
        is_complete=is_complete,
    )


def _incomplete_draft() -> SlideContentDraft:
    incomplete_assign = SlotDraftAssignment(
        slot_id="s1",
        shape_id=7,
        shape_path="7",
        slot_role=SlotRole.TITLE,
        semantic_label="Title",
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
        missing_information="Need client name.",
        capacity_characters=120,
        capacity_utilization=0.0,
        max_lines_estimate=2,
    )
    return SlideContentDraft(
        slide_id="slide-test",
        slide_number=2,
        brief_key_message="Test.",
        assignments=[incomplete_assign],
        drafting_summary="Incomplete.",
        is_complete=False,
    )


def _plan(output_pptx: Path) -> WritebackPlan:
    return WritebackPlan(
        schema_version=WRITEBACK_SCHEMA_VERSION,
        slide_id="slide-test",
        deck_id=None,
        slide_number=2,
        resolved_slide_number=2,
        native_slide_id=None,
        source_pptx=Path("/src/deck.pptx"),
        output_pptx=output_pptx,
        operations=[
            WritebackOperation(
                slot_id="s1",
                shape_id=7,
                shape_path="7",
                action=SlotDraftAction.REPLACE,
                text="New title text",
            )
        ],
        replacement_count=1,
        clear_count=0,
        before_structure_fingerprint="abcdef01",
    )


def _success_result(output_pptx: Path) -> PowerPointWritebackResult:
    return PowerPointWritebackResult(
        source_pptx="/src/deck.pptx",
        output_pptx=str(output_pptx),
        slide_id="slide-test",
        slide_number=2,
        resolved_slide_number=2,
        replacement_count=1,
        clear_count=0,
        applied_assignments=[{
            "slot_id": "s1",
            "shape_id": 7,
            "shape_path": "7",
            "action": "replace",
            "expected_text": "New title text",
            "verified_text": "New title text",
            "verified": True,
        }],
        verification_passed=True,
        warnings=[],
        before_structure_fingerprint="abcdef01",
        after_structure_fingerprint="abcdef01",
    )


def _write_files(
    tmp_path: Path,
    draft: SlideContentDraft | None = None,
    slot_map: TemplateSlotMap | None = None,
) -> tuple[Path, Path, Path]:
    """Write draft and slot_map JSON to tmp_path, return (draft_path, sm_path, source_path)."""
    d = draft or _complete_draft()
    sm = slot_map or _slot_map()

    draft_file = tmp_path / "draft.json"
    draft_file.write_text(d.model_dump_json(), encoding="utf-8")

    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(sm.model_dump_json(), encoding="utf-8")

    source_file = tmp_path / "source.pptx"
    source_file.touch()

    return draft_file, sm_file, source_file


def _run(
    tmp_path: Path,
    *extra_args: str,
    draft: SlideContentDraft | None = None,
    slot_map: TemplateSlotMap | None = None,
    mock_plan: WritebackPlan | None = None,
    mock_result: PowerPointWritebackResult | None = None,
    preflight_raises: Exception | None = None,
    apply_raises: Exception | None = None,
) -> "typer.testing.Result":  # type: ignore[name-defined]
    draft_file, sm_file, source_file = _write_files(tmp_path, draft, slot_map)
    output_file = tmp_path / "output.pptx"

    plan = mock_plan or _plan(output_file)
    result = mock_result or _success_result(output_file)

    mock_svc = MagicMock()
    if preflight_raises:
        mock_svc.preflight.side_effect = preflight_raises
    else:
        mock_svc.preflight.return_value = plan
    if apply_raises:
        mock_svc.apply.side_effect = apply_raises
    else:
        mock_svc.apply.return_value = result

    with patch(
        "slidestein.writeback.service.PowerPointWritebackService",
        return_value=mock_svc,
    ):
        r = runner.invoke(
            app,
            [
                "apply-draft",
                "--draft", str(draft_file),
                "--slot-map", str(sm_file),
                "--source", str(source_file),
                "--output", str(output_file),
                *extra_args,
            ],
            catch_exceptions=False,
        )
    return r


# ---------------------------------------------------------------------------
# Dry-run: preflight only, no apply called
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run")
    assert result.exit_code == 0


def test_dry_run_shows_plan_details(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run")
    assert "slide-test" in result.output
    assert "replace" in result.output.lower() or "Replace" in result.output


def test_dry_run_does_not_call_apply(tmp_path: Path) -> None:
    draft_file, sm_file, source_file = _write_files(tmp_path)
    output_file = tmp_path / "output.pptx"
    plan = _plan(output_file)

    mock_svc = MagicMock()
    mock_svc.preflight.return_value = plan

    with patch(
        "slidestein.writeback.service.PowerPointWritebackService",
        return_value=mock_svc,
    ):
        runner.invoke(
            app,
            [
                "apply-draft",
                "--draft", str(draft_file),
                "--slot-map", str(sm_file),
                "--source", str(source_file),
                "--output", str(output_file),
                "--dry-run",
            ],
            catch_exceptions=False,
        )

    mock_svc.apply.assert_not_called()


def test_dry_run_shows_dry_run_label(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run")
    assert "dry run" in result.output.lower() or "Dry run" in result.output


# ---------------------------------------------------------------------------
# Full run: success
# ---------------------------------------------------------------------------


def test_success_exits_zero(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.exit_code == 0


def test_success_output_path_in_output(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert "output.pptx" in result.output


def test_success_verification_passed_shown(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert "PASSED" in result.output or "passed" in result.output.lower()


# ---------------------------------------------------------------------------
# Preflight failure → exit non-zero
# ---------------------------------------------------------------------------


def test_incomplete_draft_preflight_failure(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        preflight_raises=PowerPointWritebackError("Draft is not complete"),
    )
    assert result.exit_code != 0
    assert "Preflight failed" in result.output or "not complete" in result.output


def test_source_not_found_preflight_failure(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        preflight_raises=PowerPointWritebackError("Source PPTX not found"),
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Apply failure → exit non-zero
# ---------------------------------------------------------------------------


def test_apply_failure_exits_nonzero(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        apply_raises=PowerPointWritebackError("COM write failed"),
    )
    assert result.exit_code != 0
    assert "Write-back failed" in result.output or "COM write failed" in result.output


# ---------------------------------------------------------------------------
# Missing required options
# ---------------------------------------------------------------------------


def test_missing_draft_option_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "apply-draft",
            "--slot-map", str(tmp_path / "sm.json"),
            "--source", str(tmp_path / "src.pptx"),
            "--output", str(tmp_path / "out.pptx"),
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
