"""Tests for the analyze-slots CLI command."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.slots.models import TemplateSlotMap
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION

runner = CliRunner()

_PATCH_LIB = "slidestein.library.store.SlideLibrary"
_PATCH_FACTORY = "slidestein.slots.providers.factory.create_slot_semantic_analyzer"
_PATCH_SERVICE = "slidestein.slots.service.TemplateSlotAnalysisService"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_slot_map(slide_id: str = "slide-abc") -> TemplateSlotMap:
    return TemplateSlotMap(
        slide_id=slide_id,
        slide_number=2,
        slide_width=9144000,
        slide_height=5143500,
        slots=[],
        non_editable_elements=[],
        unsupported_elements=[],
        groups=[],
        analysis_summary="A roadmap slide with title and five workstream labels.",
        slot_analysis_input_fingerprint="a" * 64,
    )


def _make_mock_service(slot_map: TemplateSlotMap | None = None) -> MagicMock:
    svc = MagicMock()
    svc.analyze.return_value = slot_map or _make_slot_map()
    return svc


def _invoke(args: list[str], service: MagicMock | None = None) -> object:
    """Invoke analyze-slots with all external dependencies patched."""
    svc = service or _make_mock_service()
    is_dry_run = "--dry-run" in args

    with ExitStack() as stack:
        mock_lib_cls = stack.enter_context(patch(_PATCH_LIB))
        mock_lib_cls.return_value.__enter__.return_value = MagicMock()
        mock_lib_cls.return_value.__exit__.return_value = None

        # Replace the SERVICE CLASS with a mock whose instantiation returns svc
        stack.enter_context(patch(_PATCH_SERVICE, return_value=svc))

        # Factory only called when not dry_run
        if not is_dry_run:
            stack.enter_context(patch(_PATCH_FACTORY, return_value=MagicMock()))

        return runner.invoke(app, ["analyze-slots"] + args)


# ---------------------------------------------------------------------------
# Basic success
# ---------------------------------------------------------------------------


class TestBasicSuccess:
    def test_exits_zero(self):
        result = _invoke(["slide-abc"])
        assert result.exit_code == 0, result.output

    def test_slide_id_rendered(self):
        result = _invoke(["slide-abc"])
        assert "slide-abc" in result.output

    def test_summary_rendered(self):
        result = _invoke(["slide-abc"])
        assert "roadmap" in result.output.lower() or "workstream" in result.output.lower()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_exits_zero(self):
        result = _invoke(["slide-abc", "--dry-run"])
        assert result.exit_code == 0, result.output

    def test_dry_run_label_shown(self):
        result = _invoke(["slide-abc", "--dry-run"])
        lower = result.output.lower()
        assert "dry run" in lower or "no vision" in lower

    def test_dry_run_passes_dry_run_true_to_service(self):
        svc = _make_mock_service()
        _invoke(["slide-abc", "--dry-run"], service=svc)
        call_kwargs = svc.analyze.call_args[1]
        assert call_kwargs.get("dry_run") is True

    def test_dry_run_service_analyze_called_once(self):
        svc = _make_mock_service()
        _invoke(["slide-abc", "--dry-run"], service=svc)
        svc.analyze.assert_called_once()


# ---------------------------------------------------------------------------
# --output flag
# ---------------------------------------------------------------------------


class TestOutputFlag:
    def test_output_writes_valid_json(self, tmp_path: Path):
        out = tmp_path / "slot_map.json"
        _invoke(["slide-abc", "--output", str(out)])
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "slide_id" in data

    def test_output_json_round_trips(self, tmp_path: Path):
        out = tmp_path / "slot_map.json"
        slot_map = _make_slot_map("slide-xyz")
        svc = _make_mock_service(slot_map)
        _invoke(["slide-xyz", "--output", str(out)], service=svc)
        loaded = TemplateSlotMap.model_validate_json(out.read_text(encoding="utf-8"))
        assert loaded.slide_id == "slide-xyz"
        assert loaded.schema_version == SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# --force flag
# ---------------------------------------------------------------------------


class TestForceFlag:
    def test_force_passes_force_true_to_service(self):
        svc = _make_mock_service()
        _invoke(["slide-abc", "--force"], service=svc)
        call_kwargs = svc.analyze.call_args[1]
        assert call_kwargs.get("force") is True


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_service_value_error_exits_nonzero(self):
        svc = MagicMock()
        svc.analyze.side_effect = ValueError("Slide not found in library")
        result = _invoke(["slide-missing"], service=svc)
        assert result.exit_code != 0

    def test_error_message_shown(self):
        svc = MagicMock()
        svc.analyze.side_effect = ValueError("Slide not found in library")
        result = _invoke(["slide-missing"], service=svc)
        assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# cp1252 safety
# ---------------------------------------------------------------------------


class TestCp1252Safety:
    def test_output_is_cp1252_safe(self):
        result = _invoke(["slide-abc"])
        try:
            result.output.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(f"Output contains cp1252-unsafe characters: {exc}")
