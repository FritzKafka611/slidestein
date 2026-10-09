"""ConsultingSlideBrief — structured interpretation of a natural-language slide request."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from slidestein.briefing.versions import SLIDE_BRIEF_SCHEMA_VERSION
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)


def _dedup_preserve_order(items: list) -> list:
    seen: set = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _normalize_string_list(values: list[str]) -> list[str]:
    """Strip whitespace, remove blanks, casefold-based dedup preserving first spelling."""
    seen_folded: set[str] = set()
    result: list[str] = []
    for raw in values:
        cleaned = raw.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in seen_folded:
            seen_folded.add(key)
            result.append(cleaned)
    return result


# ---------------------------------------------------------------------------
# LLM-output model — contains ONLY fields the model is responsible for.
# original_request and schema_version are application-owned and must not
# appear in the model response; extra="forbid" enforces this strictly.
# ---------------------------------------------------------------------------

class SlideBriefModelOutput(BaseModel):
    """Strict parse target for the raw LLM response.

    Contains only the fields Claude is allowed to return.
    Application-owned fields (original_request, schema_version) are absent
    here and injected by the provider after parsing.
    extra="forbid" ensures the model cannot slip in application-owned fields
    or any other unknown field.
    """

    model_config = ConfigDict(extra="forbid")

    key_message: str

    slide_function: SlideFunction

    primary_communication_job: Optional[CommunicationJob] = None
    secondary_communication_jobs: list[CommunicationJob] = []

    storyline_roles: list[StorylineRole] = []

    required_content_elements: list[str] = []
    preferred_visual_archetypes: list[VisualArchetype] = []

    density: Optional[DensityLevel] = None

    assumptions: list[str] = []
    open_questions: list[str] = []

    @field_validator("key_message", mode="after")
    @classmethod
    def key_message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("key_message must not be blank")
        return v

    @field_validator("secondary_communication_jobs", mode="before")
    @classmethod
    def dedup_secondary_jobs(cls, v: list) -> list:
        return _dedup_preserve_order(v)

    @field_validator("storyline_roles", mode="before")
    @classmethod
    def dedup_roles(cls, v: list) -> list:
        return _dedup_preserve_order(v)

    @field_validator("preferred_visual_archetypes", mode="before")
    @classmethod
    def dedup_archetypes(cls, v: list) -> list:
        return _dedup_preserve_order(v)

    @field_validator("required_content_elements", "assumptions", "open_questions", mode="before")
    @classmethod
    def normalize_string_lists(cls, v: list) -> list:
        return _normalize_string_list([str(x) for x in v])

    @model_validator(mode="after")
    def check_job_consistency(self) -> "SlideBriefModelOutput":
        content_functions = {SlideFunction.CONTENT}
        is_content = self.slide_function in content_functions

        if is_content and self.primary_communication_job is None:
            raise ValueError(
                "primary_communication_job must not be None for slide_function='content'"
            )

        if not is_content:
            if self.primary_communication_job is not None:
                raise ValueError(
                    f"primary_communication_job must be None for slide_function="
                    f"'{self.slide_function.value}' (non-content slides have no communication job)"
                )
            if self.secondary_communication_jobs:
                raise ValueError(
                    f"secondary_communication_jobs must be empty for slide_function="
                    f"'{self.slide_function.value}'"
                )

        if (
            self.primary_communication_job is not None
            and self.primary_communication_job in self.secondary_communication_jobs
        ):
            raise ValueError(
                f"primary_communication_job '{self.primary_communication_job.value}' "
                "must not also appear in secondary_communication_jobs"
            )

        return self


# ---------------------------------------------------------------------------
# ConsultingSlideBrief — the public application model.
# original_request and schema_version are always application-owned.
# ---------------------------------------------------------------------------

class ConsultingSlideBrief(BaseModel):
    """Structured interpretation of a natural-language slide request.

    Produced by the application by combining the LLM output (SlideBriefModelOutput)
    with application-owned fields (original_request, schema_version).
    Does NOT contain drafted slide content.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SLIDE_BRIEF_SCHEMA_VERSION

    original_request: str
    key_message: str

    slide_function: SlideFunction

    primary_communication_job: Optional[CommunicationJob] = None
    secondary_communication_jobs: list[CommunicationJob] = []

    storyline_roles: list[StorylineRole] = []

    required_content_elements: list[str] = []
    preferred_visual_archetypes: list[VisualArchetype] = []

    density: Optional[DensityLevel] = None

    assumptions: list[str] = []
    open_questions: list[str] = []

    @field_validator("original_request", mode="after")
    @classmethod
    def original_request_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("original_request must not be blank")
        return v

    @field_validator("key_message", mode="after")
    @classmethod
    def key_message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("key_message must not be blank")
        return v

    @field_validator("secondary_communication_jobs", mode="before")
    @classmethod
    def dedup_secondary_jobs(cls, v: list) -> list:
        return _dedup_preserve_order(v)

    @field_validator("storyline_roles", mode="before")
    @classmethod
    def dedup_roles(cls, v: list) -> list:
        return _dedup_preserve_order(v)

    @field_validator("preferred_visual_archetypes", mode="before")
    @classmethod
    def dedup_archetypes(cls, v: list) -> list:
        return _dedup_preserve_order(v)

    @field_validator("required_content_elements", "assumptions", "open_questions", mode="before")
    @classmethod
    def normalize_string_lists(cls, v: list) -> list:
        return _normalize_string_list([str(x) for x in v])

    @model_validator(mode="after")
    def check_job_consistency(self) -> "ConsultingSlideBrief":
        content_functions = {SlideFunction.CONTENT}
        is_content = self.slide_function in content_functions

        if is_content and self.primary_communication_job is None:
            raise ValueError(
                "primary_communication_job must not be None for slide_function='content'"
            )

        if not is_content:
            if self.primary_communication_job is not None:
                raise ValueError(
                    f"primary_communication_job must be None for slide_function="
                    f"'{self.slide_function.value}' (non-content slides have no communication job)"
                )
            if self.secondary_communication_jobs:
                raise ValueError(
                    f"secondary_communication_jobs must be empty for slide_function="
                    f"'{self.slide_function.value}'"
                )

        if (
            self.primary_communication_job is not None
            and self.primary_communication_job in self.secondary_communication_jobs
        ):
            raise ValueError(
                f"primary_communication_job '{self.primary_communication_job.value}' "
                "must not also appear in secondary_communication_jobs"
            )

        return self
