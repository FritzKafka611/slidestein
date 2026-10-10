"""VisualQAReviewer Protocol and renderer/inspector protocols for M8."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from slidestein.qa.models import (
        NativeVisualCheck,
        VisualQAModelOutput,
    )
    from slidestein.slots.models import TemplateSlot, TemplateSlotMap


@runtime_checkable
class VisualQAReviewer(Protocol):
    def review(
        self,
        generated_image: Path,
        template_image: Path,
        overlay_image: Path,
        slot_specs: list[dict],
        native_checks: list[dict],
    ) -> "VisualQAModelOutput": ...


@runtime_checkable
class SlideRenderer(Protocol):
    def render(self, pptx_path: Path, slide_number: int, output_path: Path) -> None: ...


@runtime_checkable
class OverlayBuilder(Protocol):
    def build(
        self,
        source_image: Path,
        output_path: Path,
        slot_geometries: dict[str, dict],
    ) -> None: ...


@runtime_checkable
class NativeInspectorProtocol(Protocol):
    def inspect(
        self,
        pptx_path: Path,
        slide_number: int,
        slot_key_map: dict[str, "TemplateSlot"],
        slot_map: "TemplateSlotMap",
    ) -> "list[NativeVisualCheck]": ...
