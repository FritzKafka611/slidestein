"""CLI tests for recover-slide command.

All provider calls are mocked; zero API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.revision.models import RevisionRoute
from slidestein.structural.models import (
    StructuralRecoveryRoute,
)

from .conftest import (
    make_brief,
    make_complete_draft,
    make_m9_plan,
    make_manager_review,
    make_slot_map,
    make_visual_qa,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures: write JSON files
# ---------------------------------------------------------------------------


@pytest.fixture()
def input_files(tmp_path: Path):
    """Write all required JSON input files and placeholder PPTXs."""
    brief = make_brief()
    draft = make_complete_draft()
    slot_map = make_slot_map()
    manager_rev = make_manager_review()
    visual_qa_r = make_visual_qa()
    m9_plan = make_m9_plan(route=RevisionRoute.TEMPLATE_RESELECTION)

    brief_path = tmp_path / "brief.json"
    draft_path = tmp_path / "draft.json"
    slot_map_path = tmp_path / "slot_map.json"
    manager_review_path = tmp_path / "manager_review.json"
    visual_qa_path = tmp_path / "visual_qa.json"
    m9_plan_path = tmp_path / "m9_plan.json"
    template_pptx = tmp_path / "template.pptx"
    generated_pptx = tmp_path / "generated.pptx"
    output_pptx = tmp_path / "output.pptx"

    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    draft_path.write_text(draft.model_dump_json(), encoding="utf-8")
    slot_map_path.write_text(slot_map.model_dump_json(), encoding="utf-8")
    manager_review_path.write_text(manager_rev.model_dump_json(), encoding="utf-8")
    visual_qa_path.write_text(visual_qa_r.model_dump_json(), encoding="utf-8")
    m9_plan_path.write_text(m9_plan.model_dump_json(), encoding="utf-8")
    template_pptx.write_bytes(b"fake pptx")
    generated_pptx.write_bytes(b"fake pptx")

    return {
        "brief": brief_path,
        "draft": draft_path,
        "slot_map": slot_map_path,
        "manager_review": manager_review_path,
        "visual_qa": visual_qa_path,
        "m9_plan": m9_plan_path,
        "template_pptx": template_pptx,
        "generated_pptx": generated_pptx,
        "output_pptx": output_pptx,
    }


def _base_args(f: dict, tmp_path: Path) -> list[str]:
    return [
        "recover-slide",
        "--brief", str(f["brief"]),
        "--draft", str(f["draft"]),
        "--slot-map", str(f["slot_map"]),
        "--manager-review", str(f["manager_review"]),
        "--visual-qa", str(f["visual_qa"]),
        "--m9-plan", str(f["m9_plan"]),
        "--template-pptx", str(f["template_pptx"]),
        "--generated-pptx", str(f["generated_pptx"]),
        "--output-pptx", str(f["output_pptx"]),
    ]


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero(tmp_path, input_files):
    f = input_files
    with patch(
        "slidestein.structural.diagnosis.resolve_slide_by_stable_id",
        return_value=(2, "native-001"),
    ), patch(
        "slidestein.structural.diagnosis._read_slide_space_geometries",
        side_effect=[
            {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
             "K2": {"x": 100, "y": 600, "width": 500, "height": 800}},
            {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
             "K2": {"x": 100, "y": 600, "width": 500, "height": 800}},
        ],
    ), patch(
        "slidestein.structural.diagnosis.StructuralDiagnosisService._verify_content_identity",
    ):
        result = runner.invoke(app, _base_args(f, tmp_path) + ["--dry-run"])

    assert result.exit_code == 0
    assert "Dry-run" in result.output


def test_dry_run_no_api_calls(tmp_path, input_files):
    f = input_files
    # StructuralRecoveryOrchestrator should NOT be imported/constructed in dry-run
    with patch(
        "slidestein.structural.diagnosis.resolve_slide_by_stable_id",
        return_value=(2, "native-001"),
    ), patch(
        "slidestein.structural.diagnosis._read_slide_space_geometries",
        side_effect=[
            {"K1": {"x": 100}, "K2": {"x": 200}},
            {"K1": {"x": 100}, "K2": {"x": 200}},
        ],
    ), patch(
        "slidestein.structural.diagnosis.StructuralDiagnosisService._verify_content_identity",
    ), patch(
        "slidestein.structural.orchestrator.StructuralRecoveryOrchestrator.recover"
    ) as mock_recover:
        runner.invoke(app, _base_args(f, tmp_path) + ["--dry-run"])
        mock_recover.assert_not_called()


def test_dry_run_shows_route(tmp_path, input_files):
    f = input_files
    with patch(
        "slidestein.structural.diagnosis.resolve_slide_by_stable_id",
        return_value=(2, "native-001"),
    ), patch(
        "slidestein.structural.diagnosis._read_slide_space_geometries",
        side_effect=[
            {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
             "K2": {"x": 100, "y": 600, "width": 500, "height": 800}},
            {"K1": {"x": 100, "y": 200, "width": 500, "height": 300},
             "K2": {"x": 100, "y": 600, "width": 500, "height": 800}},
        ],
    ), patch(
        "slidestein.structural.diagnosis.StructuralDiagnosisService._verify_content_identity",
    ):
        result = runner.invoke(app, _base_args(f, tmp_path) + ["--dry-run"])

    assert "reselect_template" in result.output or "rebuild" in result.output


# ---------------------------------------------------------------------------
# Input validation errors
# ---------------------------------------------------------------------------


def test_source_file_and_text_mutually_exclusive(tmp_path, input_files):
    f = input_files
    result = runner.invoke(
        app,
        _base_args(f, tmp_path) + [
            "--source-file", str(f["brief"]),
            "--source-text", "inline text",
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or "exclusive" in result.output.lower()


def test_invalid_brief_json_exits_nonzero(tmp_path, input_files):
    f = input_files
    f["brief"].write_text("NOT VALID JSON", encoding="utf-8")
    result = runner.invoke(app, _base_args(f, tmp_path) + ["--dry-run"])
    assert result.exit_code != 0


def test_invalid_m9_plan_json_exits_nonzero(tmp_path, input_files):
    f = input_files
    f["m9_plan"].write_text("{}", encoding="utf-8")
    result = runner.invoke(app, _base_args(f, tmp_path) + ["--dry-run"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Full run — mock orchestrator
# ---------------------------------------------------------------------------


def _make_mock_result():
    from slidestein.structural.models import StructuralRecoveryResult
    from .conftest import make_manager_review, make_visual_qa

    plan = make_m9_plan()
    from slidestein.structural.models import StructuralRecoveryPlan, StructuralRecoveryRoute
    recovery_plan = StructuralRecoveryPlan(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
        reasons=["Test."],
        current_template_slide_id="slide-test-001",
        requires_candidate_retrieval=True,
        requires_selection_call=True,
        requires_redraft_call=True,
    )
    return StructuralRecoveryResult(
        route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
        status="reselected",
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        plan=recovery_plan,
        content_changed=True,
        manager_review_effective=make_manager_review(recommendation="approve"),
        visual_qa_after=make_visual_qa(recommendation="pass"),
        final_ready=True,
        model_calls={
            "retrieval_embedding": 1,
            "template_selection": 1,
            "drafting": 1,
            "manager_review": 1,
            "visual_qa": 1,
        },
    )


def test_full_run_exits_zero(tmp_path, input_files):
    f = input_files
    mock_result = _make_mock_result()

    with patch(
        "slidestein.structural.orchestrator.StructuralRecoveryOrchestrator.recover",
        return_value=mock_result,
    ), patch(
        "slidestein.structural.providers.factory.create_structural_template_selector",
    ), patch(
        "slidestein.drafting.providers.factory.create_content_draft_generator",
    ), patch(
        "slidestein.review.providers.factory.create_manager_reviewer",
    ), patch(
        "slidestein.qa.providers.factory.create_visual_qa_reviewer",
    ), patch(
        "slidestein.retrieval.providers.factory.create_embedding_provider",
    ), patch(
        "slidestein.retrieval.store.SlideVectorStore",
    ), patch(
        "slidestein.retrieval.hybrid.HybridSlideSearch",
    ), patch(
        "slidestein.library.store.SlideLibrary.__enter__", return_value=MagicMock()
    ), patch(
        "slidestein.library.store.SlideLibrary.__exit__", return_value=False
    ):
        result = runner.invoke(app, _base_args(f, tmp_path))

    assert result.exit_code == 0


def test_full_run_writes_output_json(tmp_path, input_files):
    f = input_files
    output_json = tmp_path / "result.json"
    mock_result = _make_mock_result()

    with patch(
        "slidestein.structural.orchestrator.StructuralRecoveryOrchestrator.recover",
        return_value=mock_result,
    ), patch("slidestein.structural.providers.factory.create_structural_template_selector"), \
       patch("slidestein.drafting.providers.factory.create_content_draft_generator"), \
       patch("slidestein.review.providers.factory.create_manager_reviewer"), \
       patch("slidestein.qa.providers.factory.create_visual_qa_reviewer"), \
       patch("slidestein.retrieval.providers.factory.create_embedding_provider"), \
       patch("slidestein.retrieval.store.SlideVectorStore"), \
       patch("slidestein.retrieval.hybrid.HybridSlideSearch"), \
       patch("slidestein.library.store.SlideLibrary.__enter__", return_value=MagicMock()), \
       patch("slidestein.library.store.SlideLibrary.__exit__", return_value=False):
        result = runner.invoke(
            app, _base_args(f, tmp_path) + ["--output", str(output_json)]
        )

    assert result.exit_code == 0
    assert output_json.exists()
    parsed = json.loads(output_json.read_text(encoding="utf-8"))
    assert parsed["status"] == "reselected"
    assert parsed["final_ready"] is True


def test_full_run_shows_final_ready_yes(tmp_path, input_files):
    f = input_files
    mock_result = _make_mock_result()

    with patch(
        "slidestein.structural.orchestrator.StructuralRecoveryOrchestrator.recover",
        return_value=mock_result,
    ), patch("slidestein.structural.providers.factory.create_structural_template_selector"), \
       patch("slidestein.drafting.providers.factory.create_content_draft_generator"), \
       patch("slidestein.review.providers.factory.create_manager_reviewer"), \
       patch("slidestein.qa.providers.factory.create_visual_qa_reviewer"), \
       patch("slidestein.retrieval.providers.factory.create_embedding_provider"), \
       patch("slidestein.retrieval.store.SlideVectorStore"), \
       patch("slidestein.retrieval.hybrid.HybridSlideSearch"), \
       patch("slidestein.library.store.SlideLibrary.__enter__", return_value=MagicMock()), \
       patch("slidestein.library.store.SlideLibrary.__exit__", return_value=False):
        result = runner.invoke(app, _base_args(f, tmp_path))

    assert "YES" in result.output or "yes" in result.output.lower()
