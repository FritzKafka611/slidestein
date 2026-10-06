"""PPTMasterAdapter — the only contract between consulting logic and PPT Master.

Rules:
  - Never modify PPT Master source code.
  - All callers interact exclusively through this ABC.
  - Dependency rule: imports only from slidestein.domain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from slidestein.domain.models import ContentSlot, SlideMetadata


class PPTMasterAdapter(ABC):
    """Abstract interface for producing and introspecting PPTX files.

    Implementations must preserve full PPTX editability — no rasterisation,
    no PDF round-trips.  The output of fill_and_export must open natively in
    PowerPoint.
    """

    @abstractmethod
    def introspect_template(self, template_path: Path) -> SlideMetadata:
        """Read a PPTX file and return its slot structure and metadata.

        The returned SlideMetadata is stored in the library; its content_slots
        represent every fillable placeholder the template exposes.
        """
        ...

    @abstractmethod
    def fill_and_export(
        self,
        template_path: Path,
        slots: list[ContentSlot],
        output_path: Path,
    ) -> Path:
        """Fill the template's placeholders with slot values and write an
        editable PPTX to output_path.

        Only slots with a non-None value are written; others are left as-is.
        Returns output_path.
        """
        ...

    @abstractmethod
    def render_preview(
        self,
        pptx_path: Path,
        slide_number: int,
        output_path: Path,
    ) -> Path:
        """Render slide_number (1-indexed) of pptx_path to a PNG at output_path.

        Used by the ingestion pipeline, vision-selection, and visual-QA stages.
        output_path's parent directory must exist or be created by the implementation.
        Returns output_path on success.
        """
        ...

    # ------------------------------------------------------------------
    # Roundtrip operations — concrete default raises NotImplementedError
    # so existing subclasses are not broken.
    # ------------------------------------------------------------------

    def extract_slide(
        self,
        source_pptx: Path,
        slide_number: int,
        output_path: Path,
    ) -> Path:
        """Extract a single slide preserving native PPTX objects.

        The default implementation raises NotImplementedError.
        Override in adapters that support native roundtrip (e.g. PPTMasterRealAdapter).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support native slide extraction. "
            "Use PPTMasterRealAdapter."
        )

    def replace_text_in_slide(
        self,
        source_pptx: Path,
        slide_number: int,
        replacements: dict[str, str],
        output_path: Path,
    ) -> Path:
        """Replace text in a slide and export an editable PPTX.

        replacements maps old_text → new_text; only exact literal matches are replaced.
        The default implementation raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support native text replacement. "
            "Use PPTMasterRealAdapter."
        )
