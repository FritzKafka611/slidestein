"""StubPPTMasterAdapter — development fallback using python-pptx directly.

Replace this with a real PPTMasterAdapter once PPT Master is available.
This stub satisfies the full contract so every other pipeline stage can be
developed and tested without PPT Master being installed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pptx import Presentation
from pptx.util import Pt

from slidestein.domain.models import (
    CommunicationJob,
    ContentSlot,
    ContentSlotType,
    SlideMetadata,
    VisualArchetype,
)
from slidestein.pptx.adapter import PPTMasterAdapter

# Placeholder archetype and job — a real adapter would read these from
# custom document properties or a sidecar JSON file.
_DEFAULT_ARCHETYPE = VisualArchetype.TITLE_ONLY
_DEFAULT_JOBS = [CommunicationJob.INFORM]


class StubPPTMasterAdapter(PPTMasterAdapter):
    """python-pptx-backed stub.  Sufficient for wiring up the pipeline;
    not suitable for production use with complex slide masters."""

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

    def render_preview(self, pptx_path: Path, output_dir: Path) -> Path:
        # Real implementation: LibreOffice headless on Linux/macOS, or
        # comtypes / win32com on Windows.
        raise NotImplementedError(
            "Preview rendering requires LibreOffice or a COM bridge. "
            "Install LibreOffice and implement via subprocess, or use comtypes on Windows."
        )


def _infer_slot_type(placeholder_idx: int) -> ContentSlotType:
    """Map python-pptx placeholder indices to ContentSlotType."""
    if placeholder_idx == 0:
        return ContentSlotType.TITLE
    if placeholder_idx == 1:
        return ContentSlotType.SUBTITLE
    return ContentSlotType.BODY
