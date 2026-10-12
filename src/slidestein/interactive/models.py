"""Domain models for M11 Interactive PowerPoint Round-Trip."""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from slidestein.interactive.versions import (
    INTERACTIVE_PATCH_POLICY_VERSION,
    INTERACTIVE_STATE_SCHEMA_VERSION,
)


class ShapeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = INTERACTIVE_STATE_SCHEMA_VERSION
    shape_id: int
    shape_path: str
    name: str
    shape_type: str
    parent_group_path: Optional[str] = None
    text: Optional[str] = None
    x: int
    y: int
    width: int
    height: int
    rotation: Optional[float] = None
    z_order: Optional[int] = None
    editable_text: bool = False
    formatting_fingerprint: Optional[str] = None


class SlideState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = INTERACTIVE_STATE_SCHEMA_VERSION
    deck_id: Optional[str] = None
    slide_id: Optional[str] = None
    slide_number: int
    slide_width: int
    slide_height: int
    shapes: list[ShapeState]
    state_hash: str
    captured_at: Optional[str] = None


class ShapeDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shape_path: str
    shape_id: int
    changed_fields: list[str]
    delta_categories: list[str]
    before: Optional[ShapeState] = None
    after: Optional[ShapeState] = None


class SlideStateDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = INTERACTIVE_STATE_SCHEMA_VERSION
    base_state_hash: str
    current_state_hash: str
    shape_deltas: list[ShapeDelta]
    added_shapes: list[ShapeState]
    deleted_shapes: list[ShapeState]
    has_changes: bool


class SlidePatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["replace_text", "clear_text"]
    shape_id: int
    shape_path: str
    field: Literal["text"]
    expected_before: Optional[str] = None
    value: Optional[str] = None

    @field_validator("shape_id")
    @classmethod
    def shape_id_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("shape_id must be a positive integer")
        return v

    @field_validator("shape_path")
    @classmethod
    def shape_path_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("shape_path must not be empty")
        return v

    @model_validator(mode="after")
    def validate_value_for_operation(self) -> "SlidePatchOperation":
        if self.operation == "replace_text" and self.value is None:
            raise ValueError("replace_text requires value to be set (not None)")
        if self.operation == "clear_text" and self.value is not None:
            raise ValueError("clear_text requires value=None")
        return self


class SlidePatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = INTERACTIVE_STATE_SCHEMA_VERSION
    policy_version: str = INTERACTIVE_PATCH_POLICY_VERSION
    deck_id: Optional[str] = None
    slide_id: Optional[str] = None
    slide_number: int
    base_state_hash: str
    operations: list[SlidePatchOperation]
    explicitly_authorized_fields: list[str] = Field(default_factory=list)

    @field_validator("slide_number")
    @classmethod
    def slide_number_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("slide_number must be >= 1")
        return v

    @field_validator("base_state_hash")
    @classmethod
    def hash_format_valid(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", v):
            raise ValueError("base_state_hash must be exactly 64 hex characters")
        return v

    @field_validator("operations")
    @classmethod
    def operations_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("operations must contain at least 1 operation")
        return v

    @model_validator(mode="after")
    def no_duplicate_targets(self) -> "SlidePatchPlan":
        seen: set[str] = set()
        for op in self.operations:
            key = f"{op.shape_path}.{op.field}"
            if key in seen:
                raise ValueError(f"Duplicate target field key: {key!r}")
            seen.add(key)
        return self

    @model_validator(mode="after")
    def authorized_fields_correspond_to_ops(self) -> "SlidePatchPlan":
        targeted = {f"{op.shape_path}.{op.field}" for op in self.operations}
        seen: set[str] = set()
        for auth in self.explicitly_authorized_fields:
            if auth in seen:
                raise ValueError(
                    f"Duplicate entry in explicitly_authorized_fields: {auth!r}"
                )
            seen.add(auth)
            if auth not in targeted:
                raise ValueError(
                    f"explicitly_authorized_fields entry {auth!r} does not correspond "
                    f"to any operation target"
                )
        return self


_REJECTION_REASONS = Literal[
    "stale_base_state",
    "protected_user_edit",
    "missing_target_shape",
    "shape_identity_mismatch",
    "target_not_editable",
    "precondition_failed",
    "slide_identity_mismatch",
    "verification_failed",
]


class PatchExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "rejected"]
    rejection_reason: Optional[_REJECTION_REASONS] = None
    base_state_hash: str
    observed_pre_state_hash: str
    resulting_state_hash: Optional[str] = None
    applied_operations: list[SlidePatchOperation] = Field(default_factory=list)
    skipped_operations: list[SlidePatchOperation] = Field(default_factory=list)
    before_state: Optional[SlideState] = None
    after_state: Optional[SlideState] = None
    verification_passed: bool = False
    unexpected_changed_fields: list[str] = Field(default_factory=list)


class SlideSession(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    session_id: str
    deck_id: Optional[str] = None
    slide_id: Optional[str] = None
    version: int = 0
    last_slidestein_state: SlideState
    current_state: SlideState
    protected_fields: set[str] = Field(default_factory=set)
    last_patch: Optional[SlidePatchPlan] = None


class UserInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    modality: Literal["chat", "voice"] = "chat"
