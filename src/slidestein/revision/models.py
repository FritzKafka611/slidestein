"""Domain models for M9 Bounded Revision Orchestration (v1.1).

RevisionRoute               — enum of four possible routes
RevisionRequest             — full input bundle for one orchestration cycle
RevisionPlan                — deterministic routing result (0 API calls to produce)
RevisionChange              — one K-key patch returned by the reviser
ContentRevisionModelOutput  — LLM parse target (strict, extra=forbid)
ContentRevisionResult       — application-owned result from ContentRevisionService
RevisionCycleResult         — final result returned to caller after orchestration
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.drafting.models import SlideContentDraft
from slidestein.qa.models import VisualQAResult
from slidestein.review.models import ManagerReviewResult
from slidestein.revision.versions import (
    REVISION_POLICY_VERSION,
    REVISION_PROMPT_VERSION,
    REVISION_SCHEMA_VERSION,
)
from slidestein.slots.models import TemplateSlotMap
from slidestein.writeback.models import PowerPointWritebackResult

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# RevisionRoute
# ---------------------------------------------------------------------------


class RevisionRoute(str, Enum):
    FINALIZE = "finalize"
    CONTENT_REVISION = "content_revision"
    TEMPLATE_RESELECTION = "template_reselection"
    MANUAL_REVIEW = "manual_review"


# ---------------------------------------------------------------------------
# RevisionRequest  (input bundle for one orchestration cycle)
# ---------------------------------------------------------------------------


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: ConsultingSlideBrief
    draft: SlideContentDraft
    slot_map: TemplateSlotMap
    manager_review: ManagerReviewResult
    visual_qa: VisualQAResult
    source_material: Optional[str] = None

    template_pptx: Optional[Path] = None
    output_pptx: Optional[Path] = None
    overwrite: bool = False


# ---------------------------------------------------------------------------
# RevisionPlan  (deterministic routing result — no API calls to produce)
# ---------------------------------------------------------------------------


class RevisionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REVISION_SCHEMA_VERSION
    policy_version: str = REVISION_POLICY_VERSION

    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int

    route: RevisionRoute
    reasons: list[str]

    manager_issue_indexes: list[int] = []
    visual_issue_indexes: list[int] = []
    factual_flag_indexes: list[int] = []

    target_slot_keys: list[str] = []
    max_revision_cycles: int = 1
    requires_model_call: bool

    @field_validator("reasons")
    @classmethod
    def reasons_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("reasons must not be empty")
        return v


# ---------------------------------------------------------------------------
# RevisionChange  (one K-key patch returned by the reviser)
# ---------------------------------------------------------------------------


class RevisionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    action: Literal["replace", "clear"]
    text: Optional[str] = None

    @field_validator("key")
    @classmethod
    def key_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("key must not be blank")
        return v

    @model_validator(mode="after")
    def text_consistent_with_action(self) -> "RevisionChange":
        if self.action == "replace":
            if self.text is None or not self.text.strip():
                raise ValueError(
                    "action='replace' requires non-empty text"
                )
        elif self.action == "clear":
            if self.text is not None:
                raise ValueError(
                    "action='clear' requires text=None"
                )
        return self


# ---------------------------------------------------------------------------
# ContentRevisionModelOutput  (LLM parse target — strict, extra=forbid)
# ---------------------------------------------------------------------------


class ContentRevisionModelOutput(BaseModel):
    """Parse target for the content revision LLM response.

    `status` is "revised" when changes were applied, "blocked" when the model
    could not produce valid revisions within the given constraints.
    `changes` contains ONLY the K-keys the reviser wants to change.
    Unmentioned slots must be left exactly as they are in the original draft.
    `blocked_reason` is required when status="blocked", null otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["revised", "blocked"]
    changes: list[RevisionChange]
    change_summary: str
    blocked_reason: Optional[str] = None

    @field_validator("change_summary")
    @classmethod
    def summary_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("change_summary must not be blank")
        return v

    @model_validator(mode="after")
    def status_changes_consistent(self) -> "ContentRevisionModelOutput":
        if self.status == "revised":
            if len(self.changes) < 1:
                raise ValueError(
                    "status='revised' requires at least one change in changes"
                )
            if self.blocked_reason is not None:
                raise ValueError(
                    "status='revised' must have blocked_reason=None"
                )
        elif self.status == "blocked":
            if self.changes:
                raise ValueError(
                    "status='blocked' must have changes=[]"
                )
            if not self.blocked_reason or not self.blocked_reason.strip():
                raise ValueError(
                    "status='blocked' requires a non-empty blocked_reason"
                )
        return self


# ---------------------------------------------------------------------------
# ContentRevisionResult  (application-owned result from ContentRevisionService)
# ---------------------------------------------------------------------------


class ContentRevisionResult(BaseModel):
    """Application-owned result of one ContentRevisionService.revise() call.

    `status` is "revised" when the draft was patched, "blocked" when the model
    indicated it could not produce a valid revision.
    `revised_draft` is None when status="blocked".
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["revised", "blocked"]
    revised_draft: Optional[SlideContentDraft] = None
    applied_changes: list[RevisionChange] = []
    change_summary: str
    blocked_reason: Optional[str] = None

    @field_validator("change_summary")
    @classmethod
    def summary_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("change_summary must not be blank")
        return v

    @model_validator(mode="after")
    def status_fields_consistent(self) -> "ContentRevisionResult":
        if self.status == "revised":
            if self.revised_draft is None:
                raise ValueError(
                    "status='revised' requires revised_draft to be non-None"
                )
            if self.blocked_reason is not None:
                raise ValueError(
                    "status='revised' must have blocked_reason=None"
                )
        elif self.status == "blocked":
            if self.revised_draft is not None:
                raise ValueError(
                    "status='blocked' must have revised_draft=None"
                )
            if self.applied_changes:
                raise ValueError(
                    "status='blocked' must have applied_changes=[]"
                )
            if not self.blocked_reason or not self.blocked_reason.strip():
                raise ValueError(
                    "status='blocked' requires a non-empty blocked_reason"
                )
        return self


# ---------------------------------------------------------------------------
# RevisionCycleResult  (final result returned after orchestration)
# ---------------------------------------------------------------------------


def _default_model_calls() -> dict:
    return {"revision": 0, "manager_review": 0, "visual_qa": 0}


class RevisionCycleResult(BaseModel):
    """Result of one bounded revision cycle.

    `status` values:
      finalized          — route=finalize; no API calls; final_ready=True
      revised            — route=content_revision; revision succeeded
      blocked            — route=content_revision; reviser returned blocked
      escalation_required — route=template_reselection or manual_review

    `model_calls` counts ATTEMPTS (incremented before each provider call;
    failures count as attempts, not just successes).

    Maximum: revision=1, manager_review=1, visual_qa=1 (total ≤ 3).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = REVISION_SCHEMA_VERSION
    policy_version: str = REVISION_POLICY_VERSION
    prompt_version: str = REVISION_PROMPT_VERSION

    route: RevisionRoute

    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int

    plan: RevisionPlan
    status: Literal["finalized", "revised", "blocked", "escalation_required"]

    revised_draft: Optional[SlideContentDraft] = None
    writeback_result: Optional[PowerPointWritebackResult] = None

    manager_review_after: Optional[ManagerReviewResult] = None
    visual_qa_after: Optional[VisualQAResult] = None

    final_ready: bool = False
    output_pptx: Optional[Path] = None

    model_calls: dict = Field(default_factory=_default_model_calls)
