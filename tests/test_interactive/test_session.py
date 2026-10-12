"""Unit tests for SlideSessionService."""

from __future__ import annotations

from slidestein.interactive.hashing import compute_slide_state_hash
from slidestein.interactive.models import (
    PatchExecutionResult,
    ShapeState,
    SlideState,
    SlidePatchOperation,
    SlidePatchPlan,
)
from slidestein.interactive.session import SlideSessionService
import pytest


def _make_shape(path="5", shape_id=5, text="Hello", x=1000, y=2000) -> ShapeState:
    return ShapeState(
        shape_id=shape_id, shape_path=path, name=f"S{path}",
        shape_type="text_box", text=text, x=x, y=y, width=5000, height=1000,
    )


def _make_state(shapes=None, slide_number=1) -> SlideState:
    if shapes is None:
        shapes = [_make_shape()]
    w, h = 9144000, 6858000
    return SlideState(
        slide_number=slide_number, slide_width=w, slide_height=h,
        shapes=shapes,
        state_hash=compute_slide_state_hash(shapes, w, h),
    )


def _make_patch(state: SlideState) -> SlidePatchPlan:
    op = SlidePatchOperation(
        operation="replace_text", shape_id=5, shape_path="5", field="text", value="B"
    )
    return SlidePatchPlan(
        slide_number=state.slide_number,
        base_state_hash=state.state_hash,
        operations=[op],
    )


_svc = SlideSessionService()


def test_create_session_version_zero():
    state = _make_state()
    session = _svc.create_session(None, None, state)
    assert session.version == 0


def test_create_session_both_states_equal():
    state = _make_state()
    session = _svc.create_session(None, None, state)
    assert session.last_slidestein_state.state_hash == state.state_hash
    assert session.current_state.state_hash == state.state_hash


def test_create_session_protected_fields_empty():
    state = _make_state()
    session = _svc.create_session(None, None, state)
    assert session.protected_fields == set()


def test_advance_after_human_edit_version_unchanged():
    initial = _make_state([_make_shape(text="A")])
    session = _svc.create_session(None, None, initial)
    new_state = _make_state([_make_shape(text="B")])
    updated, _ = _svc.advance_after_human_edit(session, new_state)
    assert updated.version == 0  # unchanged


def test_advance_after_human_edit_current_state_updated():
    initial = _make_state([_make_shape(text="A")])
    session = _svc.create_session(None, None, initial)
    new_state = _make_state([_make_shape(text="B")])
    updated, _ = _svc.advance_after_human_edit(session, new_state)
    assert updated.current_state.state_hash == new_state.state_hash


def test_advance_after_human_edit_protected_fields_populated():
    initial = _make_state([_make_shape(text="A", x=100)])
    session = _svc.create_session(None, None, initial)
    new_state = _make_state([_make_shape(text="B", x=100)])
    updated, _ = _svc.advance_after_human_edit(session, new_state)
    assert "5.text" in updated.protected_fields


def test_advance_after_human_edit_geometry_protected():
    initial = _make_state([_make_shape(x=1000)])
    session = _svc.create_session(None, None, initial)
    new_state = _make_state([_make_shape(x=2000)])
    updated, _ = _svc.advance_after_human_edit(session, new_state)
    assert "5.x" in updated.protected_fields


def test_two_consecutive_human_edits_accumulate():
    initial = _make_state([_make_shape(text="A", x=100)])
    session = _svc.create_session(None, None, initial)

    state2 = _make_state([_make_shape(text="B", x=100)])
    session2, _ = _svc.advance_after_human_edit(session, state2)

    state3 = _make_state([_make_shape(text="B", x=200)])
    session3, _ = _svc.advance_after_human_edit(session2, state3)

    assert "5.text" in session3.protected_fields
    assert "5.x" in session3.protected_fields


def test_advance_after_slidestein_patch_increments_version():
    initial = _make_state([_make_shape(text="A")])
    session = _svc.create_session(None, None, initial)

    after_state = _make_state([_make_shape(text="B")])
    patch = _make_patch(initial)
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after_state.state_hash,
        applied_operations=[patch.operations[0]],
        before_state=initial,
        after_state=after_state,
        verification_passed=True,
    )
    updated = _svc.advance_after_slidestein_patch(session, patch, result)
    assert updated.version == 1


def test_advance_after_slidestein_patch_updates_both_states():
    initial = _make_state([_make_shape(text="A")])
    session = _svc.create_session(None, None, initial)
    after_state = _make_state([_make_shape(text="B")])
    patch = _make_patch(initial)
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after_state.state_hash,
        applied_operations=[patch.operations[0]],
        before_state=initial,
        after_state=after_state,
        verification_passed=True,
    )
    updated = _svc.advance_after_slidestein_patch(session, patch, result)
    assert updated.last_slidestein_state.state_hash == after_state.state_hash
    assert updated.current_state.state_hash == after_state.state_hash


