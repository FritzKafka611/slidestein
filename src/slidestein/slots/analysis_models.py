"""Vision output models for M5.2 slot semantic analysis.

ShapeSemanticAssessment and SlotAnalysisModelOutput are strict parse targets
for the LLM response.  extra="forbid" ensures Vision cannot inject unexpected
fields.  Application-owned fields (shape_id, geometry, editable, capacity)
are NOT present here — the service merges them after parsing.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from slidestein.slots.roles import SlotRole


class ShapeSemanticAssessment(BaseModel):
    """Vision's assessment of one editable shape candidate.

    candidate_key refers to the S1..Sn key supplied in the prompt — never
    a native shape_id.  The service maps back to shape_path after parsing.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_key: str       # must be one of the supplied S1..Sn keys
    include_as_slot: bool    # semantic significance: True = content slot
    slot_role: SlotRole
    semantic_label: str
    group_key: Optional[str] = None   # e.g. "workstream_1"; groups related shapes
    group_role: Optional[str] = None  # semantic role of the group
    sequence_index: Optional[int] = None
    confidence: float         # 0..1
    rationale: str

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return v

    @field_validator("sequence_index")
    @classmethod
    def _sequence_index_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError(f"sequence_index must be >= 0, got {v}")
        return v


class SlotAnalysisModelOutput(BaseModel):
    """Top-level Vision response model for slot analysis.

    Validates that no candidate_key appears more than once across assessments.
    """

    model_config = ConfigDict(extra="forbid")

    assessments: list[ShapeSemanticAssessment]
    analysis_summary: str

    @model_validator(mode="after")
    def _no_duplicate_candidate_keys(self) -> "SlotAnalysisModelOutput":
        seen: set[str] = set()
        for a in self.assessments:
            if a.candidate_key in seen:
                raise ValueError(
                    f"Duplicate candidate_key in assessments: {a.candidate_key!r}"
                )
            seen.add(a.candidate_key)
        return self
