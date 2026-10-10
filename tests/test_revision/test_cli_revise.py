"""CLI tests for revise-slide command (M9).

BoundedRevisionOrchestrator and all three factory creates are fully mocked —
no real SAP AI Core calls, no COM write-back, no filesystem PPTX operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.revision.errors import RevisionError
from slidestein.revision.models import RevisionCycleResult, RevisionPlan, RevisionRoute
from slidestein.revision.versions import REVISION_SCHEMA_VERSION
from tests.test_revision.conftest import (
    make_brief,
    make_complete_draft,
    make_manager_review,
    make_slot_map,
    make_visual_qa,
)

runner = CliRunner()

_PATCH_CONTENT_FACTORY = "slidestein.revision.providers.factory.create_content_reviser"
_PATCH_M7_FACTORY = "slidestein.review.providers.factory.create_manager_reviewer"
_PATCH_M8_FACTORY = "slidestein.qa.providers.factory.create_visual_qa_reviewer"
_PATCH_ORCHESTRATOR = "slidestein.revision.service.BoundedRevisionOrchestrator"


# ---------------------------------------------------------------------------
# Input-file writers
# ---------------------------------------------------------------------------


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    """Write all required JSON inputs + placeholder PPTX paths.

    Returns (brief, draft, slot_map, manager_review, visual_qa, template_pptx, output_pptx).
    PPTX paths are created as empty files so Path.exists() passes if needed.
    """
    brief = make_brief()
    draft = make_complete_draft()
    slot_map = make_slot_map()
    mr = make_manager_review()
    vq = make_visual_qa()

    brief_f = tmp_path / "brief.json"
    brief_f.write_text(brief.model_dump_json(), encoding="utf-8")

    draft_f = tmp_path / "draft.json"
    draft_f.write_text(draft.model_dump_json(), encoding="utf-8")

    sm_f = tmp_path / "slot_map.json"
    sm_f.write_text(slot_map.model_dump_json(), encoding="utf-8")

    mr_f = tmp_path / "manager_review.json"
    mr_f.write_text(mr.model_dump_json(), encoding="utf-8")

    vq_f = tmp_path / "visual_qa.json"
    vq_f.write_text(vq.model_dump_json(), encoding="utf-8")

    template_pptx = tmp_path / "template.pptx"
    template_pptx.touch()

    output_pptx = tmp_path / "output.pptx"

    return brief_f, draft_f, sm_f, mr_f, vq_f, template_pptx, output_pptx


def _make_finalize_result() -> RevisionCycleResult:
    plan = RevisionPlan(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        route=RevisionRoute.FINALIZE,
        reasons=["Manager review approved and visual QA passed."],
        requires_model_call=False,
    )
    return RevisionCycleResult(
        route=RevisionRoute.FINALIZE,
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        plan=plan,
        status="finalized",
        final_ready=True,
        model_calls={"revision": 0, "manager_review": 0, "visual_qa": 0},
    )


def _run_full(
    tmp_path: Path,
    *extra_args: str,
    mock_result: RevisionCycleResult | None = None,
    orchestrate_raises=None,
) -> "typer.testing.Result":  # type: ignore[name-defined]
    """Run revise-slide full mode with all services mocked."""
    brief_f, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)

    mock_orch = MagicMock()
    if orchestrate_raises:
        mock_orch.revise.side_effect = orchestrate_raises
    else:
        mock_orch.revise.return_value = mock_result or _make_finalize_result()

    output_f = tmp_path / "result.json"

    with patch(_PATCH_CONTENT_FACTORY, return_value=MagicMock()), \
         patch(_PATCH_M7_FACTORY, return_value=MagicMock()), \
         patch(_PATCH_M8_FACTORY, return_value=MagicMock()), \
         patch(_PATCH_ORCHESTRATOR, return_value=mock_orch):
        r = runner.invoke(
            app,
            [
                "revise-slide",
                "--brief", str(brief_f),
                "--draft", str(draft_f),
                "--slot-map", str(sm_f),
                "--manager-review", str(mr_f),
                "--visual-qa", str(vq_f),
                "--template-pptx", str(tpl_pptx),
                "--output-pptx", str(out_pptx),
                "--artifacts-dir", str(tmp_path / "artifacts"),
                "--output", str(output_f),
                *extra_args,
            ],
            catch_exceptions=False,
        )
    return r


# ---------------------------------------------------------------------------
# Happy path — full run
# ---------------------------------------------------------------------------


def test_full_run_exits_zero(tmp_path: Path) -> None:
    r = _run_full(tmp_path)
    assert r.exit_code == 0


def test_full_run_shows_route(tmp_path: Path) -> None:
    r = _run_full(tmp_path)
    assert "finalize" in r.output.lower()


def test_full_run_shows_api_calls(tmp_path: Path) -> None:
    r = _run_full(tmp_path)
    assert "0" in r.output or "api_calls" in r.output.lower() or "API calls" in r.output


def test_full_run_writes_output_json(tmp_path: Path) -> None:
    _run_full(tmp_path)
    out = tmp_path / "result.json"
    assert out.exists()


def test_full_run_output_json_round_trips(tmp_path: Path) -> None:
    _run_full(tmp_path)
    out = tmp_path / "result.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == REVISION_SCHEMA_VERSION
    assert "route" in data
    assert "model_calls" in data
    assert "final_ready" in data


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            "--visual-qa", str(vq_f),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    assert r.exit_code == 0


def test_dry_run_shows_route(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            "--visual-qa", str(vq_f),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    # With both approve/pass, route should be finalize
    assert "finalize" in r.output.lower()


def test_dry_run_does_not_call_factory(tmp_path: Path) -> None:
    """Dry-run must not invoke any factory function (zero API calls)."""
    brief_f, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    with patch(_PATCH_CONTENT_FACTORY) as mock_factory:
        runner.invoke(
            app,
            [
                "revise-slide",
                "--brief", str(brief_f),
                "--draft", str(draft_f),
                "--slot-map", str(sm_f),
                "--manager-review", str(mr_f),
                "--visual-qa", str(vq_f),
                "--template-pptx", str(tpl_pptx),
                "--output-pptx", str(out_pptx),
                "--dry-run",
            ],
            catch_exceptions=False,
        )
    mock_factory.assert_not_called()


def test_dry_run_shows_rationale(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            "--visual-qa", str(vq_f),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    assert "Reason" in r.output or "reason" in r.output.lower()


# ---------------------------------------------------------------------------
# Extra fields in manager review JSON stripped correctly
# ---------------------------------------------------------------------------


def test_extra_mr_fields_stripped(tmp_path: Path) -> None:
    """Manager review JSON with extra 'case' and 'slide' fields must be accepted."""
    brief_f, draft_f, sm_f, _, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)

    mr = make_manager_review()
    mr_dict = json.loads(mr.model_dump_json())
    mr_dict["case"] = "Case A"  # extra field from M7 eval runner
    mr_dict["slide"] = "Slide 2"  # extra field from M7 eval runner

    mr_f = tmp_path / "mr_with_extras.json"
    mr_f.write_text(json.dumps(mr_dict), encoding="utf-8")

    with patch(_PATCH_CONTENT_FACTORY, return_value=MagicMock()), \
         patch(_PATCH_M7_FACTORY, return_value=MagicMock()), \
         patch(_PATCH_M8_FACTORY, return_value=MagicMock()), \
         patch(_PATCH_ORCHESTRATOR, return_value=MagicMock(revise=MagicMock(return_value=_make_finalize_result()))):
        r = runner.invoke(
            app,
            [
                "revise-slide",
                "--brief", str(brief_f),
                "--draft", str(draft_f),
                "--slot-map", str(sm_f),
                "--manager-review", str(mr_f),
                "--visual-qa", str(vq_f),
                "--template-pptx", str(tpl_pptx),
                "--output-pptx", str(out_pptx),
                "--artifacts-dir", str(tmp_path / "artifacts"),
            ],
            catch_exceptions=False,
        )
    assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Missing required options
# ---------------------------------------------------------------------------


def test_missing_manager_review_option_exits_nonzero(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, _, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            # missing --manager-review
            "--visual-qa", str(vq_f),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
        ],
        catch_exceptions=True,
    )
    assert r.exit_code != 0


def test_missing_visual_qa_option_exits_nonzero(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, mr_f, _, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            # missing --visual-qa
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
        ],
        catch_exceptions=True,
    )
    assert r.exit_code != 0


def test_invalid_brief_json_exits_nonzero(tmp_path: Path) -> None:
    _, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    bad_brief = tmp_path / "bad_brief.json"
    bad_brief.write_text("not json at all", encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(bad_brief),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            "--visual-qa", str(vq_f),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    assert r.exit_code != 0


def test_invalid_visual_qa_json_exits_nonzero(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, mr_f, _, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    bad_vq = tmp_path / "bad_vq.json"
    bad_vq.write_text("{}", encoding="utf-8")  # missing required fields
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            "--visual-qa", str(bad_vq),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_revision_error_exits_nonzero(tmp_path: Path) -> None:
    r = _run_full(tmp_path, orchestrate_raises=RevisionError("Content revision failed."))
    assert r.exit_code != 0


def test_revision_error_shows_message(tmp_path: Path) -> None:
    r = _run_full(tmp_path, orchestrate_raises=RevisionError("Content revision failed."))
    assert "Revision failed" in r.output


def test_source_file_and_source_text_mutually_exclusive(tmp_path: Path) -> None:
    brief_f, draft_f, sm_f, mr_f, vq_f, tpl_pptx, out_pptx = _write_inputs(tmp_path)
    src_file = tmp_path / "src.txt"
    src_file.write_text("Source material.", encoding="utf-8")
    r = runner.invoke(
        app,
        [
            "revise-slide",
            "--brief", str(brief_f),
            "--draft", str(draft_f),
            "--slot-map", str(sm_f),
            "--manager-review", str(mr_f),
            "--visual-qa", str(vq_f),
            "--template-pptx", str(tpl_pptx),
            "--output-pptx", str(out_pptx),
            "--source-file", str(src_file),
            "--source-text", "Inline source.",
            "--dry-run",
        ],
        catch_exceptions=False,
    )
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# cp1252 safety
# ---------------------------------------------------------------------------


def test_output_cp1252_safe(tmp_path: Path) -> None:
    r = _run_full(tmp_path)
    try:
        r.output.encode("cp1252")
    except UnicodeEncodeError as exc:
        pytest.fail(f"Output contains cp1252-unsafe characters: {exc}")