def test_advance_after_slidestein_patch_sets_last_patch():
    """last_patch must be the SlidePatchPlan, not a list of operations."""
    initial = _make_state([_make_shape(text="A")])
    session = _svc.create_session(None, None, initial)
    after_state = _make_state([_make_shape(text="B")])
    patch = _make_patch(initial)
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after_state.state_hash,
        applied_operations=[patch.operations[0]],
        before_state=initial,
        after_state=after_state,
        verification_passed=True,
    )
    updated = _svc.advance_after_slidestein_patch(session, patch, result)
    assert updated.last_patch is patch
    assert isinstance(updated.last_patch, SlidePatchPlan)


def test_advance_after_slidestein_patch_guards_rejected_status():
    """Rejected result must not advance session."""
    initial = _make_state()
    session = _svc.create_session(None, None, initial)
    patch = _make_patch(initial)
    result = PatchExecutionResult(
        status="rejected",
        rejection_reason="stale_base_state",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        before_state=initial,
    )
    with pytest.raises(ValueError, match="result.status"):
        _svc.advance_after_slidestein_patch(session, patch, result)


def test_advance_after_slidestein_patch_guards_unverified():
    """verification_passed=False must not advance session."""
    initial = _make_state()
    session = _svc.create_session(None, None, initial)
    patch = _make_patch(initial)
    after_state = _make_state([_make_shape(text="B")])
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after_state.state_hash,
        before_state=initial,
        after_state=after_state,
        verification_passed=False,
    )
    with pytest.raises(ValueError, match="verification_passed"):
        _svc.advance_after_slidestein_patch(session, patch, result)


def test_advance_after_human_edit_added_shape_protected():
    """Human-added shapes get ._presence and all editable fields protected."""
    initial = _make_state([_make_shape(path="5", shape_id=5)])
    session = _svc.create_session(None, None, initial)

    new_shape = _make_shape(path="99", shape_id=99, text="Added by human")
    new_shape_editable = ShapeState(
        shape_id=99, shape_path="99", name="S99", shape_type="text_box",
        text="Added by human", x=1000, y=2000, width=5000, height=1000,
        editable_text=True,
    )
    new_state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape(path="5", shape_id=5), new_shape_editable],
        state_hash=compute_slide_state_hash(
            [_make_shape(path="5", shape_id=5), new_shape_editable], 9144000, 6858000
        ),
    )
    updated, diff = _svc.advance_after_human_edit(session, new_state)

    assert len(diff.added_shapes) == 1
    assert "99._presence" in updated.protected_fields
    assert "99.text" in updated.protected_fields
    assert "99.x" in updated.protected_fields
    assert "99.y" in updated.protected_fields


def test_advance_after_human_edit_deleted_shape_presence_protected():
    """Human-deleted shapes get ._presence protected (cannot be recreated by SlideStein)."""
    initial = _make_state([_make_shape(path="5", shape_id=5), _make_shape(path="6", shape_id=6)])
    session = _svc.create_session(None, None, initial)

    # Delete shape "6"
    new_state = _make_state([_make_shape(path="5", shape_id=5)])
    updated, diff = _svc.advance_after_human_edit(session, new_state)

    assert len(diff.deleted_shapes) == 1
    assert "6._presence" in updated.protected_fields


# ---------------------------------------------------------------------------
# create_session identity guards
# ---------------------------------------------------------------------------

def test_create_session_deck_id_mismatch_raises():
    """deck_id arg and initial_state.deck_id both non-None but differ → ValueError."""
    state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()],
        state_hash=compute_slide_state_hash([_make_shape()], 9144000, 6858000),
        deck_id="deck-B",
    )
    with pytest.raises(ValueError, match="deck_id"):
        _svc.create_session("deck-A", None, state)


def test_create_session_slide_id_mismatch_raises():
    """slide_id arg and initial_state.slide_id both non-None but differ → ValueError."""
    state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()],
        state_hash=compute_slide_state_hash([_make_shape()], 9144000, 6858000),
        slide_id="slide-Z",
    )
    with pytest.raises(ValueError, match="slide_id"):
        _svc.create_session(None, "slide-A", state)


def test_create_session_deck_id_none_arg_passes():
    """None deck_id arg never conflicts."""
    state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()],
        state_hash=compute_slide_state_hash([_make_shape()], 9144000, 6858000),
        deck_id="deck-X",
    )
    session = _svc.create_session(None, None, state)
    assert session.deck_id is None


