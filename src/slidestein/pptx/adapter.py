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
    def render_preview(self, pptx_path: Path, output_dir: Path) -> Path:
        """Render the first slide of pptx_path to a PNG in output_dir.

        Used by the vision-selection and visual-QA stages.
        Returns the path to the PNG file.
        """
        ...
