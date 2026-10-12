"""Tests for SlidePatchService protected-field validation and slide identity guard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from slidestein.interactive.hashing import compute_slide_state_hash
from slidestein.interactive.models import (
    PatchExecutionResult,
    ShapeState,
    SlideSession,
    SlideState,
    SlidePatchOperation,
    SlidePatchPlan,
)
from slidestein.interactive.patch import SlidePatchService, validate_session_identity
from slidestein.interactive.session import SlideSessionService


def _make_shape(path="5", shape_id=5, text="Hello") -> ShapeState:
    return ShapeState(
        shape_id=shape_id, shape_path=path, name=f"S{path}",
        shape_type="text_box", text=text, x=1000, y=2000, width=5000, height=1000,
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


def _make_session(protected: set | None = None, slide_number: int = 1) -> SlideSession:
    state = _make_state(slide_number=slide_number)
    s = SlideSessionService().create_session(None, None, state)
    if protected:
        s = s.model_copy(update={"protected_fields": protected})
    return s


def _make_patch(shape_path="5", field="text", value="new", authorized=None,
                slide_number=1) -> SlidePatchPlan:
    op = SlidePatchOperation(
        operation="replace_text", shape_id=5, shape_path=shape_path, field=field, value=value
    )
    return SlidePatchPlan(
        slide_number=slide_number,
        base_state_hash=_make_state().state_hash,
        operations=[op],
        explicitly_authorized_fields=authorized or [],
    )


def _mock_adapter_success(before_state: SlideState | None = None) -> MagicMock:
    adapter = MagicMock()
    bs = before_state or _make_state()
    after = _make_state([_make_shape(text="new")])
    adapter.apply_patch.return_value = PatchExecutionResult(
        status="applied",
        base_state_hash=bs.state_hash,
        observed_pre_state_hash=bs.state_hash,
        resulting_state_hash=after.state_hash,
        before_state=bs,
        after_state=after,
        verification_passed=True,
    )
    return adapter


_svc = SlidePatchService()


def test_unprotected_field_delegates_to_adapter(tmp_path):
    session = _make_session(protected=set())
    patch = _make_patch()
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)

    adapter.apply_patch.assert_called_once()
    assert result.status == "applied"


def test_protected_field_no_authorization_rejected(tmp_path):
    session = _make_session(protected={"5.text"})
    patch = _make_patch(shape_path="5", field="text", authorized=[])
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)

    adapter.apply_patch.assert_not_called()
    assert result.status == "rejected"
    assert result.rejection_reason == "protected_user_edit"


def test_protected_field_with_authorization_passes(tmp_path):
    session = _make_session(protected={"5.text"})
    patch = _make_patch(shape_path="5", field="text", authorized=["5.text"])
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)

    adapter.apply_patch.assert_called_once()
    assert result.status == "applied"


def test_multiple_ops_one_protected_rejects_all(tmp_path):
    session = _make_session(protected={"5.text"})
    ops = [
        SlidePatchOperation(operation="replace_text", shape_id=5, shape_path="5", field="text", value="x"),
        SlidePatchOperation(operation="replace_text", shape_id=6, shape_path="6", field="text", value="y"),
    ]
    state = _make_state()
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=ops,
        explicitly_authorized_fields=[],
    )
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)

    adapter.apply_patch.assert_not_called()
    assert result.status == "rejected"


def test_adapter_called_exactly_once(tmp_path):
    session = _make_session(protected=set())
    patch = _make_patch()
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    _svc.validate_and_apply(session, patch, adapter, pptx_path)

    assert adapter.apply_patch.call_count == 1


def test_adapter_result_returned_unchanged(tmp_path):
    session = _make_session(protected=set())
    patch = _make_patch()
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)
    expected = adapter.apply_patch.return_value

    assert result is expected


def test_protected_field_format_shape_path_dot_field(tmp_path):
    """Protected fields use 'shape_path.field' format e.g. '10.text'."""
    session = _make_session(protected={"10.text"})
    op = SlidePatchOperation(
        operation="replace_text", shape_id=10, shape_path="10", field="text", value="x"
    )
    state = _make_state()
    patch = SlidePatchPlan(
        slide_number=1, base_state_hash=state.state_hash, operations=[op]
    )
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)
    assert result.status == "rejected"
    assert result.rejection_reason == "protected_user_edit"


def test_protected_field_rejection_includes_before_state(tmp_path):
    """Service-layer rejection must include before_state for evidence."""
    session = _make_session(protected={"5.text"})
    patch = _make_patch(shape_path="5", field="text", authorized=[])
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)
    assert result.before_state is not None
    assert result.before_state.state_hash == session.current_state.state_hash


def test_slide_identity_mismatch_rejected(tmp_path):
    """Patch targeting a different slide number must be rejected before adapter call."""
    session = _make_session(slide_number=1)
    patch = _make_patch(slide_number=2)
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)

    adapter.apply_patch.assert_not_called()
    assert result.status == "rejected"
    assert result.rejection_reason == "slide_identity_mismatch"


def test_slide_identity_rejection_includes_before_state(tmp_path):
    """slide_identity_mismatch rejection must include before_state."""
    session = _make_session(slide_number=1)
    patch = _make_patch(slide_number=2)
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)
    assert result.before_state is not None
    assert result.before_state.state_hash == session.current_state.state_hash


def test_slide_identity_match_passes_through(tmp_path):
    """Matching slide number allows the patch to delegate normally."""
    session = _make_session(slide_number=1)
    patch = _make_patch(slide_number=1)
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)
    adapter.apply_patch.assert_called_once()
    assert result.status == "applied"


def test_deck_id_mismatch_rejected(tmp_path):
    """Deck ID mismatch must be rejected as slide_identity_mismatch."""
    state = _make_state()
    session = SlideSessionService().create_session(None, None, state)
    session = session.model_copy(update={"deck_id": "deck-A"})

    op = SlidePatchOperation(
        operation="replace_text", shape_id=5, shape_path="5", field="text", value="x"
    )
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[op],
        deck_id="deck-B",
    )
    adapter = _mock_adapter_success()
    pptx_path = tmp_path / "dummy.pptx"

    result = _svc.validate_and_apply(session, patch, adapter, pptx_path)
    assert result.status == "rejected"
    assert result.rejection_reason == "slide_identity_mismatch"
    adapter.apply_patch.assert_not_called()


# ---------------------------------------------------------------------------
# validate_session_identity helper tests
# ---------------------------------------------------------------------------

def test_validate_session_identity_consistent():
    """Consistent session (same slide_number, matching ids) returns True."""
    state = _make_state()
    session = SlideSessionService().create_session(None, None, state)
    assert validate_session_identity(session) is True


def test_validate_session_identity_slide_number_mismatch():
    """current_state vs last_slidestein_state slide_number differ → False."""
    state1 = _make_state(slide_number=1)
    state2 = _make_state(slide_number=2)
    session = SlideSessionService().create_session(None, None, state1)
    session = session.model_copy(update={"current_state": state2})
    assert validate_session_identity(session) is False


def test_validate_session_identity_deck_id_mismatch_in_current():
    """current_state.deck_id disagrees with session.deck_id → False."""
    state = _make_state()
    session = SlideSessionService().create_session(None, None, state)
    session = session.model_copy(update={"deck_id": "deck-A"})
    bad_current = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()],
        state_hash=_make_state().state_hash,
        deck_id="deck-Z",
    )
    session = session.model_copy(update={"current_state": bad_current})
    assert validate_session_identity(session) is False


def test_validate_session_identity_cs_ls_deck_id_differ():
    """current_state.deck_id and last_slidestein_state.deck_id both non-None but differ → False."""
    state = _make_state()
    session = SlideSessionService().create_session(None, None, state)
    cs = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()], state_hash=_make_state().state_hash,
        deck_id="deck-A",
    )
    ls = SlideState(
        slide_number=1, slide_width=9144000, slide_height=6858000,
        shapes=[_make_shape()], state_hash=_make_state().state_hash,
        deck_id="deck-B",
    )
    session = session.model_copy(update={"current_state": cs, "last_slidestein_state": ls})
    assert validate_session_identity(session) is False


def test_validate_session_identity_rejected_triggers_slide_identity_mismatch(tmp_path):
    """If validate_session_identity returns False, validate_and_apply rejects with slide_identity_mismatch."""
    state = _make_state(slide_number=1)
    state2 = _make_state(slide_number=2)
    session = SlideSessionService().create_session(None, None, state)
    # Corrupt session: current_state has slide_number=2 but last_slidestein_state has slide_number=1
    session = session.model_copy(update={"current_state": state2})

    # patch with slide_number=2 (matches current_state, but validate_session_identity fails first)
    op = SlidePatchOperation(
        operation="replace_text", shape_id=5, shape_path="5", field="text", value="x"
    )
    patch = SlidePatchPlan(
        slide_number=2,
        base_state_hash=state2.state_hash,
        operations=[op],
    )
    adapter = _mock_adapter_success()

    result = _svc.validate_and_apply(session, patch, adapter, tmp_path / "d.pptx")
    assert result.status == "rejected"
    assert result.rejection_reason == "slide_identity_mismatch"
    adapter.apply_patch.assert_not_called()
