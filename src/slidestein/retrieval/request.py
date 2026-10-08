"""SlideRetrievalRequest — structured query model for hybrid slide retrieval."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    StorylineRole,
    VisualArchetype,
)


class SlideRetrievalRequest(BaseModel):
    """Structured query for hybrid slide retrieval.

    query_text is the only required field.  All structured dimensions are optional;
    omitting a dimension (or passing empty lists) excludes it from hybrid scoring.

    Field names align with the consulting-brief vocabulary so this model can
    evolve into a full SlideConsultingBrief in a later milestone.
    """

    query_text: str = Field(..., description="Natural-language description of the desired slide.")
    slide_function: Optional[SlideFunction] = None
    primary_communication_job: Optional[CommunicationJob] = None
    preferred_visual_archetypes: list[VisualArchetype] = Field(default_factory=list)
    storyline_roles: list[StorylineRole] = Field(default_factory=list)
    density: Optional[DensityLevel] = None
    required_content_elements: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1)
    strict_slide_function: bool = False

    @field_validator("query_text")
    @classmethod
    def query_text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query_text must not be blank.")
        return v

    @field_validator("required_content_elements")
    @classmethod
    def normalize_elements(cls, v: list[str]) -> list[str]:
        """Strip whitespace, remove blanks, and deduplicate case-insensitively.

        Preserves the first human-readable spelling of each element and the
        original relative order.
        """
        seen: set[str] = set()
        result: list[str] = []
        for el in v:
            cleaned = el.strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result

    @field_validator("preferred_visual_archetypes")
    @classmethod
    def dedup_archetypes(cls, v: list[VisualArchetype]) -> list[VisualArchetype]:
        seen: set[VisualArchetype] = set()
        return [a for a in v if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]

    @field_validator("storyline_roles")
    @classmethod
    def dedup_roles(cls, v: list[StorylineRole]) -> list[StorylineRole]:
        seen: set[StorylineRole] = set()
        return [r for r in v if not (r in seen or seen.add(r))]  # type: ignore[func-returns-value]

    @model_validator(mode="after")
    def strict_function_requires_function(self) -> "SlideRetrievalRequest":
        if self.strict_slide_function and self.slide_function is None:
            raise ValueError(
                "strict_slide_function=True requires slide_function to be specified."
            )
        return self

    model_config = {"frozen": True}


def build_enriched_query(request: SlideRetrievalRequest) -> str:
    """Return the query string to embed, enriched with required_content_elements.

    If required_content_elements is empty, returns query_text unchanged.
    Otherwise appends a 'Required content:' section with a bulleted list,
    separated from the query by a blank line.

    Format when elements are present:
        <query_text>

        Required content:
        - <element 1>
        - <element 2>
        ...
    """
    if not request.required_content_elements:
        return request.query_text
    bullets = "\n".join(f"- {el}" for el in request.required_content_elements)
    return f"{request.query_text}\n\nRequired content:\n{bullets}"
