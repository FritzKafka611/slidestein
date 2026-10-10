"""ManagerReviewService — orchestrates K-key mapping + reviewer + validation (v1.1).

Flow:
  1.  Validate draft completeness (is_complete must be True).
  1b. Validate draft.brief_key_message == brief.key_message (exact equality).
  1c. Defensive NEEDS_INPUT gate (no assignment.action == needs_input).
  2.  Build deterministic K1..Kn slot key mapping.
  3.  Validate draft ↔ slot-map identity (slide_id, deck_id, slide_number,
      slot-by-slot shape_id / shape_path / slot_role).
  4.  Build slot_review_specs (capacity data + group context; no fallback).
  5.  Build group_descriptions from slot_map.groups (with group member validation).
  6.  Invoke reviewer once (text-only, no images, no retry).
  7.  Validate slot key references in issues against K mapping.
  8.  Validate slot key references in factual_flags against K mapping.
  9.  Compute average_score arithmetically.
  10. Build and return ManagerReviewResult (with slide identity).
"""

from __future__ import annotations

from slidestein.drafting.models import SlotDraftAction
from slidestein.drafting.validation import validate_draft_slot_map_identity
from slidestein.review.errors import ManagerReviewError
from slidestein.review.models import (
    ManagerReviewRequest,
    ManagerReviewResult,
)
from slidestein.review.reviewer import ManagerReviewer


