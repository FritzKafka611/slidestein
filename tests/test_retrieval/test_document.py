"""Tests for the retrieval document builder.

Verifies:
- Deterministic output
- All intended V2 fields included
- null job handled correctly
- best_for, structural_pattern, description included
- NOT included: slide_id, extracted text, not_for, fingerprints
"""

from __future__ import annotations

import pytest

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    SlideSemanticProfileV2,
    StorylineRole,
    VisualArchetype,
)
from slidestein.retrieval.document import build_retrieval_document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_profile(**overrides) -> SlideSemanticProfileV2:
    kwargs = dict(
        slide_id="test-slide-001",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SUMMARISE,
        secondary_communication_jobs=[CommunicationJob.EXPLAIN],
        storyline_roles=[StorylineRole.PLAN, StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.STRUCTURED_ONE_PAGER,
        structural_pattern="Five labeled rows covering team, objective, deliverables.",
        density=DensityLevel.HIGH,
        description="A workstream charter summarising scope and team.",
        best_for=["program governance", "initiative charters"],
        not_for=["quantitative analysis"],
    )
    kwargs.update(overrides)
    return SlideSemanticProfileV2(**kwargs)


def _nav_profile(func=SlideFunction.SECTION_DIVIDER, **overrides) -> SlideSemanticProfileV2:
    kwargs = dict(
        slide_id="test-nav-001",
        slide_function=func,
        primary_communication_job=None,
        secondary_communication_jobs=[],
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.TITLE,
        structural_pattern="Single centred title with decorative element.",
        density=DensityLevel.LOW,
        description="Section divider slide.",
        best_for=["deck structure"],
        not_for=["detailed content"],
    )
    kwargs.update(overrides)
    return SlideSemanticProfileV2(**kwargs)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_profiles_produce_identical_documents(self) -> None:
        p = _content_profile()
        assert build_retrieval_document(p) == build_retrieval_document(p)

    def test_two_equal_profiles_produce_same_document(self) -> None:
        p1 = _content_profile()
        p2 = _content_profile()
        assert build_retrieval_document(p1) == build_retrieval_document(p2)


# ---------------------------------------------------------------------------
# Required fields — content slide
# ---------------------------------------------------------------------------


class TestContentSlideFields:
    def test_slide_function_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "content" in doc

    def test_primary_job_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "summarise" in doc

    def test_secondary_jobs_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "explain" in doc

    def test_storyline_roles_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "plan" in doc
        assert "context" in doc

    def test_visual_archetype_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "structured_one_pager" in doc

    def test_density_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "high" in doc

    def test_description_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "workstream charter" in doc.lower()

    def test_structural_pattern_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "five labeled rows" in doc.lower()

    def test_best_for_included(self) -> None:
        doc = build_retrieval_document(_content_profile())
        assert "program governance" in doc
        assert "initiative charters" in doc


# ---------------------------------------------------------------------------
# Required fields — section divider (null job)
# ---------------------------------------------------------------------------


class TestNavSlideNullJob:
    def test_null_job_produces_none_literal(self) -> None:
        doc = build_retrieval_document(_nav_profile())
        assert "Communication job: none" in doc

    def test_empty_secondary_jobs_represented(self) -> None:
        doc = build_retrieval_document(_nav_profile())
        assert "Secondary communication jobs: none" in doc

    def test_section_divider_function_present(self) -> None:
        doc = build_retrieval_document(_nav_profile())
        assert "section_divider" in doc


# ---------------------------------------------------------------------------
# Explicitly excluded fields
# ---------------------------------------------------------------------------


class TestExcludedFields:
    def test_slide_id_not_in_document(self) -> None:
        p = _content_profile(slide_id="super-secret-slide-id-xyz")
        doc = build_retrieval_document(p)
        assert "super-secret-slide-id-xyz" not in doc

    def test_not_for_not_in_document(self) -> None:
        p = _content_profile(not_for=["confidential-negative-use"])
        doc = build_retrieval_document(p)
        assert "confidential-negative-use" not in doc

    def test_no_raw_fingerprint_strings(self) -> None:
        doc = build_retrieval_document(_content_profile())
        # Fingerprints are hex strings of 64 chars — none should appear
        import re
        assert not re.search(r"\b[0-9a-f]{64}\b", doc)
