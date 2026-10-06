"""Tests for the PPTMasterAdapter ABC and StubPPTMasterAdapter."""

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

            def render_preview(self, pptx_path, output_dir):
                return output_dir / "preview.png"

        adapter = Concrete()
        assert isinstance(adapter, PPTMasterAdapter)


class TestStubPPTMasterAdapter:
    """Integration-light tests — use an in-memory PPTX where possible."""

    def test_fill_and_export_writes_file(self, tmp_path):
        """fill_and_export creates an output file when given a valid template."""
        from pptx import Presentation

        pytest.importorskip("pptx")

        from slidestein.domain.models import ContentSlotType
        from slidestein.pptx.stub import StubPPTMasterAdapter

        # Build a minimal in-memory PPTX with a title placeholder
        prs = Presentation()
        layout = prs.slide_layouts[0]  # Title Slide layout has two placeholders
        prs.slides.add_slide(layout)
        template_path = tmp_path / "template.pptx"
        prs.save(str(template_path))

        adapter = StubPPTMasterAdapter()

        # Introspect
        metadata = adapter.introspect_template(template_path)
        assert metadata.slide_id  # non-empty
        assert len(metadata.content_slots) > 0

        # Fill
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
            adapter.render_preview(tmp_path / "slide.pptx", tmp_path)
