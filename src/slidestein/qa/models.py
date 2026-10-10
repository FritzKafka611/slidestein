"""M8 Visual QA domain models.

NOTE: do NOT add "from __future__ import annotations" to this module.
VisualQARequest holds Pydantic-validated fields whose types must be concrete
at class-definition time so callers can construct and validate the model
without calling model_rebuild().  SlideContentDraft and TemplateSlotMap are
imported directly — no circular dependency exists between qa, drafting, and
slots packages.
"""

from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from slidestein.drafting.models import SlideContentDraft
from slidestein.qa.versions import VISUAL_QA_PROMPT_VERSION, VISUAL_QA_SCHEMA_VERSION
from slidestein.slots.models import TemplateSlotMap


# ---------------------------------------------------------------------------
# Native deterministic checks
# ---------------------------------------------------------------------------


class NativeCheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class NativeCheckType(str, Enum):
    TEXT_OVERFLOW = "text_overflow"
    OUTSIDE_SLIDE_BOUNDS = "outside_slide_bounds"
    TEXT_FRAME_READABILITY = "text_frame_readability"
    RENDERING_IDENTITY = "rendering_identity"


class NativeVisualCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_type: NativeCheckType
    slot_key: Optional[str] = None
    status: NativeCheckStatus
    details: str


# ---------------------------------------------------------------------------
# Vision model output models (parse target — extra=forbid)
# ---------------------------------------------------------------------------


class VisualDimensionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int
    rationale: str

    @field_validator("score")
    @classmethod
    def score_in_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError(f"score must be 1..5, got {v}")
        return v

    @field_validator("rationale")
    @classmethod
    def rationale_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must not be blank")
        return v


class VisualQAIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["critical", "major", "minor"]
    category: Literal[
        "text_fit_and_clipping",
        "visual_hierarchy",
        "alignment_and_spacing",
        "balance_and_whitespace",
        "typography_and_style_consistency",
        "overall_readability",
    ]
    slot_keys: list[str] = Field(default_factory=list)
    issue: str
    evidence: str
    recommendation: str

    @field_validator("issue", "recommendation", "evidence")
    @classmethod
    def non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v


class VisualQAModelOutput(BaseModel):
    """LLM parse target — Claude must NOT return average_score, paths, or native checks."""

    model_config = ConfigDict(extra="forbid")

    recommendation: Literal["pass", "revise"]
    text_fit_and_clipping: VisualDimensionAssessment
    visual_hierarchy: VisualDimensionAssessment
    alignment_and_spacing: VisualDimensionAssessment
    balance_and_whitespace: VisualDimensionAssessment
    typography_and_style_consistency: VisualDimensionAssessment
    overall_readability: VisualDimensionAssessment
    issues: list[VisualQAIssue] = Field(default_factory=list)
    executive_summary: str

    @field_validator("executive_summary")
    @classmethod
    def summary_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("executive_summary must not be blank")
        return v


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class VisualQARequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_pptx: Path
    generated_pptx: Path
    draft: SlideContentDraft
    slot_map: TemplateSlotMap


# ---------------------------------------------------------------------------
# Application-owned result
# ---------------------------------------------------------------------------


class VisualQAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = VISUAL_QA_SCHEMA_VERSION
    prompt_version: str = VISUAL_QA_PROMPT_VERSION

    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int
    resolved_generated_slide_number: int

    recommendation: Literal["pass", "revise"]

    text_fit_and_clipping: VisualDimensionAssessment
    visual_hierarchy: VisualDimensionAssessment
    alignment_and_spacing: VisualDimensionAssessment
    balance_and_whitespace: VisualDimensionAssessment
    typography_and_style_consistency: VisualDimensionAssessment
    overall_readability: VisualDimensionAssessment

    average_score: float

    native_checks: list[NativeVisualCheck] = Field(default_factory=list)
    issues: list[VisualQAIssue] = Field(default_factory=list)
    executive_summary: str

    generated_render_path: str
    template_render_path: str
    overlay_render_path: str
