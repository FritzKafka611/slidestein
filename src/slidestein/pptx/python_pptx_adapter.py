"""PythonPptxAdapter — production adapter for ingestion and template operations.

Uses python-pptx for all PPTX structure work and auto-detects a rendering
backend (PowerPoint COM on Windows, then LibreOffice) for preview generation.

This class must NOT be modified to embed PPT Master logic.  When PPT Master
becomes available, create a new PPTMasterAdapter subclass that delegates to it.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
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
from slidestein.pptx.stub import _infer_slot_type  # shared helper

_LOG = logging.getLogger(__name__)

_DEFAULT_ARCHETYPE = VisualArchetype.TITLE_ONLY
_DEFAULT_JOBS = [CommunicationJob.INFORM]


class PythonPptxAdapter(PPTMasterAdapter):
    """Production adapter backed by python-pptx + an auto-detected render backend.

    Preview rendering strategy (tried in order):
      1. PowerPoint COM automation  (Windows, requires Microsoft Office)
      2. LibreOffice headless       (cross-platform)
      3. RuntimeError               (neither backend available)
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
        """Render slide_number to a PNG at output_path.

        Tries PowerPoint COM first (Windows), then LibreOffice.
        Raises RuntimeError if neither backend is available.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if _render_via_powerpoint_com(pptx_path, slide_number, output_path):
            _LOG.debug("Rendered slide %d via PowerPoint COM → %s", slide_number, output_path)
            return output_path

        if _render_via_libreoffice(pptx_path, slide_number, output_path):
            _LOG.debug("Rendered slide %d via LibreOffice → %s", slide_number, output_path)
            return output_path

        raise RuntimeError(
            f"No preview rendering backend found for slide {slide_number} of "
            f"{pptx_path.name}. "
            "Install Microsoft PowerPoint (Windows) or LibreOffice, "
            "or run with --no-preview to skip rendering."
        )


# ---------------------------------------------------------------------------
# Rendering backends (module-level so they are easily unit-tested)
# ---------------------------------------------------------------------------


def _render_via_powerpoint_com(
    pptx_path: Path,
    slide_number: int,
    output_path: Path,
) -> bool:
    """Render via PowerPoint COM automation.  Returns True on success."""
    try:
        import comtypes.client  # type: ignore[import-untyped]
    except ImportError:
        return False

    try:
        ppt = comtypes.client.CreateObject("PowerPoint.Application")
        ppt.Visible = 1
        try:
            prs = ppt.Presentations.Open(
                str(pptx_path.resolve()),
                ReadOnly=True,
                WithWindow=False,
            )
            try:
                slide = prs.Slides(slide_number)
                slide.Export(str(output_path.resolve()), "PNG")
                return output_path.exists()
            finally:
                prs.Close()
        finally:
            ppt.Quit()
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("PowerPoint COM rendering failed: %s", exc)
        return False


def _render_via_libreoffice(
    pptx_path: Path,
    slide_number: int,
    output_path: Path,
) -> bool:
    """Render via LibreOffice headless.  Returns True on success."""
    soffice = _find_soffice()
    if soffice is None:
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to", "png",
                    "--outdir", tmpdir,
                    str(pptx_path),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            _LOG.debug("LibreOffice rendering failed: %s", exc)
            return False

        tmpdir_path = Path(tmpdir)
        stem = pptx_path.stem

        # LibreOffice names output files: "{stem}{N}.png" (e.g. deck1.png, deck2.png)
        # Try the expected name first, then fall back to sorted position.
        candidate = tmpdir_path / f"{stem}{slide_number}.png"
        if not candidate.exists():
            pngs = sorted(tmpdir_path.glob(f"{stem}*.png"), key=lambda p: p.name)
            if not pngs or slide_number > len(pngs):
                _LOG.debug(
                    "LibreOffice did not produce a PNG for slide %d (found %d file(s))",
                    slide_number,
                    len(pngs),
                )
                return False
            candidate = pngs[slide_number - 1]

        shutil.copy(candidate, output_path)
        return True


def _find_soffice() -> str | None:
    """Return the path to the LibreOffice soffice binary, or None."""
    binary = shutil.which("soffice")
    if binary:
        return binary

    # Common Windows installation path
    win_default = Path("C:/Program Files/LibreOffice/program/soffice.exe")
    if win_default.exists():
        return str(win_default)

    return None
