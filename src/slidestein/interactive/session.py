"""SlideSessionService — manages SlideSession lifecycle across human and SlideStein edits."""

from __future__ import annotations

import uuid
from typing import Optional

from slidestein.interactive.diff import SlideStateDiffService
from slidestein.interactive.models import (
    PatchExecutionResult,
    SlideSession,
    SlideState,
    SlideStateDiff,
    SlidePatchPlan,
)

_diff_service = SlideStateDiffService()


class SlideSessionService:
    """Tracks slide state, version, and protected-field accumulation for one session."""

    def create_session(
        self,
        deck_id: Optional[str],
        slide_id: Optional[str],
        initial_state: SlideState,
    ) -> SlideSession:
        """Create a fresh session. last_slidestein_state and current_state both point to initial_state."""
        if (
            deck_id is not None
            and initial_state.deck_id is not None
            and deck_id != initial_state.deck_id
        ):
            raise ValueError(
                f"create_session deck_id mismatch: argument {deck_id!r} != "
                f"initial_state.deck_id {initial_state.deck_id!r}"
            )
        if (
            slide_id is not None
            and initial_state.slide_id is not None
            and slide_id != initial_state.slide_id
        ):
            raise ValueError(
                f"create_session slide_id mismatch: argument {slide_id!r} != "
                f"initial_state.slide_id {initial_state.slide_id!r}"
            )
        return SlideSession(
            session_id=str(uuid.uuid4()),
            deck_id=deck_id,
            slide_id=slide_id,
            version=0,
            last_slidestein_state=initial_state,
            current_state=initial_state,
            protected_fields=set(),
        )

    def advance_after_human_edit(
        self,
        session: SlideSession,
        new_state: SlideState,
    ) -> tuple[SlideSession, SlideStateDiff]:
        """Update current_state; accumulate protected fields from changes vs last_slidestein_state.

        Version is NOT incremented — human edits do not advance the SlideStein version counter.
        Added shapes: all editable fields + ._presence protected.
        Deleted shapes: ._presence protected so SlideStein cannot recreate them.
        """
        if new_state.slide_number != session.current_state.slide_number:
            raise ValueError(
                f"advance_after_human_edit slide_number mismatch: "
                f"new_state.slide_number={new_state.slide_number} != "
                f"session.current_state.slide_number={session.current_state.slide_number}"
            )
        if (
            new_state.deck_id is not None
            and session.deck_id is not None
            and new_state.deck_id != session.deck_id
        ):
            raise ValueError(
                f"advance_after_human_edit deck_id mismatch: "
                f"new_state.deck_id={new_state.deck_id!r} != session.deck_id={session.deck_id!r}"
            )
        if (
            new_state.slide_id is not None
            and session.slide_id is not None
            and new_state.slide_id != session.slide_id
        ):
            raise ValueError(
                f"advance_after_human_edit slide_id mismatch: "
                f"new_state.slide_id={new_state.slide_id!r} != session.slide_id={session.slide_id!r}"
            )
        diff = _diff_service.diff(session.last_slidestein_state, new_state)

        new_protected = set(session.protected_fields)

        # Changed field protection
        for delta in diff.shape_deltas:
            for field in delta.changed_fields:
                new_protected.add(f"{delta.shape_path}.{field}")

        # Added shape protection — human-owned shapes (Req 11)
        for shape in diff.added_shapes:
            path = shape.shape_path
            new_protected.add(f"{path}._presence")
            if shape.editable_text:
                new_protected.add(f"{path}.text")
            new_protected.add(f"{path}.x")
            new_protected.add(f"{path}.y")
            new_protected.add(f"{path}.width")
            new_protected.add(f"{path}.height")
            new_protected.add(f"{path}.rotation")
            new_protected.add(f"{path}.formatting_fingerprint")

        # Deleted shape protection — mark absence as human-chosen (Req 12)
        for shape in diff.deleted_shapes:
            new_protected.add(f"{shape.shape_path}._presence")

        updated = session.model_copy(
            update={
                "current_state": new_state,
                "protected_fields": new_protected,
            }
        )
        return updated, diff

    def advance_after_slidestein_patch(
        self,
        session: SlideSession,
        patch: SlidePatchPlan,
        result: PatchExecutionResult,
    ) -> SlideSession:
        """After a successful SlideStein patch: version++, update both states, record last_patch.

        Requires result.status == 'applied' and result.verification_passed == True.
        Call only when the patch was fully committed and verified.
        """
        if result.status != "applied":
            raise ValueError(
                f"advance_after_slidestein_patch requires result.status == 'applied', "
                f"got {result.status!r}"
            )
        if not result.verification_passed:
            raise ValueError(
                "advance_after_slidestein_patch requires result.verification_passed == True"
            )
        after = result.after_state
        if after is None:
            raise ValueError("advance_after_slidestein_patch requires result.after_state to be set")

        # Identity guard: after_state must agree with session and patch
        if after.slide_number != session.current_state.slide_number:
            raise ValueError(
                f"advance_after_slidestein_patch slide_number mismatch: "
                f"after_state.slide_number={after.slide_number} != "
                f"session.current_state.slide_number={session.current_state.slide_number}"
            )
        if after.slide_number != patch.slide_number:
            raise ValueError(
                f"advance_after_slidestein_patch slide_number mismatch: "
                f"after_state.slide_number={after.slide_number} != "
                f"patch.slide_number={patch.slide_number}"
            )
        if (
            after.deck_id is not None
            and session.deck_id is not None
            and after.deck_id != session.deck_id
        ):
            raise ValueError(
                f"advance_after_slidestein_patch deck_id mismatch: "
                f"after_state.deck_id={after.deck_id!r} != session.deck_id={session.deck_id!r}"
            )
        if (
            after.deck_id is not None
            and patch.deck_id is not None
            and after.deck_id != patch.deck_id
        ):
            raise ValueError(
                f"advance_after_slidestein_patch deck_id mismatch: "
                f"after_state.deck_id={after.deck_id!r} != patch.deck_id={patch.deck_id!r}"
            )
        if (
            after.slide_id is not None
            and session.slide_id is not None
            and after.slide_id != session.slide_id
        ):
            raise ValueError(
                f"advance_after_slidestein_patch slide_id mismatch: "
                f"after_state.slide_id={after.slide_id!r} != session.slide_id={session.slide_id!r}"
            )
        if (
            after.slide_id is not None
            and patch.slide_id is not None
            and after.slide_id != patch.slide_id
        ):
            raise ValueError(
                f"advance_after_slidestein_patch slide_id mismatch: "
                f"after_state.slide_id={after.slide_id!r} != patch.slide_id={patch.slide_id!r}"
            )
        return session.model_copy(
            update={
                "version": session.version + 1,
                "last_slidestein_state": after,
                "current_state": after,
                "last_patch": patch,
            }
        )
