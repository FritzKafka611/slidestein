"""Deterministic RevisionRouter for M9 (v1.1).

Zero API calls.  Routing precedence (applied in order):
  0. CONTRACT ERROR (identity/completeness) → RevisionError (hard stop)
  1. Contradiction detection               → manual_review
  2. Material structural M8 issue          → template_reselection
  3. Material M7 content issue / material factual flags → content_revision
  4. Material text-fit M8 on ALL-REPLACE slots → content_revision
  4b. Material text-fit M8 with ANY non-REPLACE slot → template_reselection
  5. Both approve/pass, no material issues → finalize
  6. Semantic recommendation fallback

Material = critical or major severity.

Contradictions (→ manual_review):
  M8 recommendation=pass  AND any critical visual issue
  M7 recommendation=approve AND any critical manager issue
  M7 recommendation=approve AND any critical factual flag

Structural M8 categories (→ template_reselection):
  visual_hierarchy, alignment_and_spacing, balance_and_whitespace,
  typography_and_style_consistency

Content M7 categories (→ content_revision):
  answer_first_title, core_message_clarity, vertical_logic,
  exhibit_title_consistency, mece_structure, factual_grounding

Material factual flags: severity in {critical, major} AND category=factual_grounding

target_slot_keys:
  content_revision: the exact editable K-keys to patch
  template_reselection / manual_review / finalize: [] (no content-patch scope)
"""

from __future__ import annotations

from slidestein.drafting.models import SlotDraftAction
from slidestein.drafting.service import build_slot_key_mapping
from slidestein.drafting.validation import validate_draft_slot_map_identity
from slidestein.revision.errors import RevisionError
from slidestein.revision.models import (
    RevisionPlan,
    RevisionRequest,
    RevisionRoute,
)
from slidestein.slots.roles import SlotRole

_MATERIAL_SEVERITIES = {"critical", "major"}

_STRUCTURAL_M8_CATEGORIES = frozenset({
    "visual_hierarchy",
    "alignment_and_spacing",
    "balance_and_whitespace",
    "typography_and_style_consistency",
})

_CONTENT_M7_CATEGORIES = frozenset({
    "answer_first_title",
    "core_message_clarity",
    "vertical_logic",
    "exhibit_title_consistency",
    "mece_structure",
    "factual_grounding",
})


def _plan(
    request: RevisionRequest,
    route: RevisionRoute,
    reasons: list[str],
    target_slot_keys: list[str] = (),
    manager_issue_indexes: list[int] = (),
    visual_issue_indexes: list[int] = (),
    factual_flag_indexes: list[int] = (),
) -> RevisionPlan:
    # template_reselection / manual_review / finalize: no content-patch scope
    if route != RevisionRoute.CONTENT_REVISION:
        target_slot_keys = []
    return RevisionPlan(
        slide_id=request.draft.slide_id,
        deck_id=request.draft.deck_id,
        slide_number=request.draft.slide_number,
        route=route,
        reasons=reasons,
        target_slot_keys=list(target_slot_keys),
        manager_issue_indexes=list(manager_issue_indexes),
        visual_issue_indexes=list(visual_issue_indexes),
        factual_flag_indexes=list(factual_flag_indexes),
        requires_model_call=(route == RevisionRoute.CONTENT_REVISION),
    )


