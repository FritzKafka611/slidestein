"""Tests for the manager-review CLI command (M7).

ManagerReviewService is fully mocked — no real SAP AI Core calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.review.errors import ManagerReviewError
from slidestein.review.models import DimensionAssessment, ManagerReviewResult
from slidestein.review.providers.sap_aicore import ManagerReviewGenerationError
from slidestein.review.versions import MANAGER_REVIEW_SCHEMA_VERSION
from tests.test_review.conftest import (
    make_brief,
    make_complete_draft,
    make_model_output,
    make_slot_map,
)

runner = CliRunner()

_PATCH_FACTORY = "slidestein.review.providers.factory.create_manager_reviewer"


# ---------------------------------------------------------------------------
# File-write helpers
# ---------------------------------------------------------------------------


def _write_inputs(
    tmp_path: Path,
    is_complete: bool = True,
) -> tuple[Path, Path, Path]:
    brief = make_brief()
    draft = make_complete_draft(is_complete=is_complete)
    slot_map = make_slot_map()

    brief_file = tmp_path / "brief.json"
    brief_file.write_text(brief.model_dump_json(), encoding="utf-8")

    draft_file = tmp_path / "draft.json"
    draft_file.write_text(draft.model_dump_json(), encoding="utf-8")

    sm_file = tmp_path / "slot_map.json"
    sm_file.write_text(slot_map.model_dump_json(), encoding="utf-8")

    return brief_file, draft_file, sm_file


def _make_result() -> ManagerReviewResult:
    dim = DimensionAssessment(score=4, rationale="Good.")
    return ManagerReviewResult(
        slide_id="slide-test",
        deck_id=None,
        slide_number=2,
        recommendation="approve",
        average_score=4.0,
        answer_first_title=dim,
        core_message_clarity=dim,
        vertical_logic=dim,
        exhibit_title_consistency=dim,
        mece_structure=dim,
        content_density=dim,
        executive_summary="A solid draft with clear message hierarchy.",
    )


def _run(
    tmp_path: Path,
    *extra_args: str,
    is_complete: bool = True,
    mock_result=None,
    review_raises=None,
) -> "typer.testing.Result":  # type: ignore[name-defined]
    brief_file, draft_file, sm_file = _write_inputs(tmp_path, is_complete=is_complete)
    output_file = tmp_path / "result.json"

    mock_reviewer = MagicMock()

    if review_raises:
        mock_reviewer.review.side_effect = review_raises
    else:
        result = mock_result or _make_result()
        mock_reviewer.review.return_value = result

    mock_svc = MagicMock()
    if review_raises:
        mock_svc.review.side_effect = review_raises
    else:
        mock_svc.review.return_value = mock_result or _make_result()

    with patch(_PATCH_FACTORY, return_value=mock_reviewer), \
         patch("slidestein.review.service.ManagerReviewService", return_value=mock_svc):
        r = runner.invoke(
            app,
            [
                "manager-review",
                "--brief", str(brief_file),
                "--draft", str(draft_file),
                "--slot-map", str(sm_file),
                "--output", str(output_file),
                *extra_args,
            ],
            catch_exceptions=False,
        )
    return r


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_success_exits_zero(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.exit_code == 0


def test_approve_in_output(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert "APPROVE" in result.output or "approve" in result.output


def test_average_score_in_output(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert "4.00" in result.output or "4.0" in result.output


def test_output_file_written(tmp_path: Path) -> None:
    _run(tmp_path)
    out = tmp_path / "result.json"
    assert out.exists()


def test_output_json_round_trips(tmp_path: Path) -> None:
    _run(tmp_path)
    out = tmp_path / "result.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == MANAGER_REVIEW_SCHEMA_VERSION
    assert data["recommendation"] in ("approve", "revise")
    assert "average_score" in data
    assert "executive_summary" in data
    assert "slide_id" in data
    assert "slide_number" in data


def test_revise_recommendation_in_output(tmp_path: Path) -> None:
    dim = DimensionAssessment(score=2, rationale="Poor quality.")
    revise_result = ManagerReviewResult(
        slide_id="slide-test",
        deck_id=None,
        slide_number=2,
        recommendation="revise",
        average_score=2.0,
        answer_first_title=dim,
        core_message_clarity=dim,
        vertical_logic=dim,
        exhibit_title_consistency=dim,
        mece_structure=dim,
        content_density=dim,
        executive_summary="Needs significant revision.",
    )
    result = _run(tmp_path, mock_result=revise_result)
    assert "REVISE" in result.output or "revise" in result.output


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero(tmp_path: Path) -> None:
    brief_file, draft_file, sm_file = _write_inputs(tmp_path)
    with patch(_PATCH_FACTORY) as mock_factory:
        r = runner.invoke(
            app,
            [
                "manager-review",
                "--brief", str(brief_file),
                "--draft", str(draft_file),
                "--slot-map", str(sm_file),
                "--dry-run",
            ],
            catch_exceptions=False,
        )
    assert r.exit_code == 0
    mock_factory.assert_not_called()


def test_dry_run_shows_k_key_table(tmp_path: Path) -> None:
    brief_file, draft_file, sm_file = _write_inputs(tmp_path)
    with patch(_PATCH_FACTORY):
        r = runner.invoke(
            app,
            [
                "manager-review",
                "--brief", str(brief_file),
                "--draft", str(draft_file),
                "--slot-map", str(sm_file),
                "--dry-run",
            ],
            catch_exceptions=False,
        )
    assert "K1" in r.output or "K-key" in r.output.lower() or "mapping" in r.output.lower()


# ---------------------------------------------------------------------------
# Incomplete draft
# ---------------------------------------------------------------------------


def test_incomplete_draft_exits_nonzero(tmp_path: Path) -> None:
    result = _run(tmp_path, is_complete=False)
    assert result.exit_code != 0


def test_incomplete_draft_shows_error(tmp_path: Path) -> None:
    result = _run(tmp_path, is_complete=False)
    assert "complete" in result.output.lower() or "is_complete" in result.output


# ---------------------------------------------------------------------------
# Missing options
# ---------------------------------------------------------------------------


def test_missing_brief_option_exits_nonzero(tmp_path: Path) -> None:
    _, draft_file, sm_file = _write_inputs(tmp_path)
    r = runner.invoke(
        app,
        [
            "manager-review",
            "--draft", str(draft_file),
            "--slot-map", str(sm_file),
        ],
        catch_exceptions=True,
    )
    assert r.exit_code != 0


def test_invalid_brief_json_exits_nonzero(tmp_path: Path) -> None:
    brief_file = tmp_path / "bad_brief.json"
    brief_file.write_text("not json", encoding="utf-8")
    _, draft_file, sm_file = _write_inputs(tmp_path)
    with patch(_PATCH_FACTORY):
        r = runner.invoke(
            app,
            [
                "manager-review",
                "--brief", str(brief_file),
                "--draft", str(draft_file),
                "--slot-map", str(sm_file),
            ],
            catch_exceptions=False,
        )
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_generation_error_exits_nonzero(tmp_path: Path) -> None:
    result = _run(tmp_path, review_raises=ManagerReviewGenerationError("API failed"))
    assert result.exit_code != 0
    assert "Review failed" in result.output or "API failed" in result.output


def test_review_error_exits_nonzero(tmp_path: Path) -> None:
    result = _run(tmp_path, review_raises=ManagerReviewError("slot key K999 unknown"))
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# cp1252 safety
# ---------------------------------------------------------------------------


def test_output_cp1252_safe(tmp_path: Path) -> None:
    result = _run(tmp_path)
    try:
        result.output.encode("cp1252")
    except UnicodeEncodeError as exc:
        pytest.fail(f"Output contains cp1252-unsafe characters: {exc}")
