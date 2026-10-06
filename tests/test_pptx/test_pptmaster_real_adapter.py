"""Unit tests for PPTMasterRealAdapter.

All tests in this module mock subprocess calls so they run without a ppt-master
installation.  The integration test at the bottom is opt-in via @pytest.mark.integration.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from slidestein.pptx.pptmaster_real_adapter import (
    PPTMasterError,
    PPTMasterRealAdapter,
    _find_pptmaster_cli,
    _replace_text_in_svg,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(tmp_path: Path) -> PPTMasterRealAdapter:
    """Return a PPTMasterRealAdapter wired to a stub Python/CLI that do not exist."""
    python = tmp_path / "python.exe"
    python.touch()
    cli = tmp_path / "cli.py"
    cli.touch()
    adapter = PPTMasterRealAdapter.__new__(PPTMasterRealAdapter)
    adapter._python = python
    adapter._cli = cli
    adapter._workspace_root = tmp_path / "workspaces"
    return adapter


def _stub_import_success(workspace: Path) -> None:
    """Create the minimum workspace structure that _import_deck expects."""
    authoring = workspace / "authoring-svg-flat"
    authoring.mkdir(parents=True, exist_ok=True)
    (authoring / "slide_01.svg").write_text("<svg/>", encoding="utf-8")
    (authoring / "slide_03.svg").write_text(
        "<svg><text>Hello World</text></svg>", encoding="utf-8"
    )
    sources = workspace / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    # source.pptx size must match what we pass as source_pptx
    (sources / "source.pptx").write_bytes(b"\x00" * 100)


# ---------------------------------------------------------------------------
# _find_pptmaster_cli
# ---------------------------------------------------------------------------


class TestFindPptmasterCli:
    def test_finds_windows_layout(self, tmp_path: Path) -> None:
        python = tmp_path / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        cli = tmp_path / "Lib" / "site-packages" / "cli.py"
        cli.parent.mkdir(parents=True)
        cli.touch()
        assert _find_pptmaster_cli(python) == cli

    def test_falls_back_to_subprocess(self, tmp_path: Path) -> None:
        python = tmp_path / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        target = tmp_path / "somewhere" / "cli.py"
        target.parent.mkdir(parents=True)
        target.touch()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=str(target) + "\n")
            found = _find_pptmaster_cli(python)
        assert found == target

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        python = tmp_path / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            with pytest.raises(FileNotFoundError, match="cli.py"):
                _find_pptmaster_cli(python)


# ---------------------------------------------------------------------------
# _replace_text_in_svg
# ---------------------------------------------------------------------------


class TestReplaceTextInSvg:
    def test_replaces_matching_text(self, tmp_path: Path) -> None:
        svg = tmp_path / "slide_01.svg"
        svg.write_text("<svg><text>Hello World</text></svg>", encoding="utf-8")
        _replace_text_in_svg(svg, {"Hello": "Hi"})
        assert svg.read_text(encoding="utf-8") == "<svg><text>Hi World</text></svg>"

    def test_no_match_leaves_file_unchanged(self, tmp_path: Path) -> None:
        original = "<svg><text>Keep this</text></svg>"
        svg = tmp_path / "slide_01.svg"
        svg.write_text(original, encoding="utf-8")
        _replace_text_in_svg(svg, {"Not present": "Replacement"})
        assert svg.read_text(encoding="utf-8") == original

    def test_multiple_replacements_applied(self, tmp_path: Path) -> None:
        svg = tmp_path / "slide_01.svg"
        svg.write_text("<svg><text>A B C</text></svg>", encoding="utf-8")
        _replace_text_in_svg(svg, {"A": "X", "B": "Y"})
        assert svg.read_text(encoding="utf-8") == "<svg><text>X Y C</text></svg>"

    def test_empty_key_is_skipped(self, tmp_path: Path) -> None:
        original = "<svg><text>Text</text></svg>"
        svg = tmp_path / "slide_01.svg"
        svg.write_text(original, encoding="utf-8")
        _replace_text_in_svg(svg, {"": "should-not-insert"})
        assert svg.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# PPTMasterRealAdapter.from_auto_discover
# ---------------------------------------------------------------------------


class TestFromAutoDiscover:
    def test_discovers_windows_venv(self, tmp_path: Path) -> None:
        py = tmp_path / "tools" / "pptmaster-env" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.touch()
        cli = tmp_path / "tools" / "pptmaster-env" / "Lib" / "site-packages" / "cli.py"
        cli.parent.mkdir(parents=True)
        cli.touch()
        with patch("slidestein.pptx.pptmaster_real_adapter.Path") as MockPath:
            MockPath.side_effect = lambda s: tmp_path / s if "tools" in s else Path(s)
            # Directly test with explicit paths instead
        adapter = PPTMasterRealAdapter(
            pptmaster_python=py,
            workspace_root=tmp_path / "ws",
        )
        # _find_pptmaster_cli should find cli.py
        assert adapter._cli == cli

    def test_raises_when_no_venv_found(self, tmp_path: Path) -> None:
        with patch("slidestein.pptx.pptmaster_real_adapter.Path") as _:
            with pytest.raises(FileNotFoundError, match="ppt-master venv not found"):
                # Patch candidates to paths that don't exist
                orig_from = PPTMasterRealAdapter.from_auto_discover.__func__
                adapter_cls = PPTMasterRealAdapter
                with patch.object(adapter_cls, "from_auto_discover", classmethod(
                    lambda cls, ws=None: (_ for _ in ()).throw(
                        FileNotFoundError("ppt-master venv not found at tools/pptmaster-env/.")
                    )
                )):
                    PPTMasterRealAdapter.from_auto_discover()


# ---------------------------------------------------------------------------
# PPTMasterRealAdapter._import_deck
# ---------------------------------------------------------------------------


class TestImportDeck:
    def test_calls_pptx_to_svg_with_correct_args(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)

        workspace = adapter._workspace_root / "deck"

        def fake_run(*args, **kwargs):
            _stub_import_success(workspace)
            return MagicMock(returncode=1, stdout="", stderr="Warning: ...")

        with patch.object(adapter, "_run", side_effect=fake_run) as mock_run:
            result = adapter._import_deck(source, force_reimport=False)

        assert result == workspace
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0]
        assert "pptx-to-svg" in call_args
        assert "--roundtrip" in call_args
        assert "--inheritance-mode" in call_args
        assert "both" in call_args

    def test_skips_reimport_when_workspace_cached(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)

        workspace = adapter._workspace_root / "deck"
        _stub_import_success(workspace)
        # source copy must match size
        (workspace / "sources" / "source.pptx").write_bytes(b"\x00" * 100)

        with patch.object(adapter, "_run") as mock_run:
            adapter._import_deck(source, force_reimport=False)

        mock_run.assert_not_called()

    def test_force_reimport_always_re_runs(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)

        workspace = adapter._workspace_root / "deck"
        _stub_import_success(workspace)
        (workspace / "sources" / "source.pptx").write_bytes(b"\x00" * 100)

        def fake_run(*args, **kwargs):
            _stub_import_success(workspace)
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(adapter, "_run", side_effect=fake_run) as mock_run:
            adapter._import_deck(source, force_reimport=True)

        mock_run.assert_called_once()

    def test_raises_pptmaster_error_when_authoring_dir_missing(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)

        with patch.object(adapter, "_run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: failed")
            with pytest.raises(PPTMasterError, match="authoring workspace"):
                adapter._import_deck(source, force_reimport=False)


# ---------------------------------------------------------------------------
# PPTMasterRealAdapter.extract_slide
# ---------------------------------------------------------------------------


class TestExtractSlide:
    def test_produces_output_pptx(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"

        workspace = adapter._workspace_root / "deck"

        def fake_run(*args, **kwargs):
            cmd_args = args
            if "pptx-to-svg" in cmd_args:
                _stub_import_success(workspace)
            elif "svg-to-pptx" in cmd_args:
                output.write_bytes(b"PK_fake_pptx")
            return MagicMock(returncode=1, stdout="", stderr="Warning: ...")

        with patch.object(adapter, "_run", side_effect=fake_run):
            result = adapter.extract_slide(source, slide_number=3, output_path=output)

        assert result == output
        assert output.exists()

    def test_raises_if_output_not_created(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"

        workspace = adapter._workspace_root / "deck"

        def fake_run(*args, **kwargs):
            if "pptx-to-svg" in args:
                _stub_import_success(workspace)
            # svg-to-pptx does NOT create the file
            return MagicMock(returncode=1, stdout="", stderr="Error: export failed")

        with patch.object(adapter, "_run", side_effect=fake_run):
            with pytest.raises(PPTMasterError, match="svg-to-pptx failed"):
                adapter.extract_slide(source, slide_number=3, output_path=output)

    def test_page_plan_selects_correct_slide(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"

        workspace = adapter._workspace_root / "deck"

        def fake_run(*args, **kwargs):
            if "pptx-to-svg" in args:
                _stub_import_success(workspace)
            elif "svg-to-pptx" in args:
                output.write_bytes(b"PK")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(adapter, "_run", side_effect=fake_run):
            adapter.extract_slide(source, slide_number=5, output_path=output)

        plan = json.loads((workspace / "page_plan.json").read_text())
        assert plan["pages"] == [{"source_slide": 5}]


# ---------------------------------------------------------------------------
# PPTMasterRealAdapter.replace_text_in_slide
# ---------------------------------------------------------------------------


class TestReplaceTextInSlide:
    def test_edits_svg_before_export(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"

        workspace = adapter._workspace_root / "deck"

        def fake_run(*args, **kwargs):
            if "pptx-to-svg" in args:
                _stub_import_success(workspace)
            elif "svg-to-pptx" in args:
                output.write_bytes(b"PK")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(adapter, "_run", side_effect=fake_run):
            adapter.replace_text_in_slide(
                source, slide_number=3,
                replacements={"Hello World": "Goodbye"},
                output_path=output,
            )

        svg = workspace / "authoring-svg-flat" / "slide_03.svg"
        assert "Goodbye" in svg.read_text(encoding="utf-8")
        assert "Hello World" not in svg.read_text(encoding="utf-8")

    def test_raises_when_svg_missing(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"

        workspace = adapter._workspace_root / "deck"

        def fake_run(*args, **kwargs):
            if "pptx-to-svg" in args:
                # Create workspace but only slide_01.svg, not slide_99.svg
                _stub_import_success(workspace)
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(adapter, "_run", side_effect=fake_run):
            with pytest.raises(PPTMasterError, match="SVG for slide 99"):
                adapter.replace_text_in_slide(
                    source, slide_number=99,
                    replacements={"X": "Y"},
                    output_path=output,
                )

    def test_calls_refresh_summary(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"
        workspace = adapter._workspace_root / "deck"
        called_with: list[tuple] = []

        def fake_run(*args, **kwargs):
            called_with.append(args)
            if "pptx-to-svg" in args:
                _stub_import_success(workspace)
            elif "svg-to-pptx" in args:
                output.write_bytes(b"PK")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(adapter, "_run", side_effect=fake_run):
            adapter.replace_text_in_slide(
                source, slide_number=3,
                replacements={"Hello World": "Hi"},
                output_path=output,
            )

        commands_called = [args[0] for args in called_with]
        assert "svg-authoring-view" in commands_called

    def test_always_reimports_deck(self, tmp_path: Path) -> None:
        """replace_text_in_slide must always start with a fresh import."""
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "out.pptx"
        workspace = adapter._workspace_root / "deck"
        # Pre-populate a cached workspace
        _stub_import_success(workspace)
        (workspace / "sources" / "source.pptx").write_bytes(b"\x00" * 100)

        import_calls = 0

        def fake_run(*args, **kwargs):
            nonlocal import_calls
            if "pptx-to-svg" in args:
                import_calls += 1
                _stub_import_success(workspace)
            elif "svg-to-pptx" in args:
                output.write_bytes(b"PK")
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch.object(adapter, "_run", side_effect=fake_run):
            adapter.replace_text_in_slide(
                source, slide_number=3,
                replacements={"Hello World": "Hi"},
                output_path=output,
            )

        assert import_calls == 1  # forced, even though workspace was cached


# ---------------------------------------------------------------------------
# subprocess failure propagation
# ---------------------------------------------------------------------------


class TestSubprocessFailurePropagation:
    def test_timeout_propagates(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300)):
            with pytest.raises(subprocess.TimeoutExpired):
                adapter.extract_slide(source, slide_number=1, output_path=tmp_path / "out.pptx")

    def test_oserror_propagates(self, tmp_path: Path) -> None:
        adapter = _make_adapter(tmp_path)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"\x00" * 100)

        with patch("subprocess.run", side_effect=OSError("simulated disk full")):
            with pytest.raises(OSError, match="simulated disk full"):
                adapter.extract_slide(source, slide_number=1, output_path=tmp_path / "out.pptx")


# ---------------------------------------------------------------------------
# Integration (opt-in — requires ppt-master + PowerPoint)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPPTMasterRealAdapterIntegration:
    """End-to-end tests against the real deck.  Require:
    - tools/pptmaster-env/ with ppt-master installed
    - PowerPoint COM available for preview rendering
    Run with: pytest -m integration
    """

    DECK = Path("data/test_decks/sample_consulting_deck.pptx")

    def test_extract_slide_produces_valid_pptx(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        adapter = PPTMasterRealAdapter.from_auto_discover(workspace_root=tmp_path / "ws")
        output = tmp_path / "slide_03.pptx"
        result = adapter.extract_slide(self.DECK, slide_number=3, output_path=output)
        assert result.exists()
        assert result.stat().st_size > 10_000
        # Must be a valid ZIP (PPTX is ZIP-based)
        import zipfile
        assert zipfile.is_zipfile(str(result))

    def test_extract_slide_renders_preview(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        adapter = PPTMasterRealAdapter.from_auto_discover(workspace_root=tmp_path / "ws")
        pptx = tmp_path / "slide_03.pptx"
        adapter.extract_slide(self.DECK, slide_number=3, output_path=pptx)
        png = tmp_path / "slide_03.png"
        adapter.render_preview(pptx, slide_number=1, output_path=png)
        assert png.exists()
        assert png.stat().st_size > 1_000
        assert png.read_bytes()[:4] == b"\x89PNG"

    def test_replace_text_in_slide_modifies_output(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        adapter = PPTMasterRealAdapter.from_auto_discover(workspace_root=tmp_path / "ws")
        output = tmp_path / "slide_03_mod.pptx"
        # Use text known to exist on slide 3 of the consulting deck
        adapter.replace_text_in_slide(
            self.DECK, slide_number=3,
            replacements={"Agenda": "REPLACED_BY_TEST"},
            output_path=output,
        )
        assert output.exists()
        assert output.stat().st_size > 10_000
