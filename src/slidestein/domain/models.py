"""All pipeline-boundary domain models.

Dependency rule: this module imports nothing from slidestein itself.
Every stage of the pipeline passes a typed model defined here.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums — shared consulting vocabulary
# ---------------------------------------------------------------------------


class CommunicationJob(str, Enum):
    CONVINCE = "convince"
    INFORM = "inform"
    RECOMMEND = "recommend"
    COMPARE = "compare"
    SHOW_PROGRESS = "show_progress"
    PRIORITIZE = "prioritize"


class StorylineRole(str, Enum):
    SITUATION = "situation"
    COMPLICATION = "complication"
    RESOLUTION = "resolution"
    EVIDENCE = "evidence"
    NEXT_STEPS = "next_steps"


class VisualArchetype(str, Enum):
    TWO_BY_TWO = "2x2_matrix"
    WATERFALL = "waterfall"
    PROCESS_FLOW = "process_flow"
    COMPARISON_TABLE = "comparison_table"
    PYRAMID = "pyramid"
    TIMELINE = "timeline"
    BAR_CHART = "bar_chart"
    BUBBLE_CHART = "bubble_chart"
    TITLE_ONLY = "title_only"
    BULLETS = "bullets"


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
