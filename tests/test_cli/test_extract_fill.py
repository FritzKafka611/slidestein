"""CLI tests for extract-slide and test-fill commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from slidestein.cli import app

runner = CliRunner()


def _make_mock_adapter(output_path_to_create: Path | None = None):
    """Return a mock PPTMasterRealAdapter."""
    adapter = MagicMock()
    if output_path_to_create is not None:
        def fake_extract(source_pptx, slide_number, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"PK_fake_pptx")
            return output_path
        def fake_replace(source_pptx, slide_number, replacements, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"PK_fake_pptx")
            return output_path
        adapter.extract_slide.side_effect = fake_extract
        adapter.replace_text_in_slide.side_effect = fake_replace
    adapter.render_preview.side_effect = RuntimeError("No rendering backend")
    return adapter


# ---------------------------------------------------------------------------
# extract-slide
# ---------------------------------------------------------------------------


class TestExtractSlideCommand:
    def test_missing_source_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "extract-slide",
            str(tmp_path / "nonexistent.pptx"),
            "3",
            "--output", str(tmp_path / "out.pptx"),
        ])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_non_pptx_source_exits_1(self, tmp_path: Path) -> None:
        bad = tmp_path / "deck.pdf"
        bad.write_bytes(b"%%PDF")
        result = runner.invoke(app, [
            "extract-slide", str(bad), "3",
            "--output", str(tmp_path / "out.pptx"),
        ])
        assert result.exit_code == 1

    def test_zero_slide_number_exits_1(self, tmp_path: Path) -> None:
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        result = runner.invoke(app, [
            "extract-slide", str(pptx), "0",
            "--output", str(tmp_path / "out.pptx"),
        ])
        assert result.exit_code == 1
        assert "1" in result.output  # mentions >= 1

    def test_success_exits_0(self, tmp_path: Path) -> None:
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        output = tmp_path / "out.pptx"
        mock_adapter = _make_mock_adapter(output)

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            return_value=mock_adapter,
        ):
            result = runner.invoke(app, [
                "extract-slide", str(pptx), "3",
                "--output", str(output),
            ])

        assert result.exit_code == 0
        mock_adapter.extract_slide.assert_called_once()

    def test_pptmaster_not_found_exits_1(self, tmp_path: Path) -> None:
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            side_effect=FileNotFoundError("ppt-master venv not found"),
        ):
            result = runner.invoke(app, [
                "extract-slide", str(pptx), "3",
                "--output", str(tmp_path / "out.pptx"),
            ])

        assert result.exit_code == 1
        assert "ppt-master" in result.output.lower()

    def test_pptmaster_error_exits_1(self, tmp_path: Path) -> None:
        from slidestein.pptx.pptmaster_real_adapter import PPTMasterError

        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        mock_adapter = MagicMock()
        mock_adapter.extract_slide.side_effect = PPTMasterError("svg-to-pptx failed")

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            return_value=mock_adapter,
        ):
            result = runner.invoke(app, [
                "extract-slide", str(pptx), "3",
                "--output", str(tmp_path / "out.pptx"),
            ])

        assert result.exit_code == 1
        assert "ppt-master error" in result.output.lower()

    def test_preview_failure_does_not_fail_command(self, tmp_path: Path) -> None:
        """Preview rendering failure is non-fatal — command still succeeds."""
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        output = tmp_path / "out.pptx"
        mock_adapter = _make_mock_adapter(output)
        # render_preview already raises RuntimeError in _make_mock_adapter

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            return_value=mock_adapter,
        ):
            result = runner.invoke(app, [
                "extract-slide", str(pptx), "3",
                "--output", str(output),
            ])

        assert result.exit_code == 0
        assert "preview skipped" in result.output.lower()


# ---------------------------------------------------------------------------
# test-fill
# ---------------------------------------------------------------------------


class TestTestFillCommand:
    def test_missing_source_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "test-fill",
            str(tmp_path / "nonexistent.pptx"),
            "3",
            "--replace", "OLD", "NEW",
            "--output", str(tmp_path / "out.pptx"),
        ])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_zero_slide_number_exits_1(self, tmp_path: Path) -> None:
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        result = runner.invoke(app, [
            "test-fill", str(pptx), "0",
            "--replace", "OLD", "NEW",
            "--output", str(tmp_path / "out.pptx"),
        ])
        assert result.exit_code == 1

    def test_success_exits_0(self, tmp_path: Path) -> None:
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        output = tmp_path / "out.pptx"
        mock_adapter = _make_mock_adapter(output)

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            return_value=mock_adapter,
        ):
            result = runner.invoke(app, [
                "test-fill", str(pptx), "3",
                "--replace", "OLD TEXT", "NEW TEXT",
                "--output", str(output),
            ])

        assert result.exit_code == 0
        mock_adapter.replace_text_in_slide.assert_called_once()
        _, kwargs = mock_adapter.replace_text_in_slide.call_args
        assert kwargs.get("replacements") == {"OLD TEXT": "NEW TEXT"}

    def test_replacement_args_passed_correctly(self, tmp_path: Path) -> None:
        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        output = tmp_path / "out.pptx"
        mock_adapter = _make_mock_adapter(output)

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            return_value=mock_adapter,
        ):
            runner.invoke(app, [
                "test-fill", str(pptx), "5",
                "--replace", "Agenda", "Our Plan",
                "--output", str(output),
            ])

        call_kwargs = mock_adapter.replace_text_in_slide.call_args[1]
        assert call_kwargs["slide_number"] == 5
        assert call_kwargs["replacements"] == {"Agenda": "Our Plan"}

    def test_pptmaster_error_exits_1(self, tmp_path: Path) -> None:
        from slidestein.pptx.pptmaster_real_adapter import PPTMasterError

        pptx = tmp_path / "deck.pptx"
        pptx.write_bytes(b"PK")
        mock_adapter = MagicMock()
        mock_adapter.replace_text_in_slide.side_effect = PPTMasterError("SVG not found")

        with patch(
            "slidestein.pptx.pptmaster_real_adapter.PPTMasterRealAdapter.from_settings",
            return_value=mock_adapter,
        ):
            result = runner.invoke(app, [
                "test-fill", str(pptx), "3",
                "--replace", "OLD", "NEW",
                "--output", str(tmp_path / "out.pptx"),
            ])

        assert result.exit_code == 1