class ManagerReviewService:
    def __init__(self, reviewer: ManagerReviewer) -> None:
        self._reviewer = reviewer

    def review(self, request: ManagerReviewRequest) -> ManagerReviewResult:
        # ------------------------------------------------------------------
        # Step 1 — Validate completeness
        # ------------------------------------------------------------------
        if not request.draft.is_complete:
            raise ManagerReviewError(
                "Draft is not complete (is_complete=False). "
                "Manager review requires a fully complete draft with no "
                "NEEDS_INPUT assignments."
            )

        # ------------------------------------------------------------------
        # Step 1b — Validate draft ↔ brief key-message identity
        # ------------------------------------------------------------------
        if request.draft.brief_key_message != request.brief.key_message:
            raise ManagerReviewError(
                f"draft.brief_key_message does not match brief.key_message. "
                f"Draft was authored for a different brief. "
                f"draft={request.draft.brief_key_message!r}, "
                f"brief={request.brief.key_message!r}"
            )

        # ------------------------------------------------------------------
        # Step 1c — Defensive NEEDS_INPUT gate
        # ------------------------------------------------------------------
        # The domain model invariant (is_complete=True implies no NEEDS_INPUT)
        # is enforced by SlideContentDraft._is_complete_consistent_with_assignments.
        # This extra check defends against model_construct() bypass, future
        # regressions, or unsafe internal construction.
        for a in request.draft.assignments:
            if a.action == SlotDraftAction.NEEDS_INPUT:
                raise ManagerReviewError(
                    f"Draft assignment for slot_id {a.slot_id!r} has "
                    "action=needs_input. Manager review requires all "
                    "assignments to be replace or clear."
                )

        # ------------------------------------------------------------------
        # Step 2 — Build K1..Kn slot key mapping
        # ------------------------------------------------------------------
        from slidestein.drafting.service import build_slot_key_mapping  # noqa: PLC0415

        slot_key_map = build_slot_key_mapping(request.slot_map.slots)

        # ------------------------------------------------------------------
        # Step 3 — Validate draft ↔ slot-map identity
        # ------------------------------------------------------------------
        draft = request.draft
        slot_map = request.slot_map

        validate_draft_slot_map_identity(draft, slot_map, ManagerReviewError)

        # Build assignment lookup (used by steps 4+)
        assignments_by_slot_id: dict = {a.slot_id: a for a in draft.assignments}

        # ------------------------------------------------------------------
        # Step 4 — Build slot_review_specs (capacity data + group context)
        # ------------------------------------------------------------------
        slot_review_specs: list[dict] = []
        for key, slot in slot_key_map.items():
            assignment = assignments_by_slot_id[slot.slot_id]
            spec: dict = {
                "key": key,
                "role": slot.slot_role.value,
                "label": slot.semantic_label,
                "action": assignment.action.value,
                "text": assignment.text,
                "character_count": assignment.character_count,
                "capacity_characters": assignment.capacity_characters,
                "capacity_utilization": assignment.capacity_utilization,
                "explicit_line_count": assignment.explicit_line_count,
                "max_lines_estimate": assignment.max_lines_estimate,
                "group_id": assignment.group_id,
                "sequence_index": assignment.sequence_index,
            }
            slot_review_specs.append(spec)

        # ------------------------------------------------------------------
        # Step 5 — Build group_descriptions
        # ------------------------------------------------------------------
        # Map slot_id → K-key for building member_keys per group
        slot_id_to_key = {slot.slot_id: key for key, slot in slot_key_map.items()}

        # Validate all group member references before building descriptions
        for group in slot_map.groups:
            for sid in group.member_slot_ids:
                if sid not in slot_id_to_key:
                    raise ManagerReviewError(
                        f"Group {group.group_id!r} references member_slot_id "
                        f"{sid!r} which is not present in the slot_map"
                    )

        group_descriptions: list[dict] = []
        for group in slot_map.groups:
            member_keys = [slot_id_to_key[sid] for sid in group.member_slot_ids]
            group_descriptions.append({
                "group_id": group.group_id,
                "group_role": group.group_role,
                "semantic_label": group.semantic_label,
                "member_keys": member_keys,
                "sequence_index": group.sequence_index,
            })

        # ------------------------------------------------------------------
        # Step 6 — Invoke reviewer once (no retry)
        # ------------------------------------------------------------------
        model_output = self._reviewer.review(
            request.brief,
            request.source_material,
            slot_review_specs,
            group_descriptions,
        )

        # Step 7 — Model output already validated by Pydantic on parse

        # ------------------------------------------------------------------
        # Step 7 — Validate slot key refs in issues
        # ------------------------------------------------------------------
        for issue in model_output.issues:
            for k in issue.slot_keys:
                if k not in slot_key_map:
                    raise ManagerReviewError(
                        f"Issue references unknown slot key {k!r}. "
                        f"Valid keys: {sorted(slot_key_map.keys())}"
                    )

        # ------------------------------------------------------------------
        # Step 8 — Validate slot key refs in factual_flags
        # ------------------------------------------------------------------
        for flag in model_output.factual_flags:
            for k in flag.slot_keys:
                if k not in slot_key_map:
                    raise ManagerReviewError(
                        f"Factual flag references unknown slot key {k!r}. "
                        f"Valid keys: {sorted(slot_key_map.keys())}"
                    )

        # ------------------------------------------------------------------
        # Step 9 — Compute average_score arithmetically
        # ------------------------------------------------------------------
        scores = [
            model_output.answer_first_title.score,
            model_output.core_message_clarity.score,
            model_output.vertical_logic.score,
            model_output.exhibit_title_consistency.score,
            model_output.mece_structure.score,
            model_output.content_density.score,
        ]
        average_score = round(sum(scores) / 6, 4)

        # ------------------------------------------------------------------
        # Step 10 — Build and return ManagerReviewResult (with slide identity)
        # ------------------------------------------------------------------
        return ManagerReviewResult(
            slide_id=draft.slide_id,
            deck_id=draft.deck_id,
            slide_number=draft.slide_number,
            recommendation=model_output.recommendation,
            average_score=average_score,
            answer_first_title=model_output.answer_first_title,
            core_message_clarity=model_output.core_message_clarity,
            vertical_logic=model_output.vertical_logic,
            exhibit_title_consistency=model_output.exhibit_title_consistency,
            mece_structure=model_output.mece_structure,
            content_density=model_output.content_density,
            issues=model_output.issues,
            factual_flags=model_output.factual_flags,
            executive_summary=model_output.executive_summary,
        )
