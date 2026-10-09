"""SlotSemanticAnalyzer protocol for M5.2.

Separates the interface from the SAP AI Core implementation so the service
can be tested with mock analyzers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from slidestein.slots.analysis_models import SlotAnalysisModelOutput
from slidestein.slots.models import NativeShapeDescriptor


@runtime_checkable
class SlotSemanticAnalyzer(Protocol):
    """Classifies editable shape candidates into semantic slots via Vision."""

    def analyze(
        self,
        preview_path: str,
        candidates: dict[str, NativeShapeDescriptor],
    ) -> SlotAnalysisModelOutput:
        """Make one Vision call and return the validated model output.

        Args:
            preview_path: absolute path to the slide preview PNG.
            candidates: mapping of candidate key (S1, S2, …) to descriptor.
                        The analyzer sends ONLY these shapes to Vision.

        Returns:
            SlotAnalysisModelOutput with one assessment per candidate key.

        Raises:
            SlotAnalysisError: on any SDK, parse, or validation failure.
        """
        ...