class RevisionRouter:
    """Produces a RevisionPlan from a RevisionRequest with zero API calls."""

    def route(self, request: RevisionRequest) -> RevisionPlan:
        # ---------------------------------------------------------------
        # Step 0 — Contract validation (raises RevisionError on failure)
        # ---------------------------------------------------------------
        _validate_contract(request)

        # Build K-key map once; used throughout
        slot_key_map = build_slot_key_mapping(request.slot_map.slots)
        assignments_by_slot_id = {a.slot_id: a for a in request.draft.assignments}

        # Defensive K-key validation for issue references
        _validate_issue_keys(request, slot_key_map)

        # ---------------------------------------------------------------
        # Step 1 — Contradiction detection → manual_review
        # ---------------------------------------------------------------
        contradiction = _detect_contradiction(request)
        if contradiction:
            return _plan(
                request,
                RevisionRoute.MANUAL_REVIEW,
                reasons=[f"Contradictory review state: {contradiction}"],
            )

        # ---------------------------------------------------------------
        # Step 2 — Material structural M8 issue → template_reselection
        # ---------------------------------------------------------------
        m8_issues = [i.model_dump() for i in request.visual_qa.issues]
        structural_idxs = _collect_material_indexes(m8_issues, _STRUCTURAL_M8_CATEGORIES)
        if structural_idxs:
            cats: set[str] = set()
            for idx in structural_idxs:
                cats.add(m8_issues[idx].get("category", ""))
            return _plan(
                request,
                RevisionRoute.TEMPLATE_RESELECTION,
                reasons=[
                    f"Material structural M8 issue(s) in "
                    f"{', '.join(sorted(cats))}. "
                    "Template layout must be reconsidered."
                ],
                visual_issue_indexes=structural_idxs,
            )

        # ---------------------------------------------------------------
        # Step 3 — Material M7 content issues / material factual_flags → content_revision
        # ---------------------------------------------------------------
        m7_issues = [i.model_dump() for i in request.manager_review.issues]
        content_idxs = _collect_material_indexes(m7_issues, _CONTENT_M7_CATEGORIES)

        # Only material (critical/major) factual_grounding flags
        factual_flag_idxs = [
            i for i, flag in enumerate(request.manager_review.factual_flags)
            if getattr(flag, "severity", None) in _MATERIAL_SEVERITIES
            and getattr(flag, "category", None) == "factual_grounding"
        ]

        if content_idxs or factual_flag_idxs:
            keys: list[str] = []
            cats_m7: set[str] = set()
            for idx in content_idxs:
                iss = m7_issues[idx]
                slot_keys = iss.get("slot_keys") or []
                cat = iss.get("category", "")
                cats_m7.add(cat)
                if slot_keys:
                    # Use exactly the valid editable keys referenced
                    keys.extend(
                        k for k in slot_keys
                        if _key_is_replace(k, slot_key_map, assignments_by_slot_id)
                    )
                elif cat == "answer_first_title":
                    # answer_first_title with no slot_keys → TITLE slots only
                    keys.extend(_title_replace_keys(slot_key_map, assignments_by_slot_id))
                else:
                    # Other content issue with no slot_keys → populated REPLACE slots
                    keys.extend(_populated_replace_keys(slot_key_map, assignments_by_slot_id))
            for idx in factual_flag_idxs:
                flag = request.manager_review.factual_flags[idx]
                flag_keys = getattr(flag, "slot_keys", []) or []
                if flag_keys:
                    keys.extend(
                        k for k in flag_keys
                        if _key_is_replace(k, slot_key_map, assignments_by_slot_id)
                    )
                else:
                    keys.extend(_populated_replace_keys(slot_key_map, assignments_by_slot_id))
            if not keys:
                keys = _populated_replace_keys(slot_key_map, assignments_by_slot_id)
            reasons: list[str] = []
            if content_idxs:
                reasons.append(
                    f"Material M7 content issue(s) in "
                    f"{', '.join(sorted(cats_m7))}. "
                    "Content must be revised."
                )
            if factual_flag_idxs:
                reasons.append(
                    f"Material M7 factual flag(s) require content grounding check "
                    f"({len(factual_flag_idxs)} flag(s))."
                )
            if not reasons:
                reasons = ["M7 content or factual issue requires revision."]
            return _plan(
                request,
                RevisionRoute.CONTENT_REVISION,
                reasons=reasons,
                target_slot_keys=sorted(set(keys)),
                manager_issue_indexes=content_idxs,
                factual_flag_indexes=factual_flag_idxs,
            )

        # ---------------------------------------------------------------
        # Step 4 — Material text-fit M8 issue → content_revision or template_reselection
        # ---------------------------------------------------------------
        text_fit_idxs = _collect_material_indexes(m8_issues, {"text_fit_and_clipping"})
        if text_fit_idxs:
            editable_keys: list[str] = []
            non_editable_found = False
            for idx in text_fit_idxs:
                iss = m8_issues[idx]
                slot_keys = iss.get("slot_keys") or []
                if not slot_keys:
                    # Empty key list → cannot determine editability → template_reselection
                    non_editable_found = True
                    break
                for k in slot_keys:
                    if _key_is_replace(k, slot_key_map, assignments_by_slot_id):
                        editable_keys.append(k)
                    else:
                        non_editable_found = True
                        break
                if non_editable_found:
                    break

            if non_editable_found:
                return _plan(
                    request,
                    RevisionRoute.TEMPLATE_RESELECTION,
                    reasons=[
                        "text_fit_and_clipping issue on non-editable or unidentified slot. "
                        "Template reselection required."
                    ],
                    visual_issue_indexes=text_fit_idxs,
                )
            else:
                return _plan(
                    request,
                    RevisionRoute.CONTENT_REVISION,
                    reasons=[
                        "Material text_fit_and_clipping M8 issue(s) on editable slot(s) "
                        f"{sorted(set(editable_keys))}. "
                        "Content revision can resolve text overflow."
                    ],
                    target_slot_keys=sorted(set(editable_keys)),
                    visual_issue_indexes=text_fit_idxs,
                )

        # ---------------------------------------------------------------
        # Step 5 — Both approve/pass, no material issues → finalize
        # ---------------------------------------------------------------
        m7_ok = request.manager_review.recommendation == "approve"
        m8_ok = request.visual_qa.recommendation == "pass"
        if m7_ok and m8_ok:
            return _plan(
                request,
                RevisionRoute.FINALIZE,
                reasons=["Manager review approved and visual QA passed. No material issues found."],
            )

        # ---------------------------------------------------------------
        # Step 6 — Semantic recommendation fallback
        # ---------------------------------------------------------------
        if not m7_ok and not m8_ok:
            return _plan(
                request,
                RevisionRoute.MANUAL_REVIEW,
                reasons=[
                    "Both manager review and visual QA recommend revision, "
                    "but no material categorised issues found to drive routing. "
                    "Manual review required."
                ],
            )
        if not m7_ok:
            return _plan(
                request,
                RevisionRoute.CONTENT_REVISION,
                reasons=[
                    "Manager review recommends revision; "
                    "no material categorised M7 issues found. "
                    "Attempting content revision as fallback."
                ],
                target_slot_keys=_populated_replace_keys(slot_key_map, assignments_by_slot_id),
            )
        # not m8_ok
        return _plan(
            request,
            RevisionRoute.TEMPLATE_RESELECTION,
            reasons=[
                "Visual QA recommends revision; "
                "no material structural M8 issues found. "
                "Template reselection recommended as fallback."
            ],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_contract(request: RevisionRequest) -> None:
    """Raise RevisionError on any contract violation. Called before routing."""
    draft = request.draft
    mr = request.manager_review
    vq = request.visual_qa

    if not draft.is_complete:
        raise RevisionError("Draft is incomplete (is_complete=False). Cannot route.")

    # No assignment may be NEEDS_INPUT even if is_complete was set
    from slidestein.drafting.models import SlotDraftAction  # noqa: PLC0415
    for assignment in draft.assignments:
        if assignment.action == SlotDraftAction.NEEDS_INPUT:
            raise RevisionError(
                f"Draft has a NEEDS_INPUT assignment for slot {assignment.slot_id!r} "
                "even though is_complete=True. Cannot route."
            )

    # brief_key_message must match draft.brief_key_message
    if request.brief.key_message != draft.brief_key_message:
        raise RevisionError(
            f"brief.key_message {request.brief.key_message!r} "
            f"!= draft.brief_key_message {draft.brief_key_message!r}"
        )

    # M7 identity must match draft identity
    if mr.slide_id != draft.slide_id:
        raise RevisionError(
            f"manager_review.slide_id {mr.slide_id!r} != draft.slide_id {draft.slide_id!r}"
        )
    if mr.deck_id != draft.deck_id:
        raise RevisionError(
            f"manager_review.deck_id {mr.deck_id!r} != draft.deck_id {draft.deck_id!r}"
        )
    if mr.slide_number != draft.slide_number:
        raise RevisionError(
            f"manager_review.slide_number {mr.slide_number} "
            f"!= draft.slide_number {draft.slide_number}"
        )

    # M8 identity must match draft identity
    if vq.slide_id != draft.slide_id:
        raise RevisionError(
            f"visual_qa.slide_id {vq.slide_id!r} != draft.slide_id {draft.slide_id!r}"
        )
    if vq.deck_id != draft.deck_id:
        raise RevisionError(
            f"visual_qa.deck_id {vq.deck_id!r} != draft.deck_id {draft.deck_id!r}"
        )
    if vq.slide_number != draft.slide_number:
        raise RevisionError(
            f"visual_qa.slide_number {vq.slide_number} "
            f"!= draft.slide_number {draft.slide_number}"
        )

    # Slot map / draft identity via shared helper
    validate_draft_slot_map_identity(
        draft=draft,
        slot_map=request.slot_map,
        error_factory=RevisionError,
    )


def _validate_issue_keys(request: RevisionRequest, slot_key_map: dict) -> None:
    """Raise RevisionError if any M7/M8 issue or factual_flag references an unknown slot key."""
    for iss in request.manager_review.issues:
        for k in iss.slot_keys:
            if k not in slot_key_map:
                raise RevisionError(
                    f"manager_review issue references unknown slot key {k!r}. "
                    f"Valid keys: {sorted(slot_key_map.keys())}"
                )
    for flag in request.manager_review.factual_flags:
        for k in getattr(flag, "slot_keys", []):
            if k not in slot_key_map:
                raise RevisionError(
                    f"manager_review factual_flag references unknown slot key {k!r}. "
                    f"Valid keys: {sorted(slot_key_map.keys())}"
                )
    for iss in request.visual_qa.issues:
        for k in iss.slot_keys:
            if k not in slot_key_map:
                raise RevisionError(
                    f"visual_qa issue references unknown slot key {k!r}. "
                    f"Valid keys: {sorted(slot_key_map.keys())}"
                )


def _detect_contradiction(request: RevisionRequest) -> str | None:
    """Return a description string if any review contradiction exists, else None."""
    # M8 pass + any critical visual issue
    if request.visual_qa.recommendation == "pass":
        for iss in request.visual_qa.issues:
            if iss.severity == "critical":
                return (
                    f"M8 recommendation=pass but a critical {iss.category} issue exists "
                    f"(slot_keys={iss.slot_keys!r})"
                )

    # M7 approve + any critical manager issue
    if request.manager_review.recommendation == "approve":
        for iss in request.manager_review.issues:
            if iss.severity == "critical":
                return (
                    f"M7 recommendation=approve but a critical {iss.category} issue exists"
                )
        # M7 approve + any critical factual flag
        for flag in request.manager_review.factual_flags:
            if getattr(flag, "severity", None) == "critical":
                return (
                    "M7 recommendation=approve but a critical factual_grounding flag exists"
                )

    return None


def _collect_material_indexes(issues: list[dict], categories: frozenset | set) -> list[int]:
    """Return indexes of material (critical/major) issues from `categories`."""
    return [
        i for i, iss in enumerate(issues)
        if iss.get("severity", "") in _MATERIAL_SEVERITIES
        and iss.get("category", "") in categories
    ]


def _all_replace_keys(slot_key_map: dict, assignments_by_slot_id: dict) -> list[str]:
    """Return sorted list of all K-keys with REPLACE action in the draft."""
    return sorted(
        k for k, slot in slot_key_map.items()
        if assignments_by_slot_id.get(slot.slot_id) is not None
        and assignments_by_slot_id[slot.slot_id].action == SlotDraftAction.REPLACE
    )


def _populated_replace_keys(slot_key_map: dict, assignments_by_slot_id: dict) -> list[str]:
    """Return sorted list of REPLACE K-keys that have non-empty text."""
    result = []
    for k, slot in slot_key_map.items():
        a = assignments_by_slot_id.get(slot.slot_id)
        if a is None:
            continue
        if a.action != SlotDraftAction.REPLACE:
            continue
        if a.text and a.text.strip():
            result.append(k)
    return sorted(result)


def _title_replace_keys(slot_key_map: dict, assignments_by_slot_id: dict) -> list[str]:
    """Return sorted list of REPLACE K-keys whose slot role is TITLE."""
    result = []
    for k, slot in slot_key_map.items():
        if slot.slot_role != SlotRole.TITLE:
            continue
        a = assignments_by_slot_id.get(slot.slot_id)
        if a is None:
            continue
        if a.action == SlotDraftAction.REPLACE:
            result.append(k)
    return sorted(result)


def _key_is_replace(
    key: str,
    slot_key_map: dict,
    assignments_by_slot_id: dict,
) -> bool:
    slot = slot_key_map.get(key)
    if slot is None:
        return False
    assignment = assignments_by_slot_id.get(slot.slot_id)
    if assignment is None:
        return False
    return assignment.action == SlotDraftAction.REPLACE
