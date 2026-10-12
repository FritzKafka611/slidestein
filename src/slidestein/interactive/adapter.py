"""PowerPointHostAdapter protocol — transport-neutral interface for slide state capture and patching."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from slidestein.interactive.models import PatchExecutionResult, SlideState, SlidePatchPlan


@runtime_checkable
class PowerPointHostAdapter(Protocol):
    """Transport-neutral adapter for reading and writing PowerPoint slide state.

    Implementations:
      PythonPptxPowerPointHostAdapter  — python-pptx backed, file-system PPTX (M11)

    COM adapter (ComPowerPointHostAdapter) is planned for M12.
    The existing PPTMasterRealAdapter drives an external subprocess and does not
    expose a clean in-process capture_slide_state interface.
    """

    def capture_slide_state(
        self,
        pptx_path: Path,
        slide_number: int,
        *,
        deck_id: Optional[str] = None,
        slide_id: Optional[str] = None,
    ) -> SlideState: ...

    def apply_patch(
        self,
        pptx_path: Path,
        patch: SlidePatchPlan,
    ) -> PatchExecutionResult: ...
