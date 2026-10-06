"""StubPPTMasterAdapter — development fallback using python-pptx directly.

Use PythonPptxAdapter for any workflow that requires preview rendering.
This stub intentionally raises NotImplementedError for render_preview so that
tests that wire up the generation pipeline without a rendering backend still
have explicit, readable failure points.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pptx import Presentation

from slidestein.domain.models import (
    CommunicationJob,
    ContentSlot,
    ContentSlotType,
    SlideMetadata,
    VisualArchetype,
)
from slidestein.pptx.adapter import PPTMasterAdapter

_DEFAULT_ARCHETYPE = VisualArchetype.TITLE_ONLY
_DEFAULT_JOBS = [CommunicationJob.INFORM]


class StubPPTMasterAdapter(PPTMasterAdapter):
    """python-pptx-backed stub.

    Sufficient for wiring up the generation pipeline in tests; not suitable
    for production ingestion (no preview rendering).
    """

    def introspect_template(self, template_path: Path) -> SlideMetadata:
        prs = Presentation(str(template_path))
        slide = prs.slides[0]

        slots: list[ContentSlot] = []
        for shape in slide.placeholders:
            ph_idx = shape.placeholder_format.idx
            slots.append(
                ContentSlot(
                    slot_id=f"ph_{ph_idx}",
                    slot_type=_infer_slot_type(ph_idx),
                    placeholder_name=shape.name,
                    max_chars=None,
                )
            )

        slide_id = hashlib.md5(template_path.read_bytes()).hexdigest()[:12]

        return SlideMetadata(
            slide_id=slide_id,
            template_path=template_path,
            archetype=_DEFAULT_ARCHETYPE,
            communication_jobs=_DEFAULT_JOBS,
            content_slots=slots,
            description=f"Template: {template_path.name}",
        )

    def fill_and_export(
        self,
        template_path: Path,
        slots: list[ContentSlot],
        output_path: Path,
    ) -> Path:
        prs = Presentation(str(template_path))
        slide = prs.slides[0]

        slot_map = {s.placeholder_name: s for s in slots if s.value is not None}
        for shape in slide.placeholders:
            candidate = slot_map.get(shape.name)
            if candidate and candidate.value is not None:
                shape.text = candidate.value

        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        return output_path

    def render_preview(
        self,
        pptx_path: Path,
        slide_number: int,
        output_path: Path,
    ) -> Path:
        raise NotImplementedError(
            "Preview rendering is not implemented in StubPPTMasterAdapter. "
            "Use PythonPptxAdapter (which tries PowerPoint COM or LibreOffice), "
            "or pass render_previews=False to IngestionService."
        )


def _infer_slot_type(placeholder_idx: int) -> ContentSlotType:
    """Map python-pptx placeholder indices to ContentSlotType."""
    if placeholder_idx == 0:
        return ContentSlotType.TITLE
    if placeholder_idx == 1:
        return ContentSlotType.SUBTITLE
    return ContentSlotType.BODY
