"""Domain models for M6 PowerPoint write-back.

All models are application-owned.  No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from slidestein.drafting.models import SlideContentDraft, SlotDraftAction
from slidestein.slots.models import TemplateSlotMap
from slidestein.writeback.versions import WRITEBACK_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class PowerPointWritebackRequest(BaseModel):
    """Input bundle for one write-back operation.

    source_pptx and output_pptx must be different files (validated).
    """

    model_config = ConfigDict(extra="forbid")

    draft: SlideContentDraft
    slot_map: TemplateSlotMap

    source_pptx: Path
    output_pptx: Path

    overwrite: bool = False

    @model_validator(mode="after")
    def _source_and_output_differ(self) -> "PowerPointWritebackRequest":
        try:
            src = self.source_pptx.resolve()
            out = self.output_pptx.resolve()
        except Exception:
            return self
        if src == out:
            raise ValueError(
                f"source_pptx and output_pptx must be different files: {src}"
            )
        return self


# ---------------------------------------------------------------------------
# Plan (internal — produced by preflight, consumed by com_writer)
# ---------------------------------------------------------------------------


@dataclass
class WritebackOperation:
    """A single resolved write-back operation.

    Only REPLACE and CLEAR actions reach this stage.
    NEEDS_INPUT is rejected by preflight.
    """

    slot_id: str
    shape_id: int
    shape_path: str
    action: SlotDraftAction          # REPLACE or CLEAR only
    text: Optional[str]              # set for REPLACE (normalised); None for CLEAR


@dataclass
class WritebackPlan:
    """Fully validated, mutation-ready plan produced by preflight.

    Once constructed, no semantic decisions remain.

    resolved_slide_number is the stable-identity-resolved current ordinal —
    may differ from slide_number if the deck was reordered since M5.2.
    COM execution and verification always use resolved_slide_number.
    """

    schema_version: str
    slide_id: str
    deck_id: Optional[str]

    slide_number: int           # historical ordinal from slot map (metadata only)
    resolved_slide_number: int  # stable-identity-resolved current ordinal

    native_slide_id: Optional[int]  # PowerPoint native slide ID (from sldIdLst)

    source_pptx: Path
    output_pptx: Path

    operations: list[WritebackOperation]
    replacement_count: int
    clear_count: int

    before_structure_fingerprint: str   # target slide geometry, from source PPTX
    before_format_fingerprint: str = ""  # target slide format props, from source PPTX

    # Deck-level structure baseline (all slides, keyed by native slide ID as str)
    before_deck_native_ids: list[int] = field(default_factory=list)
    before_deck_structure: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Receipt and result
# ---------------------------------------------------------------------------


@dataclass
class WritebackReceipt:
    """Per-slot audit record produced after writing."""

    slot_id: str
    shape_id: int
    shape_path: str
    action: str                      # "replace" or "clear"

    expected_text: Optional[str]     # draft text for replace, "" for clear
    verified_text: Optional[str]     # text read back from output; None = unread

    verified: bool


class PowerPointWritebackResult(BaseModel):
    """Complete result of one write-back operation.

    Serialisable to JSON for evaluation artifacts.
    Never contains COM objects or credentials.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = WRITEBACK_SCHEMA_VERSION

    source_pptx: str         # str for JSON serialisation
    output_pptx: str

    slide_id: str
    slide_number: int
    resolved_slide_number: int  # stable-identity-resolved ordinal actually written

    native_slide_id: Optional[int] = None

    replacement_count: int
    clear_count: int

    applied_assignments: list[dict]  # WritebackReceipt as dict

    verification_passed: bool
    source_currentness_verified: bool = True
    target_structure_verified: bool = True
    non_target_structure_verified: bool = True

    warnings: list[str] = []

    before_structure_fingerprint: Optional[str] = None
    after_structure_fingerprint: Optional[str] = None
