"""Unit tests for M11 domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slidestein.interactive.models import (
    PatchExecutionResult,
    ShapeState,
    SlideSession,
    SlideState,
    SlidePatchOperation,
    SlidePatchPlan,
    SlideStateDiff,
    UserInstruction,
)
from slidestein.interactive.versions import (
    INTERACTIVE_PATCH_POLICY_VERSION,
    INTERACTIVE_STATE_SCHEMA_VERSION,
)


def _make_shape(**kwargs) -> ShapeState:
    defaults = dict(
        shape_id=5,
        shape_path="5",
        name="MyShape",
        shape_type="text_box",
        text="Hello",
        x=1000,
        y=2000,
        width=5000,
        height=1000,
    )
    defaults.update(kwargs)
    return ShapeState(**defaults)


def _make_slide_state(shapes=None) -> SlideState:
    if shapes is None:
        shapes = [_make_shape()]
    return SlideState(
        slide_number=1,
        slide_width=9144000,
        slide_height=6858000,
        shapes=shapes,
        state_hash="a" * 64,
    )


def _make_op(**kwargs) -> SlidePatchOperation:
    defaults = dict(operation="replace_text", shape_id=5, shape_path="5", field="text", value="x")
    defaults.update(kwargs)
    return SlidePatchOperation(**defaults)


def test_shape_state_valid():
    s = _make_shape()
    assert s.shape_id == 5
    assert s.shape_path == "5"
    assert s.editable_text is False


def test_shape_state_extra_field_forbidden():
    with pytest.raises(ValidationError):
        ShapeState(
            shape_id=1,
            shape_path="1",
            name="x",
            shape_type="text_box",
            x=0,
            y=0,
            width=100,
            height=100,
            unknown_extra="boom",
        )


def test_shape_state_schema_version_default():
    s = _make_shape()
    assert s.schema_version == INTERACTIVE_STATE_SCHEMA_VERSION


def test_slide_state_roundtrip():
    state = _make_slide_state()
    json_str = state.model_dump_json()
    restored = SlideState.model_validate_json(json_str)
    assert restored.state_hash == state.state_hash
    assert len(restored.shapes) == 1


def test_slide_state_extra_forbidden():
    with pytest.raises(ValidationError):
        SlideState(
            slide_number=1,
            slide_width=9144000,
            slide_height=6858000,
            shapes=[],
            state_hash="a" * 64,
            extra_oops="bad",
        )


def test_patch_operation_valid_operations():
    op = SlidePatchOperation(
        operation="replace_text",
        shape_id=5,
        shape_path="5",
        field="text",
        value="new",
    )
    assert op.operation == "replace_text"


def test_patch_operation_invalid_operation():
    with pytest.raises(ValidationError):
        SlidePatchOperation(
            operation="delete_shape",  # invalid
            shape_id=5,
            shape_path="5",
            field="text",
        )


def test_patch_operation_replace_text_requires_value():
    with pytest.raises(ValidationError, match="replace_text requires value"):
        SlidePatchOperation(
            operation="replace_text",
            shape_id=5,
            shape_path="5",
            field="text",
            value=None,
        )


def test_patch_operation_clear_text_requires_none_value():
    with pytest.raises(ValidationError, match="clear_text requires value=None"):
        SlidePatchOperation(
            operation="clear_text",
            shape_id=5,
            shape_path="5",
            field="text",
            value="non-empty",
        )


def test_patch_operation_clear_text_accepts_no_value():
    op = SlidePatchOperation(
        operation="clear_text", shape_id=5, shape_path="5", field="text"
    )
    assert op.value is None


def test_patch_operation_shape_id_must_be_positive():
    with pytest.raises(ValidationError, match="positive"):
        SlidePatchOperation(
            operation="replace_text", shape_id=0, shape_path="5", field="text", value="x"
        )


def test_patch_operation_shape_path_nonempty():
    with pytest.raises(ValidationError, match="empty"):
        SlidePatchOperation(
            operation="replace_text", shape_id=5, shape_path="", field="text", value="x"
        )


def test_patch_plan_operations_not_empty():
    with pytest.raises(ValidationError, match="at least 1"):
        SlidePatchPlan(
            slide_number=1,
            base_state_hash="b" * 64,
            operations=[],
        )


def test_patch_plan_slide_number_must_be_positive():
    with pytest.raises(ValidationError, match=">="):
        SlidePatchPlan(
            slide_number=0,
            base_state_hash="b" * 64,
            operations=[_make_op()],
        )


def test_patch_plan_hash_must_be_64_hex():
    with pytest.raises(ValidationError, match="64 hex"):
        SlidePatchPlan(
            slide_number=1,
            base_state_hash="tooshort",
            operations=[_make_op()],
        )


def test_patch_plan_no_duplicate_targets():
    with pytest.raises(ValidationError, match="Duplicate target"):
        SlidePatchPlan(
            slide_number=1,
            base_state_hash="b" * 64,
            operations=[_make_op(), _make_op()],
        )


def test_patch_plan_authorized_fields_must_correspond_to_ops():
    with pytest.raises(ValidationError, match="does not correspond"):
        SlidePatchPlan(
            slide_number=1,
            base_state_hash="b" * 64,
            operations=[_make_op()],
            explicitly_authorized_fields=["99.text"],  # no op targets "99.text"
        )


def test_patch_plan_authorized_fields_duplicate_rejected():
    with pytest.raises(ValidationError, match="Duplicate entry"):
        SlidePatchPlan(
            slide_number=1,
            base_state_hash="b" * 64,
            operations=[_make_op()],
            explicitly_authorized_fields=["5.text", "5.text"],  # duplicate
        )


def test_patch_plan_authorized_fields_default_empty():
    plan = SlidePatchPlan(
        slide_number=1,
        base_state_hash="b" * 64,
        operations=[_make_op()],
    )
    assert plan.explicitly_authorized_fields == []
    assert plan.policy_version == INTERACTIVE_PATCH_POLICY_VERSION


def test_patch_execution_result_status_literal():
    with pytest.raises(ValidationError):
        PatchExecutionResult(
            status="pending",  # invalid
            base_state_hash="b" * 64,
            observed_pre_state_hash="c" * 64,
        )


def test_patch_execution_result_valid():
    r = PatchExecutionResult(
        status="rejected",
        rejection_reason="stale_base_state",
        base_state_hash="b" * 64,
        observed_pre_state_hash="c" * 64,
    )
    assert r.verification_passed is False
    assert r.applied_operations == []


def test_patch_execution_result_rejection_reason_literal():
    with pytest.raises(ValidationError):
        PatchExecutionResult(
            status="rejected",
            rejection_reason="unknown_made_up_reason",
            base_state_hash="b" * 64,
            observed_pre_state_hash="c" * 64,
        )


def test_slide_session_protected_fields_default_empty():
    state = _make_slide_state()
    session = SlideSession(
        session_id="s1",
        version=0,
        last_slidestein_state=state,
        current_state=state,
    )
    assert session.protected_fields == set()
    assert session.version == 0


def test_slide_session_version_field():
    state = _make_slide_state()
    session = SlideSession(
        session_id="s1",
        version=3,
        last_slidestein_state=state,
        current_state=state,
    )
    assert session.version == 3


def test_user_instruction_default_modality():
    u = UserInstruction(text="Make the title bigger")
    assert u.modality == "chat"


def test_user_instruction_voice_modality():
    u = UserInstruction(text="Make the title bigger", modality="voice")
    assert u.modality == "voice"


def test_user_instruction_invalid_modality():
    with pytest.raises(ValidationError):
        UserInstruction(text="x", modality="telepathy")
