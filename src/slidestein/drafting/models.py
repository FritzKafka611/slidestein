"""Domain models for M5.3 content drafting.

Application-owned — never returned by or controlled by the LLM.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from slidestein.drafting.versions import CONTENT_DRAFT_SCHEMA_VERSION
from slidestein.slots.roles import SlotRole


class SlotDraftAction(str, Enum):
    REPLACE = "replace"
    CLEAR = "clear"
    NEEDS_INPUT = "needs_input"


class SlotDraftAssignment(BaseModel):
    """Application-assembled result for one semantic slot.

    All identity and geometry fields come from the TemplateSlot; only
    action / text / missing_information come (indirectly) from the model.
    """

    model_config = ConfigDict(extra="forbid")

    slot_id: str
    shape_id: int
    shape_path: str

    slot_role: SlotRole
    semantic_label: str

    action: SlotDraftAction

    text: Optional[str] = None
    missing_information: Optional[str] = None

    character_count: int = 0
    capacity_characters: int
    capacity_utilization: float  # 0.0..1.0

    explicit_line_count: int = 0
    max_lines_estimate: int

    group_id: Optional[str] = None
    sequence_index: Optional[int] = None

    @model_validator(mode="after")
    def _validate_action_semantics(self) -> "SlotDraftAssignment":
        if self.action == SlotDraftAction.REPLACE:
            if not self.text or not self.text.strip():
                raise ValueError(
                    "action='replace' requires non-blank text"
                )
            if self.missing_information is not None:
                raise ValueError(
                    "action='replace' must have missing_information=None"
                )
        elif self.action == SlotDraftAction.CLEAR:
            if self.text is not None:
                raise ValueError(
                    "action='clear' must have text=None"
                )
            if self.missing_information is not None:
                raise ValueError(
                    "action='clear' must have missing_information=None"
                )
        elif self.action == SlotDraftAction.NEEDS_INPUT:
            if self.text is not None:
                raise ValueError(
                    "action='needs_input' must have text=None"
                )
            if not self.missing_information or not self.missing_information.strip():
                raise ValueError(
                    "action='needs_input' requires non-blank missing_information"
                )
        return self


class SlideContentDraft(BaseModel):
    """Complete content-drafting result for one slide.

    is_complete is application-derived: True iff no assignment has
    action==needs_input.  Claude never controls this field.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTENT_DRAFT_SCHEMA_VERSION
    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int
    brief_key_message: str
    assignments: list[SlotDraftAssignment]
    open_questions: list[str] = []
    drafting_summary: str
    is_complete: bool

    @field_validator("is_complete", mode="before")
    @classmethod
    def _is_complete_is_application_flag(cls, v: bool) -> bool:
        return v

    @model_validator(mode="after")
    def _is_complete_consistent_with_assignments(self) -> "SlideContentDraft":
        has_needs_input = any(
            a.action == SlotDraftAction.NEEDS_INPUT for a in self.assignments
        )
        if self.is_complete and has_needs_input:
            raise ValueError(
                "is_complete=True is inconsistent: assignments contain "
                "one or more needs_input slots"
            )
        if not self.is_complete and not has_needs_input:
            raise ValueError(
                "is_complete=False is inconsistent: no assignment has "
                "action=needs_input"
            )
        return self


class ContentDraftRequest(BaseModel):
    """Input bundle for the content drafting service."""

    model_config = ConfigDict(extra="forbid")

    source_material: Optional[str] = None
