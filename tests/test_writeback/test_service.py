"""Tests for writeback/service.py — PowerPointWritebackService.

All COM and python-pptx operations are mocked.
No real PPTX files, no COM, no LLM.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.drafting.models import SlotDraftAction
from slidestein.writeback.errors import PowerPointWritebackError
from slidestein.writeback.models import (
    WritebackOperation,
    WritebackPlan,
    WritebackReceipt,
)
from slidestein.writeback.service import PowerPointWritebackService
from slidestein.writeback.versions import WRITEBACK_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(
    slide_id: str = "slide-001",
    slide_number: int = 2,
    resolved_slide_number: int | None = None,
    operations: list[WritebackOperation] | None = None,
    replacement_count: int = 1,
    clear_count: int = 0,
    output_pptx: Path | None = None,
) -> WritebackPlan:
    if output_pptx is None:
        output_pptx = Path("/out/deck.pptx")
    if resolved_slide_number is None:
        resolved_slide_number = slide_number
    return WritebackPlan(
        schema_version=WRITEBACK_SCHEMA_VERSION,
        slide_id=slide_id,
        deck_id="deck-abc",
        slide_number=slide_number,
        resolved_slide_number=resolved_slide_number,
        native_slide_id=256,
        source_pptx=Path("/src/deck.pptx"),
        output_pptx=output_pptx,
        operations=operations or [
            WritebackOperation(
                slot_id="s1",
                shape_id=7,
                shape_path="7",
                action=SlotDraftAction.REPLACE,
                text="New title",
            )
        ],
        replacement_count=replacement_count,
        clear_count=clear_count,
        before_structure_fingerprint="abcdef01",
        # before_format_fingerprint="" (default — skips format check)
        # before_deck_native_ids=[] (default — skips non-target check)
    )


def _receipt(verified: bool = True, slot_id: str = "s1") -> WritebackReceipt:
    return WritebackReceipt(
        slot_id=slot_id,
        shape_id=7,
        shape_path="7",
        action="replace",
        expected_text="New title",
        verified_text="New title" if verified else "Wrong text",
        verified=verified,
    )


def _fake_execute(plan: WritebackPlan) -> None:
    """Create the temp output file so os.replace succeeds."""
    plan.output_pptx.parent.mkdir(parents=True, exist_ok=True)
    plan.output_pptx.write_bytes(b"fake pptx content")


# ---------------------------------------------------------------------------
# preflight delegation
# ---------------------------------------------------------------------------


def test_preflight_calls_preflight_function() -> None:
    svc = PowerPointWritebackService()
    mock_plan = _make_plan()
    mock_request = MagicMock()

    with patch("slidestein.writeback.service._preflight", return_value=mock_plan) as mock_pre:
        result = svc.preflight(mock_request)

    mock_pre.assert_called_once_with(mock_request)
    assert result is mock_plan


# ---------------------------------------------------------------------------
# apply — success path (atomic temp + os.replace)
# ---------------------------------------------------------------------------


def test_apply_success_returns_result(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=True)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan", side_effect=_fake_execute),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="abcdef01"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
    ):
        result = svc.apply(plan)

    assert result.verification_passed is True
    assert result.slide_id == "slide-001"
    assert result.schema_version == WRITEBACK_SCHEMA_VERSION
    assert result.replacement_count == 1
    assert result.clear_count == 0
    assert result.before_structure_fingerprint == "abcdef01"
    assert result.after_structure_fingerprint == "abcdef01"
    assert result.resolved_slide_number == 2
    assert out_file.exists()


def test_apply_result_contains_receipts(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=True, slot_id="s1")]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan", side_effect=_fake_execute),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="fp2"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
    ):
        result = svc.apply(plan)

    assert len(result.applied_assignments) == 1
    assert result.applied_assignments[0]["slot_id"] == "s1"
    assert result.applied_assignments[0]["verified"] is True


def test_apply_no_temp_file_remains_after_success(tmp_path: Path) -> None:
    """After successful promotion, temp file must be gone (os.replace moves it)."""
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=True)]

    created_temp: list[Path] = []

    def capturing_execute(p: WritebackPlan) -> None:
        _fake_execute(p)
        created_temp.append(p.output_pptx)

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan", side_effect=capturing_execute),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="fp"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
    ):
        svc.apply(plan)

    assert len(created_temp) == 1
    temp_path = created_temp[0]
    assert temp_path != out_file  # temp was different from final
    assert not temp_path.exists()  # temp gone
    assert out_file.exists()  # final present


# ---------------------------------------------------------------------------
# apply — COM failure → existing final output untouched (atomic safety)
# ---------------------------------------------------------------------------


def test_apply_com_failure_existing_output_preserved(tmp_path: Path) -> None:
    """Atomic safety: COM failure must not touch the existing final output."""
    out_file = tmp_path / "out.pptx"
    out_file.write_bytes(b"existing content")
    plan = _make_plan(output_pptx=out_file)

    svc = PowerPointWritebackService()

    with (
        patch(
            "slidestein.writeback.service.execute_plan",
            side_effect=PowerPointWritebackError("COM exploded"),
        ),
    ):
        with pytest.raises(PowerPointWritebackError, match="COM exploded"):
            svc.apply(plan)

    # Existing final output must be byte-for-byte untouched
    assert out_file.read_bytes() == b"existing content"


def test_apply_com_failure_no_temp_file_remains(tmp_path: Path) -> None:
    """Any temp created before COM failure must be cleaned up."""
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)

    svc = PowerPointWritebackService()

    with (
        patch(
            "slidestein.writeback.service.execute_plan",
            side_effect=PowerPointWritebackError("COM exploded"),
        ),
    ):
        with pytest.raises(PowerPointWritebackError):
            svc.apply(plan)

    # No temp file in the output directory
    temps = list(tmp_path.glob("._m6tmp_*"))
    assert temps == []


# ---------------------------------------------------------------------------
# apply — text verification failure → temp deleted, final untouched
# ---------------------------------------------------------------------------


def test_apply_text_verification_failure_raises(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=False)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan"),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, False)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="fp"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
    ):
        with pytest.raises(PowerPointWritebackError, match="Verification failed"):
            svc.apply(plan)


def test_apply_text_verification_failure_mentions_slot(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=False, slot_id="slot-abc")]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan"),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, False)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="fp"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
    ):
        with pytest.raises(PowerPointWritebackError, match="slot-abc"):
            svc.apply(plan)


def test_apply_text_failure_existing_output_preserved(tmp_path: Path) -> None:
    """Text verification failure: existing output must survive."""
    out_file = tmp_path / "out.pptx"
    out_file.write_bytes(b"original content")
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=False)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan"),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, False)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="fp"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
    ):
        with pytest.raises(PowerPointWritebackError):
            svc.apply(plan)

    assert out_file.read_bytes() == b"original content"


# ---------------------------------------------------------------------------
# apply — structure verification failure
# ---------------------------------------------------------------------------


def test_apply_structure_failure_raises(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=True)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan"),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="deadbeef"),
        patch("slidestein.writeback.service.verify_structure", return_value=(False, ["Fingerprint changed"])),
    ):
        with pytest.raises(PowerPointWritebackError, match="Verification failed"):
            svc.apply(plan)


def test_apply_structure_failure_existing_output_preserved(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    out_file.write_bytes(b"safe original")
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=True)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan"),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="deadbeef"),
        patch("slidestein.writeback.service.verify_structure", return_value=(False, ["Fingerprint changed"])),
    ):
        with pytest.raises(PowerPointWritebackError):
            svc.apply(plan)

    assert out_file.read_bytes() == b"safe original"


# ---------------------------------------------------------------------------
# apply — warnings propagated
# ---------------------------------------------------------------------------


def test_apply_warnings_included_in_result(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    plan = _make_plan(output_pptx=out_file)
    receipts = [_receipt(verified=True)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan", side_effect=_fake_execute),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch(
            "slidestein.writeback.service.compute_after_structure_fingerprint",
            return_value=None,
        ),
        patch(
            "slidestein.writeback.service.verify_structure",
            return_value=(True, ["Structure fingerprint could not be computed"]),
        ),
    ):
        result = svc.apply(plan)

    assert result.verification_passed is True
    assert any("fingerprint" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# apply — non-target verification (with before_deck_native_ids set)
# ---------------------------------------------------------------------------


def test_apply_non_target_structure_verified(tmp_path: Path) -> None:
    """Non-target verification runs when before_deck_native_ids is set."""
    out_file = tmp_path / "out.pptx"
    from dataclasses import replace as dc_replace
    plan = _make_plan(output_pptx=out_file)
    plan = dc_replace(
        plan,
        before_deck_native_ids=[256, 300],
        before_deck_structure={"256": "fp_target", "300": "fp_other"},
    )
    receipts = [_receipt(verified=True)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan", side_effect=_fake_execute),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="abcdef01"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
        patch(
            "slidestein.writeback.service.compute_deck_structure_snapshot",
            return_value=([256, 300], {"256": "fp_target", "300": "fp_other"}),
        ),
        patch(
            "slidestein.writeback.service.verify_non_target_structure",
            return_value=(True, True, []),
        ),
    ):
        result = svc.apply(plan)

    assert result.non_target_structure_verified is True


def test_apply_non_target_structure_changed_raises(tmp_path: Path) -> None:
    out_file = tmp_path / "out.pptx"
    from dataclasses import replace as dc_replace
    plan = _make_plan(output_pptx=out_file)
    plan = dc_replace(
        plan,
        before_deck_native_ids=[256, 300],
        before_deck_structure={"256": "fp_target", "300": "fp_other"},
    )
    receipts = [_receipt(verified=True)]

    svc = PowerPointWritebackService()

    with (
        patch("slidestein.writeback.service.execute_plan"),
        patch("slidestein.writeback.service.verify_text", return_value=(receipts, True)),
        patch("slidestein.writeback.service.compute_after_structure_fingerprint", return_value="abcdef01"),
        patch("slidestein.writeback.service.verify_structure", return_value=(True, [])),
        patch(
            "slidestein.writeback.service.compute_deck_structure_snapshot",
            return_value=([256, 300], {"256": "fp_target", "300": "fp_different"}),
        ),
        patch(
            "slidestein.writeback.service.verify_non_target_structure",
            return_value=(True, False, ["Non-target slide structure changed"]),
        ),
    ):
        with pytest.raises(PowerPointWritebackError, match="Verification failed"):
            svc.apply(plan)
