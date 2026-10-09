"""Domain models for M5.2 Template / Slot Understanding.

All models are Pydantic BaseModel, not frozen — they are value objects built
by the inspector and service, never mutated by Vision output.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from slidestein.slots.roles import SlotRole
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Shape descriptor (pure native extraction, no LLM)
# ---------------------------------------------------------------------------


class NativeShapeDescriptor(BaseModel):
    """Provider-independent, normalised description of one PPTX shape.

    Geometry is stored in both raw EMU and as normalised ratios [0, 1]
    relative to the slide dimensions.  All values are from python-pptx;
    no COM or platform-specific APIs are used.
    """

    model_config = ConfigDict(extra="forbid")

    shape_id: int
    shape_path: str  # e.g. "7" for top-level, "12/7" for group child
    shape_type: str  # MSO_SHAPE_TYPE name, e.g. "AUTO_SHAPE", "GROUP"

    x: int           # EMU
    y: int           # EMU
    width: int       # EMU
    height: int      # EMU

    x_ratio: float   # [0, 1] relative to slide width
    y_ratio: float
    width_ratio: float
    height_ratio: float

    z_order: int

    has_text: bool
    text: str        # empty string when has_text is False

    is_placeholder: bool
    placeholder_type: Optional[int] = None   # MsoPlaceholderType int
    placeholder_idx: Optional[int] = None    # 0=title, 1=body, etc.

    is_group: bool
    parent_shape_path: Optional[str] = None  # None for top-level shapes

    is_table: bool
    table_rows: Optional[int] = None
    table_columns: Optional[int] = None

    has_text_frame: bool
    font_size_pt: Optional[float] = None     # first-found font size in points

    can_edit_text: bool   # application logic only — Vision may not override
    source_kind: str      # "placeholder"|"text_box"|"group"|"table"|"chart"|"image"|"other"


# ---------------------------------------------------------------------------
# Slot capacity (deterministic, no LLM)
# ---------------------------------------------------------------------------


class SlotCapacity(BaseModel):
    """Capacity estimate for a single editable slot.

    All values are deterministic from shape geometry and current text.
    """

    model_config = ConfigDict(extra="forbid")

    max_characters_estimate: int
    max_lines_estimate: int
    current_character_count: int
    current_line_count: int
    relative_capacity: str  # "small" | "medium" | "large"


# ---------------------------------------------------------------------------
# Template slot (the semantic unit returned to callers)
# ---------------------------------------------------------------------------


class TemplateSlot(BaseModel):
    """A single editable content slot within a slide template.

    Application-owned fields (slot_id, shape_id, shape_path, editable,
    geometry, capacity) are set by the service before Vision is called and
    cannot be overridden by Vision output.  Vision contributes only:
    slot_role, semantic_label, group_id, group_role, sequence_index,
    confidence, rationale (stored in notes).
    """

    model_config = ConfigDict(extra="forbid")

    slot_id: str              # UUID5 from (slide_id, shape_path)
    shape_id: int             # application-owned
    shape_path: str           # application-owned

    slot_role: SlotRole
    semantic_label: str

    editable: bool            # application-owned (can_edit_text from inspector)
    confidence: float         # 0..1, from Vision

    current_text: str
    geometry: dict[str, Any]  # {x, y, width, height, x_ratio, y_ratio, width_ratio, height_ratio}

    capacity: SlotCapacity

    group_id: Optional[str] = None
    sequence_index: Optional[int] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Slot group
# ---------------------------------------------------------------------------


class SlotGroup(BaseModel):
    """A logical grouping of slots (e.g. all workstream labels in a row)."""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    group_role: str
    member_slot_ids: list[str]
    sequence_index: Optional[int] = None
    semantic_label: str


# ---------------------------------------------------------------------------
# Template slot map (top-level output artifact)
# ---------------------------------------------------------------------------


class TemplateSlotMap(BaseModel):
    """Complete slot-map analysis result for one slide.

    Returned by TemplateSlotAnalysisService.analyze().  The JSON
    representation of this model is what gets persisted in slide_slot_maps.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SLOT_MAP_SCHEMA_VERSION
    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int
    slide_width: int   # EMU
    slide_height: int  # EMU

    slots: list[TemplateSlot]
    non_editable_elements: list[dict[str, Any]]   # technically non-editable native objects
    excluded_editable_candidates: list[dict[str, Any]] = []  # editable objects Vision judged not useful as slots
    unsupported_elements: list[dict[str, Any]]   # charts, tables, SmartArt
    groups: list[SlotGroup]

    analysis_summary: str
    slot_analysis_input_fingerprint: str

    # Populated only in dry-run mode to expose candidate mapping; always empty
    # in persisted maps.
    candidate_map: list[dict[str, Any]] = []

    @field_validator("slots")
    @classmethod
    def _slots_have_unique_ids(cls, v: list[TemplateSlot]) -> list[TemplateSlot]:
        seen: set[str] = set()
        for slot in v:
            if slot.slot_id in seen:
                raise ValueError(f"Duplicate slot_id: {slot.slot_id!r}")
            seen.add(slot.slot_id)
        return v
