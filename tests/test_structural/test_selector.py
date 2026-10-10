"""Tests for M10 build_structural_selection_prompt (pure function)."""

from __future__ import annotations

from slidestein.structural.models import StructuralCandidateInfo
from slidestein.structural.selector import (
    _SYSTEM_PROMPT,
    build_structural_selection_prompt,
)

from .conftest import make_brief


# ---------------------------------------------------------------------------
# _SYSTEM_PROMPT
# ---------------------------------------------------------------------------


def test_system_prompt_json_only():
    assert "JSON" in _SYSTEM_PROMPT or "json" in _SYSTEM_PROMPT


def test_system_prompt_prompt_injection_warning():
    # Must include injection boundary instructions
    assert "untrusted" in _SYSTEM_PROMPT.lower() or "DATA" in _SYSTEM_PROMPT


def test_system_prompt_non_empty():
    assert len(_SYSTEM_PROMPT.strip()) > 50


# ---------------------------------------------------------------------------
# build_structural_selection_prompt — pure function
# ---------------------------------------------------------------------------


def _make_candidates(n: int = 2) -> list[StructuralCandidateInfo]:
    return [
        StructuralCandidateInfo(
            candidate_key=f"SC{i + 1}",
            slide_id=f"slide-cand-{i + 1:03d}",
            deck_id="deck-001",
            slide_number=i + 3,
            has_title_slot=True,
            editable_slot_count=3,
            slot_count=4,
            slot_summary=f"K1 (title); K{i + 2} (body)",
            structural_fingerprint=f"fp-cand-{i + 1:03d}",
        )
        for i in range(n)
    ]


def test_prompt_contains_brief_key_message():
    brief = make_brief(key_message="Transform core processes.")
    candidates = _make_candidates(2)
    prompt = build_structural_selection_prompt(brief, [], candidates, "slide-cur-001")
    assert "Transform core processes" in prompt


def test_prompt_contains_candidate_keys():
    brief = make_brief()
    candidates = _make_candidates(3)
    prompt = build_structural_selection_prompt(brief, [], candidates, "slide-cur-001")
    for i in range(1, 4):
        assert f"SC{i}" in prompt


def test_prompt_current_template_excluded_noted():
    brief = make_brief()
    candidates = _make_candidates(2)
    current_id = "slide-cur-001"
    prompt = build_structural_selection_prompt(brief, [], candidates, current_id)
    # Current template should be called out as excluded/failed
    assert current_id[:8] in prompt or "CURRENT" in prompt or "excluded" in prompt.lower()


def test_prompt_contains_output_schema():
    brief = make_brief()
    prompt = build_structural_selection_prompt(brief, [], _make_candidates(), "slide-x")
    assert "selected_candidate_key" in prompt
    assert "rationale" in prompt


def test_prompt_structural_issues_appear():
    from slidestein.qa.models import VisualQAIssue
    brief = make_brief()
    issues = [
        VisualQAIssue(
            severity="major",
            category="balance_and_whitespace",
            issue="70% empty whitespace on the right side.",
            evidence="Right half of slide is blank.",
            recommendation="Use a layout that fills the space.",
        )
    ]
    candidates = _make_candidates(1)
    prompt = build_structural_selection_prompt(brief, issues, candidates, "slide-x")
    assert "balance_and_whitespace" in prompt
    # Untrusted issue text should appear in DATA section, not as instructions
    assert "70% empty whitespace" in prompt


def test_prompt_candidate_slot_summary_included():
    brief = make_brief()
    candidates = [
        StructuralCandidateInfo(
            candidate_key="SC1",
            slide_id="slide-c1",
            deck_id="deck-001",
            slide_number=3,
            has_title_slot=True,
            editable_slot_count=3,
            slot_count=4,
            slot_summary="K1 (title); K2 (body_text); K3 (section_label)",
            structural_fingerprint="fp-001",
        )
    ]
    prompt = build_structural_selection_prompt(brief, [], candidates, "slide-x")
    assert "section_label" in prompt or "slot_summary" in prompt or "K3" in prompt


def test_prompt_is_string():
    brief = make_brief()
    prompt = build_structural_selection_prompt(brief, [], _make_candidates(), "slide-x")
    assert isinstance(prompt, str)
    assert len(prompt) > 200


def test_prompt_selection_criteria_section():
    brief = make_brief()
    prompt = build_structural_selection_prompt(brief, [], _make_candidates(), "slide-x")
    assert "CRITERIA" in prompt or "selection" in prompt.lower()
