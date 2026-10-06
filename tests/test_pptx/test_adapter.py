"""Tests for the PPTMasterAdapter ABC, StubPPTMasterAdapter, and PythonPptxAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slidestein.domain.models import ContentSlot, ContentSlotType, SlideMetadata
from slidestein.pptx.adapter import PPTMasterAdapter


class TestPPTMasterAdapterIsAbstract:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            PPTMasterAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all_methods(self):
        class Incomplete(PPTMasterAdapter):
            def introspect_template(self, template_path):
                return MagicMock()

            # fill_and_export and render_preview are missing

        with pytest.raises(TypeError):
            Incomplete()

    def test_fully_concrete_subclass_instantiates(self):
        class Concrete(PPTMasterAdapter):
            def introspect_template(self, template_path: Path) -> SlideMetadata:
                return MagicMock(spec=SlideMetadata)

            def fill_and_export(self, template_path, slots, output_path):
                return output_path

            def render_preview(self, pptx_path, slide_number, output_path):
                return output_path

        adapter = Concrete()
        assert isinstance(adapter, PPTMasterAdapter)


class TestStubPPTMasterAdapter:
    def test_fill_and_export_writes_file(self, tmp_path):
        from pptx import Presentation

        pytest.importorskip("pptx")

        from slidestein.pptx.stub import StubPPTMasterAdapter

        prs = Presentation()
        layout = prs.slide_layouts[0]
        prs.slides.add_slide(layout)
        template_path = tmp_path / "template.pptx"
        prs.save(str(template_path))

        adapter = StubPPTMasterAdapter()

        metadata = adapter.introspect_template(template_path)
        assert metadata.slide_id
        assert len(metadata.content_slots) > 0

        title_slot = metadata.content_slots[0]
        filled_slot = title_slot.model_copy(update={"value": "Test Title"})

        output_path = tmp_path / "output.pptx"
        result = adapter.fill_and_export(template_path, [filled_slot], output_path)
        assert result == output_path
        assert output_path.exists()

    def test_render_preview_raises_not_implemented(self, tmp_path):
        from slidestein.pptx.stub import StubPPTMasterAdapter

        adapter = StubPPTMasterAdapter()
        with pytest.raises(NotImplementedError):
            adapter.render_preview(tmp_path / "slide.pptx", 1, tmp_path / "out.png")


class TestPythonPptxAdapterRenderingBackends:
    """Unit tests for the module-level rendering helpers."""

    def test_find_soffice_returns_none_when_absent(self, monkeypatch):
        """If soffice is not on PATH and not at the default Windows location,
        _find_soffice must return None."""
        from unittest.mock import patch

        from slidestein.pptx import python_pptx_adapter as m

        with (
            patch.object(m, "_find_soffice", return_value=None),
        ):
            assert m._find_soffice() is None  # type: ignore[comparison-overlap]

    def test_render_via_powerpoint_com_returns_false_when_comtypes_missing(
        self, tmp_path, monkeypatch
    ):
        import builtins

        real_import = builtins.__import__

        def _block_comtypes(name, *args, **kwargs):
            if name.startswith("comtypes"):
                raise ImportError("comtypes not available")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block_comtypes)

        from slidestein.pptx.python_pptx_adapter import _render_via_powerpoint_com

        result = _render_via_powerpoint_com(
            tmp_path / "x.pptx", 1, tmp_path / "out.png"
        )
        assert result is False

    def test_render_via_libreoffice_returns_false_when_soffice_absent(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import patch

        from slidestein.pptx import python_pptx_adapter as m

        with patch.object(m, "_find_soffice", return_value=None):
            result = m._render_via_libreoffice(
                tmp_path / "x.pptx", 1, tmp_path / "out.png"
            )
        assert result is False

    def test_render_preview_raises_runtime_error_when_no_backends(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import patch

        from slidestein.pptx import python_pptx_adapter as m

        with (
            patch.object(m, "_render_via_powerpoint_com", return_value=False),
            patch.object(m, "_render_via_libreoffice", return_value=False),
        ):
            adapter = m.PythonPptxAdapter()
            with pytest.raises(RuntimeError, match="No preview rendering backend"):
                adapter.render_preview(tmp_path / "x.pptx", 1, tmp_path / "out.png")


@pytest.mark.integration
class TestPythonPptxAdapterIntegration:
    """Requires a rendering backend (PowerPoint or LibreOffice) to be installed.
    Run with: pytest -m integration
    """

    def test_render_preview_produces_png(self, tmp_path, three_slide_pptx):
        from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

        adapter = PythonPptxAdapter()
        out = tmp_path / "preview.png"
        result = adapter.render_preview(three_slide_pptx, slide_number=1, output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0
