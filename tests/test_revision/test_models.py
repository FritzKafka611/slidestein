"""Tests for M9 revision domain models (v1.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.revision.models import (
    ContentRevisionModelOutput,
    ContentRevisionResult,
    RevisionChange,
    RevisionCycleResult,
    RevisionPlan,
    RevisionRequest,
    RevisionRoute,
)
from slidestein.revision.versions import (
    REVISION_POLICY_VERSION,
    REVISION_SCHEMA_VERSION,
)


def _make_plan(route=RevisionRoute.FINALIZE, reasons=None, **kw) -> RevisionPlan:
    defaults = dict(
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        route=route,
        reasons=reasons or ["All good."],
        requires_model_call=(route == RevisionRoute.CONTENT_REVISION),
    )
    defaults.update(kw)
    return RevisionPlan(**defaults)


def _make_cycle_result(plan=None, **kw) -> RevisionCycleResult:
    p = plan or _make_plan()
    defaults = dict(
        route=p.route,
        slide_id="slide-test-001",
        deck_id="deck-abc123",
        slide_number=2,
        plan=p,
        status="finalized",
        final_ready=True,
        model_calls={"revision": 0, "manager_review": 0, "visual_qa": 0},
    )
    defaults.update(kw)
    return RevisionCycleResult(**defaults)


# ---------------------------------------------------------------------------
# RevisionRoute
# ---------------------------------------------------------------------------


def test_revision_route_values():
    assert RevisionRoute.FINALIZE.value == "finalize"
    assert RevisionRoute.CONTENT_REVISION.value == "content_revision"
    assert RevisionRoute.TEMPLATE_RESELECTION.value == "template_reselection"
    assert RevisionRoute.MANUAL_REVIEW.value == "manual_review"


def test_revision_route_is_str_enum():
    assert RevisionRoute.FINALIZE == "finalize"
    assert RevisionRoute.CONTENT_REVISION == "content_revision"


# ---------------------------------------------------------------------------
# RevisionPlan
# ---------------------------------------------------------------------------


def test_revision_plan_defaults():
    plan = _make_plan()
    assert plan.schema_version == REVISION_SCHEMA_VERSION
    assert plan.policy_version == REVISION_POLICY_VERSION
    assert plan.target_slot_keys == []
    assert plan.manager_issue_indexes == []
    assert plan.visual_issue_indexes == []
    assert plan.factual_flag_indexes == []
    assert plan.max_revision_cycles == 1


def test_revision_plan_extra_forbidden():
    with pytest.raises(ValidationError):
        RevisionPlan(
            slide_id="s", deck_id="d", slide_number=1,
            route=RevisionRoute.FINALIZE, reasons=["x"],
            requires_model_call=False, unknown_field="y",
        )


def test_revision_plan_empty_reasons_rejected():
    with pytest.raises(ValidationError, match="reasons"):
        RevisionPlan(
            slide_id="s", deck_id="d", slide_number=1,
            route=RevisionRoute.FINALIZE, reasons=[],
            requires_model_call=False,
        )


def test_revision_plan_with_target_keys():
    plan = _make_plan(
        route=RevisionRoute.CONTENT_REVISION,
        reasons=["K3 overflows."],
        target_slot_keys=["K3"],
        requires_model_call=True,
    )
    assert plan.target_slot_keys == ["K3"]


def test_revision_plan_slide_identity():
    plan = RevisionPlan(
        slide_id="slide-xyz", deck_id="deck-123", slide_number=6,
        route=RevisionRoute.FINALIZE,
        reasons=["Done."],
        requires_model_call=False,
    )
    assert plan.slide_id == "slide-xyz"
    assert plan.deck_id == "deck-123"
    assert plan.slide_number == 6


def test_revision_plan_requires_model_call_true_for_content_revision():
    plan = _make_plan(route=RevisionRoute.CONTENT_REVISION, reasons=["Needs revision."])
    assert plan.requires_model_call is True


def test_revision_plan_requires_model_call_false_for_finalize():
    plan = _make_plan(route=RevisionRoute.FINALIZE)
    assert plan.requires_model_call is False


# ---------------------------------------------------------------------------
# RevisionChange — replace/clear invariants
# ---------------------------------------------------------------------------


def test_revision_change_valid_replace():
    change = RevisionChange(key="K3", action="replace", text="Shorter revised text.")
    assert change.key == "K3"
    assert change.action == "replace"
    assert change.text == "Shorter revised text."


def test_revision_change_valid_clear():
    change = RevisionChange(key="K3", action="clear", text=None)
    assert change.key == "K3"
    assert change.action == "clear"
    assert change.text is None


def test_revision_change_blank_key_rejected():
    with pytest.raises(ValidationError, match="key"):
        RevisionChange(key="   ", action="replace", text="Something.")


def test_revision_change_replace_with_none_rejected():
    with pytest.raises(ValidationError):
        RevisionChange(key="K3", action="replace", text=None)


def test_revision_change_replace_with_blank_rejected():
    with pytest.raises(ValidationError):
        RevisionChange(key="K3", action="replace", text="   ")


def test_revision_change_clear_with_text_rejected():
    with pytest.raises(ValidationError):
        RevisionChange(key="K3", action="clear", text="Some text here.")


def test_revision_change_extra_forbidden():
    with pytest.raises(ValidationError):
        RevisionChange(key="K3", action="replace", text="Text.", extra_field="x")


# ---------------------------------------------------------------------------
# ContentRevisionModelOutput — strict status/changes/blocked invariants
# ---------------------------------------------------------------------------


def test_content_revision_output_valid_revised():
    output = ContentRevisionModelOutput(
        status="revised",
        changes=[RevisionChange(key="K3", action="replace", text="Revised.")],
        change_summary="Tightened K3 to fit capacity.",
    )
    assert output.status == "revised"
    assert len(output.changes) == 1
    assert output.changes[0].key == "K3"


def test_content_revision_output_valid_blocked():
    output = ContentRevisionModelOutput(
        status="blocked",
        changes=[],
        change_summary="Cannot shorten further.",
        blocked_reason="Text already at minimum viable length.",
    )
    assert output.status == "blocked"
    assert output.blocked_reason is not None


def test_content_revision_output_revised_zero_changes_rejected():
    """revised + zero changes is now invalid."""
    with pytest.raises(ValidationError, match="at least one change"):
        ContentRevisionModelOutput(
            status="revised",
            changes=[],
            change_summary="No changes needed.",
        )


def test_content_revision_output_revised_with_blocked_reason_rejected():
    with pytest.raises(ValidationError, match="blocked_reason"):
        ContentRevisionModelOutput(
            status="revised",
            changes=[RevisionChange(key="K1", action="replace", text="New.")],
            change_summary="Revised.",
            blocked_reason="Should not be set.",
        )


def test_content_revision_output_blocked_with_changes_rejected():
    with pytest.raises(ValidationError, match="changes"):
        ContentRevisionModelOutput(
            status="blocked",
            changes=[RevisionChange(key="K1", action="replace", text="New.")],
            change_summary="Blocked.",
            blocked_reason="Cannot revise.",
        )


def test_content_revision_output_blocked_without_reason_rejected():
    with pytest.raises(ValidationError, match="blocked_reason"):
        ContentRevisionModelOutput(
            status="blocked",
            changes=[],
            change_summary="Blocked.",
            blocked_reason=None,
        )


def test_content_revision_output_blocked_blank_reason_rejected():
    with pytest.raises(ValidationError):
        ContentRevisionModelOutput(
            status="blocked",
            changes=[],
            change_summary="Blocked.",
            blocked_reason="   ",
        )


def test_content_revision_output_blank_summary_rejected():
    with pytest.raises(ValidationError, match="change_summary"):
        ContentRevisionModelOutput(
            status="revised",
            changes=[RevisionChange(key="K1", action="replace", text="x.")],
            change_summary="",
        )


def test_content_revision_output_extra_forbidden():
    with pytest.raises(ValidationError):
        ContentRevisionModelOutput(
            status="revised",
            changes=[RevisionChange(key="K1", action="replace", text="x.")],
            change_summary="x",
            unknown_field="y",
        )


def test_content_revision_output_json_roundtrip():
    output = ContentRevisionModelOutput(
        status="revised",
        changes=[
            RevisionChange(key="K1", action="replace", text="New title."),
            RevisionChange(key="K3", action="replace", text="New body."),
        ],
        change_summary="Two slots revised.",
    )
    json_str = output.model_dump_json()
    parsed = ContentRevisionModelOutput.model_validate_json(json_str)
    assert len(parsed.changes) == 2
    assert parsed.changes[0].key == "K1"


# ---------------------------------------------------------------------------
# ContentRevisionResult — status/fields invariants
# ---------------------------------------------------------------------------


def test_content_revision_result_revised():
    from tests.test_revision.conftest import make_complete_draft

    result = ContentRevisionResult(
        status="revised",
        revised_draft=make_complete_draft(),
        applied_changes=[RevisionChange(key="K1", action="replace", text="New.")],
        change_summary="Tightened K1.",
    )
    assert result.status == "revised"
    assert result.revised_draft is not None
    assert len(result.applied_changes) == 1


def test_content_revision_result_revised_requires_revised_draft():
    with pytest.raises(ValidationError, match="revised_draft"):
        ContentRevisionResult(
            status="revised",
            revised_draft=None,
            change_summary="Revised.",
        )


def test_content_revision_result_revised_blocked_reason_must_be_none():
    from tests.test_revision.conftest import make_complete_draft

    with pytest.raises(ValidationError, match="blocked_reason"):
        ContentRevisionResult(
            status="revised",
            revised_draft=make_complete_draft(),
            change_summary="Revised.",
            blocked_reason="Should not be set.",
        )


def test_content_revision_result_blocked():
    result = ContentRevisionResult(
        status="blocked",
        revised_draft=None,
        change_summary="Cannot revise.",
        blocked_reason="Constraints prevent revision.",
    )
    assert result.status == "blocked"
    assert result.revised_draft is None
    assert result.blocked_reason is not None


def test_content_revision_result_blocked_requires_blocked_reason():
    with pytest.raises(ValidationError, match="blocked_reason"):
        ContentRevisionResult(
            status="blocked",
            revised_draft=None,
            change_summary="Blocked.",
            blocked_reason=None,
        )


def test_content_revision_result_blocked_draft_must_be_none():
    from tests.test_revision.conftest import make_complete_draft

    with pytest.raises(ValidationError, match="revised_draft"):
        ContentRevisionResult(
            status="blocked",
            revised_draft=make_complete_draft(),
            change_summary="Blocked.",
            blocked_reason="Cannot revise.",
        )


def test_content_revision_result_blocked_changes_must_be_empty():
    with pytest.raises(ValidationError, match="applied_changes"):
        ContentRevisionResult(
            status="blocked",
            revised_draft=None,
            applied_changes=[RevisionChange(key="K1", action="replace", text="x.")],
            change_summary="Blocked.",
            blocked_reason="Cannot revise.",
        )


# ---------------------------------------------------------------------------
# RevisionCycleResult
# ---------------------------------------------------------------------------


def test_revision_cycle_result_finalize(revision_request):
    result = _make_cycle_result()
    assert result.schema_version == REVISION_SCHEMA_VERSION
    assert result.route == RevisionRoute.FINALIZE
    assert result.status == "finalized"
    assert result.final_ready is True
    assert result.revised_draft is None
    assert result.output_pptx is None
    assert result.manager_review_after is None
    assert result.visual_qa_after is None
    assert result.writeback_result is None
    assert sum(result.model_calls.values()) == 0


def test_revision_cycle_result_model_calls_keys():
    result = _make_cycle_result()
    assert "revision" in result.model_calls
    assert "manager_review" in result.model_calls
    assert "visual_qa" in result.model_calls


def test_revision_cycle_result_extra_forbidden(revision_request):
    plan = _make_plan()
    with pytest.raises(ValidationError):
        RevisionCycleResult(
            route=RevisionRoute.FINALIZE,
            slide_id="slide-test-001",
            deck_id="deck-abc123",
            slide_number=2,
            plan=plan,
            status="finalized",
            model_calls={"revision": 0, "manager_review": 0, "visual_qa": 0},
            unexpected="x",
        )


# ---------------------------------------------------------------------------
# RevisionRequest
# ---------------------------------------------------------------------------


def test_revision_request_extra_forbidden(revision_request):
    with pytest.raises(ValidationError):
        from tests.test_revision.conftest import make_revision_request
        req = make_revision_request()
        d = req.model_dump()
        d["extra_field"] = "x"
        RevisionRequest.model_validate(d)


def test_revision_request_has_overwrite_default():
    from tests.test_revision.conftest import make_revision_request
    req = make_revision_request()
    assert req.overwrite is False
