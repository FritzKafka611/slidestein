"""Domain models for M7 Manager Review.

ManagerReviewRequest         — input to ManagerReviewService.review()
DimensionAssessment          — score + rationale for one rubric dimension
ManagerReviewIssue           — one actionable issue found during review
ManagerReviewModelOutput     — LLM parse target (extra=forbid, strict)
ManagerReviewResult          — application-owned result returned to caller
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.drafting.models import SlideContentDraft
from slidestein.review.versions import (
    MANAGER_REVIEW_PROMPT_VERSION,
    MANAGER_REVIEW_SCHEMA_VERSION,
)
from slidestein.slots.models import TemplateSlotMap


# ---------------------------------------------------------------------------
# ManagerReviewRequest
# ---------------------------------------------------------------------------


class ManagerReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: ConsultingSlideBrief
    draft: SlideContentDraft
    slot_map: TemplateSlotMap
    source_material: Optional[str] = None


# ---------------------------------------------------------------------------
# DimensionAssessment
# ---------------------------------------------------------------------------


class DimensionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int
    rationale: str

    @field_validator("score")
    @classmethod
    def score_in_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError(f"score must be between 1 and 5 inclusive, got {v}")
        return v

    @field_validator("rationale")
    @classmethod
    def rationale_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must not be blank")
        return v


# ---------------------------------------------------------------------------
# ManagerReviewIssue
# ---------------------------------------------------------------------------


class ManagerReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["critical", "major", "minor"]
    category: Literal[
        "answer_first_title",
        "core_message_clarity",
        "vertical_logic",
        "exhibit_title_consistency",
        "mece_structure",
        "content_density",
        "factual_grounding",
    ]
    slot_keys: list[str] = []
    issue: str
    recommendation: str

    @field_validator("issue", "recommendation")
    @classmethod
    def non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("issue and recommendation must not be blank")
        return v


# ---------------------------------------------------------------------------
# ManagerReviewModelOutput  (LLM parse target)
# ---------------------------------------------------------------------------


class ManagerReviewModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Literal["approve", "revise"]
    answer_first_title: DimensionAssessment
    core_message_clarity: DimensionAssessment
    vertical_logic: DimensionAssessment
    exhibit_title_consistency: DimensionAssessment
    mece_structure: DimensionAssessment
    content_density: DimensionAssessment
    issues: list[ManagerReviewIssue] = []
    factual_flags: list[ManagerReviewIssue] = []
    executive_summary: str

    @field_validator("executive_summary")
    @classmethod
    def executive_summary_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("executive_summary must not be blank")
        return v

    @field_validator("factual_flags", mode="after")
    @classmethod
    def factual_flags_category_grounding(
        cls, v: list["ManagerReviewIssue"]
    ) -> list["ManagerReviewIssue"]:
        for item in v:
            if item.category != "factual_grounding":
                raise ValueError(
                    f"factual_flags item has category={item.category!r}; "
                    "every factual_flag must have category='factual_grounding'"
                )
        return v


# ---------------------------------------------------------------------------
# ManagerReviewResult  (application-owned)
# ---------------------------------------------------------------------------


class ManagerReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MANAGER_REVIEW_SCHEMA_VERSION
    prompt_version: str = MANAGER_REVIEW_PROMPT_VERSION

    # Application-owned slide identity — populated from validated draft/slot_map
    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int

    recommendation: Literal["approve", "revise"]
    average_score: float
    answer_first_title: DimensionAssessment
    core_message_clarity: DimensionAssessment
    vertical_logic: DimensionAssessment
    exhibit_title_consistency: DimensionAssessment
    mece_structure: DimensionAssessment
    content_density: DimensionAssessment
    issues: list[ManagerReviewIssue] = []
    factual_flags: list[ManagerReviewIssue] = []
    executive_summary: str
