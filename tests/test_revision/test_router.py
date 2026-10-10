"""Tests for the deterministic RevisionRouter v1.1 (0 API calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidestein.qa.models import VisualQAIssue
from slidestein.review.models import ManagerReviewIssue
from slidestein.revision.errors import RevisionError
from slidestein.revision.models import RevisionRoute
from slidestein.revision.router import RevisionRouter
from tests.test_revision.conftest import make_revision_request


def route(*, m7_issues=None, m8_issues=None, m7_rec="approve", m8_rec="pass",
          incomplete_draft=False, factual_flags=None):
    """Build a request and route it.  Raises RevisionError for contract violations."""
    from tests.test_revision.conftest import (
        make_brief,
        make_complete_draft,
        make_manager_review,
        make_slot_map,
        make_visual_qa,
    )
    from slidestein.drafting.models import SlotDraftAction
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    slot_map = make_slot_map()
    draft = make_complete_draft()

    if incomplete_draft:
        from slidestein.drafting.models import SlideContentDraft, SlotDraftAssignment
        from slidestein.slots.roles import SlotRole
        draft = SlideContentDraft(
            slide_id="slide-test-001",
            deck_id="deck-abc123",
            slide_number=2,
            brief_key_message="Digital transformation drives efficiency.",
            assignments=[
                SlotDraftAssignment(
                    slot_id="slot-001", shape_id=21, shape_path="21",
                    slot_role=SlotRole.TITLE, semantic_label="Title",
                    action=SlotDraftAction.NEEDS_INPUT,
                    text=None,
                    missing_information="Need client name.",
                    capacity_characters=100,
                    capacity_utilization=0.0,
                    max_lines_estimate=2,
                )
            ],
            drafting_summary="Incomplete.",
            is_complete=False,
        )

    mr = make_manager_review(
        recommendation=m7_rec,
        issues=m7_issues or [],
        factual_flags=factual_flags or [],
    )
    vq = make_visual_qa(recommendation=m8_rec, issues=m8_issues or [])
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    router = RevisionRouter()
    return router.route(req)


# ---------------------------------------------------------------------------
# Step 0 — Contract errors raise RevisionError (not manual_review)
# ---------------------------------------------------------------------------


def test_route_incomplete_draft_raises_revision_error():
    with pytest.raises(RevisionError, match="is_complete"):
        route(incomplete_draft=True)


def test_route_needs_input_assignment_raises_revision_error():
    """NEEDS_INPUT assignment even when is_complete=True must raise RevisionError.

    Uses model_construct to bypass SlideContentDraft's own is_complete validator,
    testing the router's independent defensive check.
    """
    from tests.test_revision.conftest import make_brief, make_slot_map, make_manager_review, make_visual_qa
    from slidestein.drafting.models import SlideContentDraft, SlotDraftAction, SlotDraftAssignment
    from slidestein.drafting.versions import CONTENT_DRAFT_SCHEMA_VERSION
    from slidestein.slots.roles import SlotRole
    from slidestein.revision.models import RevisionRequest

    ni_assignment = SlotDraftAssignment(
        slot_id="slot-001", shape_id=21, shape_path="21",
        slot_role=SlotRole.TITLE, semantic_label="Title",
        action=SlotDraftAction.NEEDS_INPUT, text=None,
        missing_information="Needs input.",
        capacity_characters=100, capacity_utilization=0.0, max_lines_estimate=2,
    )
    ok_assignment = SlotDraftAssignment(
        slot_id="slot-002", shape_id=22, shape_path="22",
        slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
        action=SlotDraftAction.REPLACE, text="Body text.",
        capacity_characters=300, capacity_utilization=0.03, max_lines_estimate=6,
    )
    # Bypass SlideContentDraft's own validator to simulate a corrupted draft
    draft = SlideContentDraft.model_construct(
        schema_version=CONTENT_DRAFT_SCHEMA_VERSION,
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        brief_key_message="Digital transformation drives efficiency.",
        assignments=[ni_assignment, ok_assignment],
        open_questions=[],
        drafting_summary="Sneaky.",
        is_complete=True,
    )
    brief = make_brief()
    slot_map = make_slot_map()
    mr = make_manager_review()
    vq = make_visual_qa()
    # model_construct on both to bypass all validators end-to-end
    req = RevisionRequest.model_construct(
        brief=brief,
        draft=draft,
        slot_map=slot_map,
        manager_review=mr,
        visual_qa=vq,
        source_material=None,
        template_pptx=Path("t.pptx"),
        output_pptx=Path("o.pptx"),
        overwrite=False,
    )
    with pytest.raises(RevisionError, match="NEEDS_INPUT"):
        RevisionRouter().route(req)


def test_route_brief_key_message_mismatch_raises_revision_error():
    from tests.test_revision.conftest import make_complete_draft, make_manager_review, make_slot_map, make_visual_qa
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.domain.models import CommunicationJob, SlideFunction
    from slidestein.revision.models import RevisionRequest

    brief = ConsultingSlideBrief(
        original_request="Create a slide.",
        key_message="Completely different key message.",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SUMMARISE,
    )
    draft = make_complete_draft()  # has brief_key_message="Digital transformation drives efficiency."
    slot_map = make_slot_map()
    mr = make_manager_review()
    vq = make_visual_qa()
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="key_message"):
        RevisionRouter().route(req)


def test_route_slide_id_mismatch_m7_raises_revision_error():
    from tests.test_revision.conftest import (
        make_brief, make_complete_draft, make_manager_review,
        make_slot_map, make_visual_qa,
    )
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    draft = make_complete_draft(slide_id="slide-A")
    slot_map = make_slot_map(slide_id="slide-A")
    mr = make_manager_review(slide_id="slide-B")  # mismatch
    vq = make_visual_qa(slide_id="slide-A")
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="slide_id"):
        RevisionRouter().route(req)


def test_route_deck_id_mismatch_m7_raises_revision_error():
    from tests.test_revision.conftest import (
        make_brief, make_complete_draft, make_manager_review,
        make_slot_map, make_visual_qa,
    )
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    draft = make_complete_draft(deck_id="deck-A")
    slot_map = make_slot_map(deck_id="deck-A")
    mr = make_manager_review(deck_id="deck-B")  # mismatch
    vq = make_visual_qa(deck_id="deck-A")
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="deck_id"):
        RevisionRouter().route(req)


def test_route_slide_number_mismatch_m7_raises_revision_error():
    from tests.test_revision.conftest import (
        make_brief, make_complete_draft, make_manager_review,
        make_slot_map, make_visual_qa,
    )
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    draft = make_complete_draft(slide_number=2)
    slot_map = make_slot_map(slide_number=2)
    mr = make_manager_review(slide_number=5)  # mismatch
    vq = make_visual_qa(slide_number=2)
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="slide_number"):
        RevisionRouter().route(req)


def test_route_slide_id_mismatch_m8_raises_revision_error():
    from tests.test_revision.conftest import (
        make_brief, make_complete_draft, make_manager_review,
        make_slot_map, make_visual_qa,
    )
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    draft = make_complete_draft(slide_id="slide-A")
    slot_map = make_slot_map(slide_id="slide-A")
    mr = make_manager_review(slide_id="slide-A")
    vq = make_visual_qa(slide_id="slide-B")  # mismatch
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="slide_id"):
        RevisionRouter().route(req)


def test_route_deck_id_mismatch_m8_raises_revision_error():
    from tests.test_revision.conftest import (
        make_brief, make_complete_draft, make_manager_review,
        make_slot_map, make_visual_qa,
    )
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    draft = make_complete_draft(deck_id="deck-A")
    slot_map = make_slot_map(deck_id="deck-A")
    mr = make_manager_review(deck_id="deck-A")
    vq = make_visual_qa(deck_id="deck-B")  # mismatch
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="deck_id"):
        RevisionRouter().route(req)


def test_route_slide_number_mismatch_m8_raises_revision_error():
    from tests.test_revision.conftest import (
        make_brief, make_complete_draft, make_manager_review,
        make_slot_map, make_visual_qa,
    )
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    draft = make_complete_draft(slide_number=2)
    slot_map = make_slot_map(slide_number=2)
    mr = make_manager_review(slide_number=2)
    vq = make_visual_qa(slide_number=5)  # mismatch
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    with pytest.raises(RevisionError, match="slide_number"):
        RevisionRouter().route(req)


def test_route_unknown_key_in_m7_issue_raises_revision_error():
    issue = ManagerReviewIssue(
        severity="major", category="answer_first_title",
        slot_keys=["K99"], issue="Bad key.", recommendation="Fix."
    )
    with pytest.raises(RevisionError, match="unknown slot key"):
        route(m7_issues=[issue], m7_rec="revise")


def test_route_unknown_key_in_m8_issue_raises_revision_error():
    issue = VisualQAIssue(
        severity="major", category="text_fit_and_clipping",
        slot_keys=["K77"], issue="Bad key.", evidence="E.", recommendation="Fix."
    )
    with pytest.raises(RevisionError, match="unknown slot key"):
        route(m8_issues=[issue], m8_rec="revise")


def test_route_unknown_key_in_factual_flag_raises_revision_error():
    flag = ManagerReviewIssue(
        severity="major", category="factual_grounding",
        slot_keys=["K88"], issue="Unknown key in factual flag.", recommendation="Fix."
    )
    with pytest.raises(RevisionError, match="unknown slot key"):
        route(factual_flags=[flag], m7_rec="revise")


# ---------------------------------------------------------------------------
# Step 1 — Contradiction detection → manual_review
# ---------------------------------------------------------------------------


def test_route_contradictory_m8_pass_critical_visual_hierarchy_is_manual_review():
    issue = VisualQAIssue(
        severity="critical", category="visual_hierarchy",
        slot_keys=["K1"], issue="Hierarchy is broken.", evidence="E.",
        recommendation="Fix template."
    )
    plan = route(m8_issues=[issue], m8_rec="pass")
    assert plan.route == RevisionRoute.MANUAL_REVIEW
    assert any("contradict" in r.lower() or "visual_hierarchy" in r.lower()
               for r in plan.reasons)


def test_route_contradictory_m8_pass_critical_non_hierarchy_is_manual_review():
    """M8 pass + critical alignment issue (not visual_hierarchy) → contradiction."""
    issue = VisualQAIssue(
        severity="critical", category="alignment_and_spacing",
        slot_keys=["K1"], issue="Critical alignment broken.", evidence="E.",
        recommendation="Fix template."
    )
    plan = route(m8_issues=[issue], m8_rec="pass")
    assert plan.route == RevisionRoute.MANUAL_REVIEW
    assert any("contradict" in r.lower() for r in plan.reasons)


def test_route_contradictory_m7_approve_critical_issue_is_manual_review():
    """M7 approve + critical issue → contradiction."""
    issue = ManagerReviewIssue(
        severity="critical", category="answer_first_title",
        slot_keys=["K1"], issue="Critical issue despite approval.", recommendation="Fix."
    )
    plan = route(m7_issues=[issue], m7_rec="approve")
    assert plan.route == RevisionRoute.MANUAL_REVIEW
    assert any("contradict" in r.lower() for r in plan.reasons)


def test_route_contradictory_m7_approve_critical_factual_flag_is_manual_review():
    """M7 approve + critical factual flag → contradiction."""
    flag = ManagerReviewIssue(
        severity="critical", category="factual_grounding",
        slot_keys=["K1"], issue="Critical factual error despite approval.", recommendation="Fix."
    )
    plan = route(factual_flags=[flag], m7_rec="approve")
    assert plan.route == RevisionRoute.MANUAL_REVIEW
    assert any("contradict" in r.lower() for r in plan.reasons)


# ---------------------------------------------------------------------------
# Step 2 — Structural M8 issues → template_reselection (target_slot_keys=[])
# ---------------------------------------------------------------------------


def test_route_critical_visual_hierarchy_is_template_reselection():
    issue = VisualQAIssue(
        severity="critical", category="visual_hierarchy",
        slot_keys=["K1"], issue="K1 hierarchy broken.", evidence="Visual.",
        recommendation="Fix template."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert any("visual_hierarchy" in r for r in plan.reasons)
    assert plan.target_slot_keys == []


def test_route_major_alignment_and_spacing_is_template_reselection():
    issue = VisualQAIssue(
        severity="major", category="alignment_and_spacing",
        slot_keys=["K1"], issue="Misaligned.", evidence="Off.",
        recommendation="Reselect template."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


def test_route_major_balance_and_whitespace_is_template_reselection():
    issue = VisualQAIssue(
        severity="major", category="balance_and_whitespace",
        slot_keys=["K1"], issue="Crowded.", evidence="Dense.",
        recommendation="Reselect template."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


def test_route_major_typography_is_template_reselection():
    issue = VisualQAIssue(
        severity="major", category="typography_and_style_consistency",
        slot_keys=[], issue="Inconsistent fonts.", evidence="Visual.",
        recommendation="Use consistent template."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


def test_route_structural_m8_target_slot_keys_always_empty():
    """All structural M8 routes must produce target_slot_keys=[]."""
    issue = VisualQAIssue(
        severity="major", category="visual_hierarchy",
        slot_keys=[], issue="Global hierarchy issue.", evidence="E.",
        recommendation="Reselect template."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


def test_route_minor_structural_m8_does_not_trigger_reselection():
    """Minor issues are not material — fall through to finalize."""
    issue = VisualQAIssue(
        severity="minor", category="visual_hierarchy",
        slot_keys=["K1"], issue="Minor issue.", evidence="Slight.",
        recommendation="Minor fix."
    )
    plan = route(m8_issues=[issue], m8_rec="pass")
    assert plan.route == RevisionRoute.FINALIZE


# ---------------------------------------------------------------------------
# Step 3 — M7 content issues → content_revision
# ---------------------------------------------------------------------------


def test_route_critical_answer_first_title_is_content_revision():
    issue = ManagerReviewIssue(
        severity="critical", category="answer_first_title",
        slot_keys=["K1"], issue="Title is not answer-first.",
        recommendation="Rewrite title."
    )
    plan = route(m7_issues=[issue], m7_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert any("answer_first_title" in r for r in plan.reasons)
    assert "K1" in plan.target_slot_keys


def test_route_major_core_message_clarity_is_content_revision():
    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Message unclear.", recommendation="Clarify."
    )
    plan = route(m7_issues=[issue], m7_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION


def test_route_major_mece_structure_is_content_revision():
    issue = ManagerReviewIssue(
        severity="major", category="mece_structure",
        slot_keys=["K1", "K2"], issue="Overlap.", recommendation="Fix."
    )
    plan = route(m7_issues=[issue], m7_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert "K2" in plan.target_slot_keys


def test_route_answer_first_title_no_keys_targets_title_slots_only():
    """answer_first_title with no slot_keys → TITLE slot (K1) only, not body K2."""
    issue = ManagerReviewIssue(
        severity="major", category="answer_first_title",
        slot_keys=[], issue="Title not answer-first.", recommendation="Rewrite."
    )
    plan = route(m7_issues=[issue], m7_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    # K1 is TITLE, K2 is BODY_TEXT — only K1 should be targeted
    assert "K1" in plan.target_slot_keys
    assert "K2" not in plan.target_slot_keys


def test_route_m7_content_no_keys_targets_populated_replace_slots():
    """Non-answer_first_title content issue with no slot_keys → populated REPLACE slots."""
    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=[], issue="Whole slide is unclear.", recommendation="Revise all."
    )
    plan = route(m7_issues=[issue], m7_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert len(plan.target_slot_keys) >= 1


def test_route_factual_flags_drive_content_revision():
    """Material factual flags (major, factual_grounding) → content_revision."""
    factual_issue = ManagerReviewIssue(
        severity="major", category="factual_grounding",
        slot_keys=["K1"], issue="Claim X is unsupported by source material.",
        recommendation="Verify against source material."
    )
    plan = route(factual_flags=[factual_issue], m7_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert any("factual" in r.lower() for r in plan.reasons)


def test_route_minor_factual_flag_does_not_independently_route():
    """Minor factual flag alone does not trigger content_revision."""
    minor_flag = ManagerReviewIssue(
        severity="minor", category="factual_grounding",
        slot_keys=["K1"], issue="Minor factual note.", recommendation="Optional."
    )
    # M7=approve, M8=pass, only minor factual flag → finalize
    plan = route(factual_flags=[minor_flag], m7_rec="approve", m8_rec="pass")
    assert plan.route == RevisionRoute.FINALIZE


# ---------------------------------------------------------------------------
# Step 4 — Text-fit M8 on editable slot → content_revision
# ---------------------------------------------------------------------------


def test_route_major_text_fit_editable_is_content_revision():
    """K1 and K2 are REPLACE slots — text_fit major issue routes to content_revision."""
    issue = VisualQAIssue(
        severity="major", category="text_fit_and_clipping",
        slot_keys=["K1"], issue="Overflow.", evidence="Clipped.",
        recommendation="Shorten text."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert "K1" in plan.target_slot_keys
    assert any("text_fit_and_clipping" in r for r in plan.reasons)


def test_route_critical_text_fit_editable_is_content_revision():
    issue = VisualQAIssue(
        severity="critical", category="text_fit_and_clipping",
        slot_keys=["K2"], issue="Critical overflow.", evidence="Badly clipped.",
        recommendation="Significantly shorten."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION


def test_route_text_fit_empty_slot_keys_is_template_reselection():
    """text_fit issue with empty slot_keys → template_reselection."""
    issue = VisualQAIssue(
        severity="major", category="text_fit_and_clipping",
        slot_keys=[], issue="Text overflow but no REPLACE keys.", evidence="E.",
        recommendation="Consider template change."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


def test_route_text_fit_on_clear_slot_does_not_trigger_content_revision():
    """If the affected slot is CLEAR action, text_fit routes to template_reselection."""
    from tests.test_revision.conftest import (
        make_brief, make_slot_map, make_manager_review, make_visual_qa
    )
    from slidestein.drafting.models import SlideContentDraft, SlotDraftAction, SlotDraftAssignment
    from slidestein.slots.roles import SlotRole
    from slidestein.revision.models import RevisionRequest

    brief = make_brief()
    slot_map = make_slot_map()
    assignments = [
        SlotDraftAssignment(
            slot_id="slot-001", shape_id=21, shape_path="21",
            slot_role=SlotRole.TITLE, semantic_label="Title",
            action=SlotDraftAction.REPLACE, text="Title text.",
            capacity_characters=100, capacity_utilization=0.1, max_lines_estimate=2,
        ),
        SlotDraftAssignment(
            slot_id="slot-002", shape_id=22, shape_path="22",
            slot_role=SlotRole.BODY_TEXT, semantic_label="Body",
            action=SlotDraftAction.CLEAR, text=None,
            capacity_characters=300, capacity_utilization=0.0, max_lines_estimate=6,
        ),
    ]
    draft = SlideContentDraft(
        slide_id="slide-test-001", deck_id="deck-abc123",
        slide_number=2,
        brief_key_message="Digital transformation drives efficiency.",
        assignments=assignments, drafting_summary="Test.", is_complete=True,
    )
    mr = make_manager_review()
    issue = VisualQAIssue(
        severity="major", category="text_fit_and_clipping",
        slot_keys=["K2"], issue="Overflow on K2.", evidence="?",
        recommendation="Fix."
    )
    vq = make_visual_qa(recommendation="revise", issues=[issue])
    req = RevisionRequest(
        brief=brief, draft=draft, slot_map=slot_map,
        manager_review=mr, visual_qa=vq,
        template_pptx=Path("t.pptx"), output_pptx=Path("o.pptx"),
    )
    plan = RevisionRouter().route(req)
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


# ---------------------------------------------------------------------------
# Step 5 — Both approve/pass, no material issues → finalize
# ---------------------------------------------------------------------------


def test_route_both_approve_pass_is_finalize():
    plan = route(m7_rec="approve", m8_rec="pass")
    assert plan.route == RevisionRoute.FINALIZE
    assert any(
        "approved" in r.lower() or "passed" in r.lower() or "finalize" in r.lower()
        for r in plan.reasons
    )


def test_route_finalize_has_empty_target_slot_keys():
    plan = route()
    assert plan.route == RevisionRoute.FINALIZE
    assert plan.target_slot_keys == []


def test_route_finalize_has_requires_model_call_false():
    plan = route()
    assert plan.requires_model_call is False


# ---------------------------------------------------------------------------
# Step 6 — Semantic fallback
# ---------------------------------------------------------------------------


def test_route_m7_revise_no_material_issues_is_content_revision():
    """M7=revise, M8=pass, no categorised issues → content_revision fallback."""
    plan = route(m7_rec="revise", m8_rec="pass")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert any("fallback" in r.lower() for r in plan.reasons)


def test_route_m8_revise_no_structural_issues_is_template_reselection():
    """M7=approve, M8=revise, no categorised structural issues → template_reselection fallback."""
    plan = route(m7_rec="approve", m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert any("fallback" in r.lower() for r in plan.reasons)
    assert plan.target_slot_keys == []


def test_route_both_revise_no_material_issues_is_manual_review():
    """Both revise, no material issues → manual_review."""
    plan = route(m7_rec="revise", m8_rec="revise")
    assert plan.route == RevisionRoute.MANUAL_REVIEW
    assert plan.target_slot_keys == []


# ---------------------------------------------------------------------------
# target_slot_keys = [] for non-content-revision routes
# ---------------------------------------------------------------------------


def test_route_template_reselection_target_slot_keys_empty():
    issue = VisualQAIssue(
        severity="major", category="alignment_and_spacing",
        slot_keys=["K1"], issue="Misaligned.", evidence="Off.", recommendation="Fix."
    )
    plan = route(m8_issues=[issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION
    assert plan.target_slot_keys == []


def test_route_manual_review_target_slot_keys_empty():
    plan = route(m7_rec="revise", m8_rec="revise")
    assert plan.route == RevisionRoute.MANUAL_REVIEW
    assert plan.target_slot_keys == []


# ---------------------------------------------------------------------------
# Precedence rules
# ---------------------------------------------------------------------------


def test_structural_m8_beats_m7_content_issue():
    """Structural M8 issue takes precedence over M7 content issue."""
    m8_issue = VisualQAIssue(
        severity="major", category="visual_hierarchy",
        slot_keys=["K1"], issue="Hierarchy broken.", evidence="E.", recommendation="R."
    )
    m7_issue = ManagerReviewIssue(
        severity="critical", category="answer_first_title",
        slot_keys=["K1"], issue="No answer-first.", recommendation="Fix."
    )
    plan = route(m7_issues=[m7_issue], m7_rec="revise", m8_issues=[m8_issue], m8_rec="revise")
    assert plan.route == RevisionRoute.TEMPLATE_RESELECTION


def test_m7_content_beats_text_fit():
    """M7 content issue takes precedence over M8 text_fit issue."""
    m7_issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    m8_issue = VisualQAIssue(
        severity="major", category="text_fit_and_clipping",
        slot_keys=["K1"], issue="Overflow.", evidence="E.", recommendation="R."
    )
    plan = route(m7_issues=[m7_issue], m7_rec="revise", m8_issues=[m8_issue], m8_rec="revise")
    assert plan.route == RevisionRoute.CONTENT_REVISION
    assert any("core_message_clarity" in r for r in plan.reasons)


# ---------------------------------------------------------------------------
# Plan fields
# ---------------------------------------------------------------------------


def test_plan_contains_slide_identity():
    plan = route()
    assert plan.slide_id == "slide-test-001"
    assert plan.deck_id == "deck-abc123"
    assert plan.slide_number == 2


def test_plan_reasons_non_empty():
    plan = route()
    assert len(plan.reasons) >= 1
    assert all(isinstance(r, str) and r.strip() for r in plan.reasons)


def test_plan_content_revision_requires_model_call_true():
    issue = ManagerReviewIssue(
        severity="major", category="core_message_clarity",
        slot_keys=["K1"], issue="Unclear.", recommendation="Clarify."
    )
    plan = route(m7_issues=[issue], m7_rec="revise")
    assert plan.requires_model_call is True


def test_router_is_deterministic():
    """Same inputs always produce the same route."""
    req = make_revision_request()
    router = RevisionRouter()
    plan1 = router.route(req)
    plan2 = router.route(req)
    assert plan1.route == plan2.route
    assert plan1.reasons == plan2.reasons
