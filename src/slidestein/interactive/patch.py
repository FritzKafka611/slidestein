"""SlidePatchService — validates protected fields and delegates to the adapter."""

from __future__ import annotations

from pathlib import Path

from slidestein.interactive.adapter import PowerPointHostAdapter
from slidestein.interactive.models import (
    PatchExecutionResult,
    SlideSession,
    SlidePatchPlan,
)


def validate_session_identity(session: SlideSession) -> bool:
    """Check that all slide identity fields within a session are internally consistent.

    Rules:
      A. current_state.slide_number == last_slidestein_state.slide_number
      B. Any non-None deck_id in current_state / last_slidestein_state must equal
         session.deck_id (if session.deck_id is set), and must equal each other.
      C. Same None-aware rule for slide_id.

    Returns True if fully consistent, False on any inconsistency.
    """
    cs = session.current_state
    ls = session.last_slidestein_state

    # A: slide_number
    if cs.slide_number != ls.slide_number:
        return False

    # B: deck_id
    if session.deck_id is not None:
        if cs.deck_id is not None and cs.deck_id != session.deck_id:
            return False
        if ls.deck_id is not None and ls.deck_id != session.deck_id:
            return False
    if cs.deck_id is not None and ls.deck_id is not None and cs.deck_id != ls.deck_id:
        return False

    # C: slide_id
    if session.slide_id is not None:
        if cs.slide_id is not None and cs.slide_id != session.slide_id:
            return False
        if ls.slide_id is not None and ls.slide_id != session.slide_id:
            return False
    if cs.slide_id is not None and ls.slide_id is not None and cs.slide_id != ls.slide_id:
        return False

    return True


class SlidePatchService:
    """Validates slide identity and protected-field constraints, then delegates to the adapter.

    Session state updates (version increment, protected field accumulation) are
    the CALLER's responsibility via SlideSessionService — this service only enforces
    constraints and delegates.
    """

    def validate_and_apply(
        self,
        session: SlideSession,
        patch: SlidePatchPlan,
        adapter: PowerPointHostAdapter,
        pptx_path: Path,
    ) -> PatchExecutionResult:
        # ── Internal session identity consistency check ────────────────────
        if not validate_session_identity(session):
            return PatchExecutionResult(
                status="rejected",
                rejection_reason="slide_identity_mismatch",
                base_state_hash=patch.base_state_hash,
                observed_pre_state_hash=session.current_state.state_hash,
                before_state=session.current_state,
            )

        # ── Slide identity guard: patch vs session ─────────────────────────
        if patch.slide_number != session.current_state.slide_number:
            return PatchExecutionResult(
                status="rejected",
                rejection_reason="slide_identity_mismatch",
                base_state_hash=patch.base_state_hash,
                observed_pre_state_hash=session.current_state.state_hash,
                before_state=session.current_state,
            )

        if (
            patch.deck_id is not None
            and session.deck_id is not None
            and patch.deck_id != session.deck_id
        ):
            return PatchExecutionResult(
                status="rejected",
                rejection_reason="slide_identity_mismatch",
                base_state_hash=patch.base_state_hash,
                observed_pre_state_hash=session.current_state.state_hash,
                before_state=session.current_state,
            )

        if (
            patch.slide_id is not None
            and session.slide_id is not None
            and patch.slide_id != session.slide_id
        ):
            return PatchExecutionResult(
                status="rejected",
                rejection_reason="slide_identity_mismatch",
                base_state_hash=patch.base_state_hash,
                observed_pre_state_hash=session.current_state.state_hash,
                before_state=session.current_state,
            )

        # ── Protected field check ──────────────────────────────────────────
        for op in patch.operations:
            field_key = f"{op.shape_path}.{op.field}"
            if (
                field_key in session.protected_fields
                and field_key not in patch.explicitly_authorized_fields
            ):
                return PatchExecutionResult(
                    status="rejected",
                    rejection_reason="protected_user_edit",
                    base_state_hash=patch.base_state_hash,
                    observed_pre_state_hash=session.current_state.state_hash,
                    before_state=session.current_state,
                )

        return adapter.apply_patch(pptx_path, patch)
