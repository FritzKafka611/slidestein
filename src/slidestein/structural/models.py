"""Domain models for M10 Structural Recovery & Template Reselection (v1.0).

StructuralRecoveryRoute      — enum of three possible recovery routes
StructuralDrift              — one shape-level geometry discrepancy
StructuralRecoveryRequest    — full input bundle for one recovery cycle
StructuralRecoveryPlan       — deterministic routing result (0 API calls to produce)
CandidateReference           — application-owned identity of the selected alternate
StructuralSelectionOutput    — application-owned result of one template-selection call
StructuralCandidateInfo      — structural metadata for one candidate (pre-Vision)
StructuralRecoveryResult     — final result returned to caller after recovery
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
from slidestein.revision.models import RevisionPlan
from slidestein.slots.models import TemplateSlotMap
from slidestein.structural.versions import (
    STRUCTURAL_RECOVERY_POLICY_VERSION,
    STRUCTURAL_RECOVERY_PROMPT_VERSION,
    STRUCTURAL_RECOVERY_SCHEMA_VERSION,
)
from slidestein.writeback.models import PowerPointWritebackResult

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# StructuralRecoveryRoute
# ---------------------------------------------------------------------------


class StructuralRecoveryRoute(str, Enum):
    REBUILD_CURRENT_TEMPLATE = "rebuild_current_template"
    RESELECT_TEMPLATE = "reselect_template"
    MANUAL_REVIEW = "manual_review"


# ---------------------------------------------------------------------------
# StructuralDrift  (one shape-level geometry discrepancy)
# ---------------------------------------------------------------------------


class StructuralDrift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    slot_id: str
    shape_path: str

    template_geometry: dict
    generated_geometry: Optional[dict] = None

    drift_type: Literal[
        "missing_shape",
        "position_changed",
        "size_changed",
        "position_and_size_changed",
    ]


# ---------------------------------------------------------------------------
# StructuralRecoveryRequest  (input bundle for one recovery cycle)
# ---------------------------------------------------------------------------


class StructuralRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: ConsultingSlideBrief
    source_material: Optional[str] = None

    current_draft: SlideContentDraft
    current_slot_map: TemplateSlotMap

    manager_review: ManagerReviewResult
    visual_qa: VisualQAResult

    m9_plan: RevisionPlan

    template_pptx: Path
    generated_pptx: Path

    output_pptx: Optional[Path] = None
    artifacts_dir: Optional[Path] = None

    overwrite: bool = False


# ---------------------------------------------------------------------------
# StructuralRecoveryPlan  (deterministic routing result — no API calls)
# ---------------------------------------------------------------------------


class StructuralRecoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = STRUCTURAL_RECOVERY_SCHEMA_VERSION
    policy_version: str = STRUCTURAL_RECOVERY_POLICY_VERSION

    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int

    route: StructuralRecoveryRoute
    reasons: list[str]

    structural_drifts: list[StructuralDrift] = []

    current_template_slide_id: str

    requires_candidate_retrieval: bool
    requires_selection_call: bool
    requires_redraft_call: bool

    max_structural_cycles: int = 1

    @field_validator("reasons")
    @classmethod
    def reasons_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("reasons must not be empty")
        return v


# ---------------------------------------------------------------------------
# CandidateReference  (application-owned selected-candidate identity)
# ---------------------------------------------------------------------------


class CandidateReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_key: str
    slide_id: str
    deck_id: str
    slide_number: int
    hybrid_rank: int
    structural_fingerprint: str


# ---------------------------------------------------------------------------
# StructuralCandidateInfo  (pre-Vision structural summary for one candidate)
# ---------------------------------------------------------------------------


class StructuralCandidateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_key: str
    slide_id: str
    deck_id: str
    slide_number: int

    has_title_slot: bool
    editable_slot_count: int
    slot_count: int
    slot_summary: str
    structural_fingerprint: str
    visual_archetype: str = ""


# ---------------------------------------------------------------------------
# StructuralSelectionOutput  (application-owned result of selection call)
# ---------------------------------------------------------------------------


class StructuralSelectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_candidate_key: str
    rationale: str

    @field_validator("selected_candidate_key", "rationale")
    @classmethod
    def non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v


# ---------------------------------------------------------------------------
# StructuralRecoveryResult  (final result after one recovery cycle)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# StructuralCandidateEligibility  (one record per retrieval result)
# ---------------------------------------------------------------------------


class StructuralCandidateEligibility(BaseModel):
    """Audit record for one retrieved candidate slide.

    Exactly one record per hybrid-search result.  No duplicate entries.
    eligible=True only if the candidate passed all filters and rendered.
    """

    model_config = ConfigDict(extra="forbid")

    slide_id: str
    deck_id: Optional[str] = None
    slide_number: Optional[int] = None
    retrieval_rank: Optional[int] = None

    candidate_key: Optional[str] = None

    title_slot_available: Optional[bool] = None
    editable_semantic_slot_count: Optional[int] = None
    structural_fingerprint: Optional[str] = None
    visual_archetype: Optional[str] = None

    slot_map_available: Optional[bool] = None
    rendered_successfully: Optional[bool] = None

    eligible: bool
    exclusion_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# StructuralRecoveryResult helpers
# ---------------------------------------------------------------------------


def _default_model_calls() -> dict:
    return {
        "retrieval_embedding": 0,
        "template_selection": 0,
        "drafting": 0,
        "manager_review": 0,
        "visual_qa": 0,
    }


class StructuralRecoveryResult(BaseModel):
    """Result of one bounded structural recovery cycle.

    status values:
      rebuilt              — route=rebuild_current_template; M6 + M8 complete
      reselected           — route=reselect_template; all stages complete
      blocked              — draft incomplete / no viable candidates
      escalation_required  — manual_review route or unrecoverable failure

    model_calls counts ATTEMPTS (incremented before each provider boundary;
    failures count as attempts).  Maximum: selection=1, drafting=1,
    manager_review=1, visual_qa=1 (total ≤ 4 + 1 embedding).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = STRUCTURAL_RECOVERY_SCHEMA_VERSION
    policy_version: str = STRUCTURAL_RECOVERY_POLICY_VERSION
    prompt_version: str = STRUCTURAL_RECOVERY_PROMPT_VERSION

    route: StructuralRecoveryRoute
    status: Literal["rebuilt", "reselected", "blocked", "escalation_required"]

    slide_id: str
    deck_id: Optional[str] = None
    slide_number: int

    plan: StructuralRecoveryPlan

    content_changed: bool

    selected_candidate: Optional[CandidateReference] = None

    selected_slot_map: Optional[TemplateSlotMap] = None
    selected_draft: Optional[SlideContentDraft] = None

    writeback_result: Optional[PowerPointWritebackResult] = None

    manager_review_after: Optional[ManagerReviewResult] = None
    manager_review_effective: ManagerReviewResult

    visual_qa_after: Optional[VisualQAResult] = None

    final_ready: bool = False

    output_pptx: Optional[Path] = None

    model_calls: dict = Field(default_factory=_default_model_calls)

    candidate_eligibility_log: Optional[list[StructuralCandidateEligibility]] = None
