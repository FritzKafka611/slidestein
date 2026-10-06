"""All pipeline-boundary domain models.

Dependency rule: this module imports nothing from slidestein itself.
Every stage of the pipeline passes a typed model defined here.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums — shared consulting vocabulary
# ---------------------------------------------------------------------------


class CommunicationJob(str, Enum):
    # M3 canonical taxonomy
    EXPLAIN = "explain"
    SUMMARISE = "summarise"
    COMPARE = "compare"
    DIAGNOSE = "diagnose"
    PRIORITISE = "prioritise"
    RECOMMEND = "recommend"
    SHOW_CHANGE = "show_change"
    SHOW_PROCESS = "show_process"
    SHOW_TIMELINE = "show_timeline"
    SHOW_HIERARCHY = "show_hierarchy"
    SHOW_PERFORMANCE = "show_performance"
    SHOW_DRIVERS = "show_drivers"
    SHOW_OPTIONS = "show_options"
    SHOW_RELATIONSHIP = "show_relationship"
    # Legacy values — preserved for backwards compatibility
    CONVINCE = "convince"
    INFORM = "inform"
    SHOW_PROGRESS = "show_progress"
    PRIORITIZE = "prioritize"


class StorylineRole(str, Enum):
    # M3 canonical taxonomy
    CONTEXT = "context"
    DIAGNOSIS = "diagnosis"
    INSIGHT = "insight"
    IMPLICATION = "implication"
    RECOMMENDATION = "recommendation"
    DECISION = "decision"
    PLAN = "plan"
    EVIDENCE = "evidence"
    SUMMARY = "summary"
    # Legacy values — preserved for backwards compatibility
    SITUATION = "situation"
    COMPLICATION = "complication"
    RESOLUTION = "resolution"
    NEXT_STEPS = "next_steps"


class VisualArchetype(str, Enum):
    # M3 canonical taxonomy
    TITLE = "title"
    KEY_MESSAGE = "key_message"
    TEXT_HEAVY = "text_heavy"
    METRIC_ROW = "metric_row"
    COMPARISON = "comparison"
    BEFORE_AFTER = "before_after"
    FUNNEL = "funnel"
    PYRAMID = "pyramid"
    MATRIX = "matrix"
    TIMELINE = "timeline"
    ROADMAP = "roadmap"
    PROCESS = "process"
    FLOW = "flow"
    HIERARCHY = "hierarchy"
    ORG_CHART = "org_chart"
    PORTFOLIO = "portfolio"
    STATUS_DASHBOARD = "status_dashboard"
    BAR_CHART = "bar_chart"
    LINE_CHART = "line_chart"
    WATERFALL = "waterfall"
    PIE_CHART = "pie_chart"
    TABLE = "table"
    MIXED_EXHIBIT = "mixed_exhibit"
    # Pre-existing additional value — useful but not in M3 canonical spec
    BUBBLE_CHART = "bubble_chart"
    # Legacy values — preserved for backwards compatibility
    TWO_BY_TWO = "2x2_matrix"
    PROCESS_FLOW = "process_flow"
    COMPARISON_TABLE = "comparison_table"
    TITLE_ONLY = "title_only"
    BULLETS = "bullets"


class DensityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContentSlotType(str, Enum):
    TITLE = "title"
    SUBTITLE = "subtitle"
    BODY = "body"
    BULLET = "bullet"
    CHART_DATA = "chart_data"
    LABEL = "label"


# ---------------------------------------------------------------------------
# Stage 1 input
# ---------------------------------------------------------------------------


class UserRequest(BaseModel):
    """Raw natural-language request from the user."""

    text: str


# ---------------------------------------------------------------------------
# Stage 1 output → Stage 2 input
# ---------------------------------------------------------------------------


class SlideBrief(BaseModel):
    """Structured consulting brief derived from a UserRequest."""

    key_message: str
    communication_job: CommunicationJob
    storyline_role: StorylineRole
    required_content_elements: list[str]
    preferred_visual_archetypes: list[VisualArchetype]
    source_request: str = Field(description="Original user text, preserved for tracing")


# ---------------------------------------------------------------------------
# Library / template primitives
# ---------------------------------------------------------------------------


class ContentSlot(BaseModel):
    """A single fillable placeholder in a PPTX template slide."""

    slot_id: str
    slot_type: ContentSlotType
    placeholder_name: str
    max_chars: Optional[int] = None
    value: Optional[str] = None


class SlideMetadata(BaseModel):
    """Catalogue entry for one PPTX template slide in the library."""

    slide_id: str
    template_path: Path
    archetype: VisualArchetype
    communication_jobs: list[CommunicationJob]
    content_slots: list[ContentSlot]
    description: str
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Ingestion record — one per slide in an ingested source deck
# ---------------------------------------------------------------------------


class SlideRecord(BaseModel):
    """Ingested record for a single slide from a source PPTX deck.

    Consulting semantics (archetype, communication_jobs, etc.) are intentionally
    left null at ingestion time and populated by the classification stage in a
    later milestone.

    Identity strategy
    -----------------
    slide_id = f"{deck_fingerprint[:12]}-{slide_number:03d}"
    deck_fingerprint = SHA-256(raw file bytes).hexdigest()

    This is:
      - Deterministic: same file + same slide → same ID on every run
      - Content-stable: survives file renames (fingerprint tracks content)
      - Human-readable: first 12 hex chars of deck hash + slide number
    """

    slide_id: str
    deck_fingerprint: str  # SHA-256 hex of the source file bytes (full 64-char string)
    source_deck_path: Path  # resolved absolute path at time of indexing
    slide_number: int  # 1-indexed

    # Extracted text (concatenated from all text frames, newline-separated)
    extracted_text: str = ""

    # Structural facts
    slide_width_emu: int = 0
    slide_height_emu: int = 0
    text_object_count: int = 0
    image_count: int = 0
    chart_count: int = 0
    table_count: int = 0
    shape_count: int = 0

    # Preview (null if rendering was skipped or failed)
    preview_path: Optional[Path] = None

    # Consulting semantics — null until classified (future milestone)
    archetype: Optional[VisualArchetype] = None
    communication_jobs: Optional[list[CommunicationJob]] = None
    storyline_role: Optional[StorylineRole] = None
    description: Optional[str] = None

    # M3.4 stable identity — null for records indexed before M3.4 migration
    deck_id: Optional[str] = None
    native_slide_id: Optional[int] = None
    content_fingerprint: Optional[str] = None
    structure_fingerprint: Optional[str] = None
    is_active: bool = True


def make_slide_id(deck_fingerprint: str, slide_number: int) -> str:
    """Build a legacy slide ID from deck fingerprint + slide number.

    Kept for backward compatibility with tests and pre-M3.4 records.
    New code should use make_stable_slide_id() from identity.slide_identity.
    """
    return f"{deck_fingerprint[:12]}-{slide_number:03d}"


# ---------------------------------------------------------------------------
# Stage 2 output → Stage 3 input
# ---------------------------------------------------------------------------


class SlideCandidate(BaseModel):
    """A retrieved template slide with its retrieval scores."""

    metadata: SlideMetadata
    similarity_score: float = Field(ge=0.0, le=1.0)
    job_fit_score: float = Field(ge=0.0, le=1.0)
    structural_capacity_score: float = Field(ge=0.0, le=1.0)
    archetype_score: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Stage 3 output → Stage 4 input
# ---------------------------------------------------------------------------


class SelectedSlide(BaseModel):
    """Vision-selected candidate with reasoning and empty slots ready to fill."""

    candidate: SlideCandidate
    vision_reasoning: str
    content_slots: list[ContentSlot]


# ---------------------------------------------------------------------------
# Stage 4 output → Stage 5 input
# ---------------------------------------------------------------------------


class DraftedContent(BaseModel):
    """Filled content slots produced by the drafting LLM."""

    slide: SelectedSlide
    filled_slots: list[ContentSlot]
    drafting_notes: str


# ---------------------------------------------------------------------------
# Stage 6 output — manager review
# ---------------------------------------------------------------------------


class ReviewDimension(BaseModel):
    passed: bool
    note: str


class ReviewResult(BaseModel):
    """Seven-dimension manager review of a drafted slide."""

    answer_first_title: ReviewDimension
    core_message_clarity: ReviewDimension
    vertical_logic: ReviewDimension
    exhibit_title_consistency: ReviewDimension
    mece_structure: ReviewDimension
    content_density: Literal["too_sparse", "appropriate", "too_dense"]
    approved: bool
    revision_instructions: Optional[str] = None


# ---------------------------------------------------------------------------
# Final pipeline output
# ---------------------------------------------------------------------------


class GeneratedSlide(BaseModel):
    """The finished output of the full pipeline."""

    pptx_path: Path
    preview_path: Optional[Path] = None
    review: ReviewResult
    revision_applied: bool = False


# ---------------------------------------------------------------------------
# M3.1 — Semantic domain models
# ---------------------------------------------------------------------------


class SlideSemanticProfile(BaseModel):
    """Semantic classification output for a single slide.

    Produced by the classifier (M3.2) from SlideClassificationInput.
    SlideRecord will carry an Optional[SlideSemanticProfile] field from M3.3
    onward once the store schema is updated.
    """

    schema_version: str = "1.0"
    slide_id: str
    primary_communication_job: CommunicationJob
    secondary_communication_jobs: list[CommunicationJob] = Field(default_factory=list)
    storyline_roles: list[StorylineRole] = Field(min_length=1)
    visual_archetype: VisualArchetype
    structural_pattern: str
    density: DensityLevel
    description: str
    best_for: list[str] = Field(default_factory=list)
    not_for: list[str] = Field(default_factory=list)

    @field_validator("slide_id")
    @classmethod
    def slide_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("slide_id must not be blank")
        return v

    @field_validator("description", "structural_pattern")
    @classmethod
    def non_whitespace_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must contain non-whitespace characters")
        return v

    @field_validator("best_for", "not_for", mode="before")
    @classmethod
    def dedup_list(cls, v: list) -> list:
        seen: set = set()
        result = []
        for item in v:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    @model_validator(mode="after")
    def secondary_jobs_no_duplicates(self) -> SlideSemanticProfile:
        primary = self.primary_communication_job
        seen = {primary}
        for job in self.secondary_communication_jobs:
            if job in seen:
                raise ValueError(
                    f"secondary_communication_jobs must not contain the primary job "
                    f"or duplicate entries; found {job!r}"
                )
            seen.add(job)
        return self


class SlideClassificationInput(BaseModel):
    """Input to the slide classifier (M3.2).

    Independent of the Anthropic client, COM editor, and PPT Master.
    Carries everything a classifier needs: identity, extracted text,
    structural facts, and an optional preview path for vision models.
    """

    slide_id: str
    extracted_text: str
    structural_metadata: dict[str, Any]
    preview_path: Optional[Path] = None


class ClassificationRecord(BaseModel):
    """A persisted classification result from the slide_classifications table."""

    id: Optional[int] = None
    slide_id: str
    classification_version: str
    model: str
    prompt_version: str
    input_fingerprint: str
    profile: SlideSemanticProfile
    classified_at: str = ""