def test_create_session_matching_deck_id_passes():
    """Matching non-None deck_id does not raise."""
    state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()],
        state_hash=compute_slide_state_hash([_make_shape()], 9144000, 6858000),
        deck_id="deck-X",
    )
    session = _svc.create_session("deck-X", None, state)
    assert session.deck_id == "deck-X"


# ---------------------------------------------------------------------------
# advance_after_human_edit identity guards
# ---------------------------------------------------------------------------

def test_advance_after_human_edit_slide_number_mismatch_raises():
    """new_state.slide_number != session.current_state.slide_number → ValueError."""
    initial = _make_state(slide_number=1)
    session = _svc.create_session(None, None, initial)
    wrong_slide = _make_state(slide_number=2)
    with pytest.raises(ValueError, match="slide_number"):
        _svc.advance_after_human_edit(session, wrong_slide)


def test_advance_after_human_edit_deck_id_mismatch_raises():
    """Both non-None deck_ids differ → ValueError."""
    initial = _make_state()
    session = _svc.create_session(None, None, initial)
    session = session.model_copy(update={"deck_id": "deck-A"})
    new_state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape(text="B")],
        state_hash=compute_slide_state_hash([_make_shape(text="B")], 9144000, 6858000),
        deck_id="deck-B",
    )
    with pytest.raises(ValueError, match="deck_id"):
        _svc.advance_after_human_edit(session, new_state)


def test_advance_after_human_edit_slide_id_mismatch_raises():
    """Both non-None slide_ids differ → ValueError."""
    initial = _make_state()
    session = _svc.create_session(None, None, initial)
    session = session.model_copy(update={"slide_id": "slide-1"})
    new_state = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape(text="B")],
        state_hash=compute_slide_state_hash([_make_shape(text="B")], 9144000, 6858000),
        slide_id="slide-9",
    )
    with pytest.raises(ValueError, match="slide_id"):
        _svc.advance_after_human_edit(session, new_state)


def test_advance_after_human_edit_none_deck_id_passes():
    """None deck_id in new_state never conflicts."""
    initial = _make_state()
    session = _svc.create_session(None, None, initial)
    session = session.model_copy(update={"deck_id": "deck-A"})
    new_state = _make_state([_make_shape(text="B")])  # deck_id=None
    updated, _ = _svc.advance_after_human_edit(session, new_state)
    assert updated.current_state.state_hash == new_state.state_hash


# ---------------------------------------------------------------------------
# advance_after_slidestein_patch identity guards
# ---------------------------------------------------------------------------

def test_advance_after_slidestein_patch_after_state_slide_number_vs_session():
    """after_state.slide_number must match session.current_state.slide_number."""
    initial = _make_state(slide_number=1)
    session = _svc.create_session(None, None, initial)
    patch = _make_patch(initial)
    after = _make_state([_make_shape(text="B")], slide_number=2)
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after.state_hash,
        applied_operations=[patch.operations[0]],
        before_state=initial,
        after_state=after,
        verification_passed=True,
    )
    with pytest.raises(ValueError, match="slide_number"):
        _svc.advance_after_slidestein_patch(session, patch, result)


def test_advance_after_slidestein_patch_after_state_slide_number_vs_patch():
    """after_state.slide_number must match patch.slide_number."""
    initial = _make_state(slide_number=1)
    session = _svc.create_session(None, None, initial)
    # patch.slide_number=1 but after_state.slide_number=2
    patch = _make_patch(initial)
    after = _make_state([_make_shape(text="B")], slide_number=2)
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after.state_hash,
        applied_operations=[patch.operations[0]],
        before_state=initial,
        after_state=after,
        verification_passed=True,
    )
    with pytest.raises(ValueError, match="slide_number"):
        _svc.advance_after_slidestein_patch(session, patch, result)


def test_advance_after_slidestein_patch_after_state_deck_id_vs_session():
    """after_state.deck_id must match session.deck_id when both non-None."""
    initial = _make_state()
    session = _svc.create_session(None, None, initial)
    session = session.model_copy(update={"deck_id": "deck-A"})
    patch = _make_patch(initial)
    after = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape(text="B")],
        state_hash=compute_slide_state_hash([_make_shape(text="B")], 9144000, 6858000),
        deck_id="deck-B",
    )
    result = PatchExecutionResult(
        status="applied",
        base_state_hash=initial.state_hash,
        observed_pre_state_hash=initial.state_hash,
        resulting_state_hash=after.state_hash,
        applied_operations=[patch.operations[0]],
        before_state=initial,
        after_state=after,
        verification_passed=True,
    )
    with pytest.raises(ValueError, match="deck_id"):
        _svc.advance_after_slidestein_patch(session, patch, result)
