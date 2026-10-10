"""SlideContentDraftService — orchestrates K-key mapping + generator + validation.

Flow:
  1. Build deterministic K1..Kn slot mapping (stable sort by position).
  2. Build compact slot specs and group context for the prompt.
  3. Call ContentDraftGenerator once (text-only, no images).
  4. Validate exact slot coverage (returned == supplied).
  5. Map K keys back to TemplateSlots.
  6. Compute capacity metrics; reject violations.
  7. Derive is_complete.
  8. Return SlideContentDraft.

No persistence in M5.3 — drafts are request-specific, not library artifacts.
"""

from __future__ import annotations

from typing import Optional

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.drafting.analysis_models import ContentDraftModelOutput
from slidestein.drafting.generator import ContentDraftGenerator
from slidestein.drafting.models import (
    SlotDraftAction,
    SlotDraftAssignment,
    SlideContentDraft,
)
from slidestein.drafting.prompt import build_brief_summary, preferred_target_characters
from slidestein.drafting.versions import CONTENT_DRAFT_SCHEMA_VERSION
from slidestein.slots.models import SlotGroup, TemplateSlot, TemplateSlotMap

_MAX_EXAMPLE_CHARS = 80


# ---------------------------------------------------------------------------
# Shared capacity validation helper (reused by M5.3 and M9)
# ---------------------------------------------------------------------------


def validate_text_capacity(
    text: str,
    max_chars: int,
    max_lines: int,
    key: str,
    error_factory,
) -> None:
    """Raise error_factory(msg) if text exceeds hard character or line limits.

    Does NOT truncate, resize, or modify the text — only validates.
    """
    char_count = len(text)
    if max_chars > 0 and char_count > max_chars:
        raise error_factory(
            f"Revised text for {key} exceeds capacity: "
            f"{char_count} chars > {max_chars} max"
        )
    line_count = text.count("\n") + 1
    if max_lines > 0 and line_count > max_lines:
        raise error_factory(
            f"Revised text for {key} exceeds line limit: "
            f"{line_count} lines > {max_lines} max"
        )
_CAPACITY_TARGET = 0.85  # prompt target; hard limit is 1.0


# ---------------------------------------------------------------------------
# K-key mapping helpers (module-level so CLI can call them for dry-run)
# ---------------------------------------------------------------------------


def _slot_sort_key(slot: TemplateSlot) -> tuple:
    y = slot.geometry.get("y_ratio", 0.0)
    x = slot.geometry.get("x_ratio", 0.0)
    seq = slot.sequence_index if slot.sequence_index is not None else 9999
    return (y, x, seq, slot.slot_id)


def build_slot_key_mapping(slots: list[TemplateSlot]) -> dict[str, TemplateSlot]:
    """Return a deterministic K1..Kn -> TemplateSlot mapping.

    Sort order: y_ratio, x_ratio, sequence_index (None=last), slot_id.
    Given the same TemplateSlotMap the mapping is always identical.
    """
    sorted_slots = sorted(slots, key=_slot_sort_key)
    return {f"K{i + 1}": slot for i, slot in enumerate(sorted_slots)}


def build_slot_specs(
    slot_key_map: dict[str, TemplateSlot],
) -> list[dict]:
    """Build compact slot specification dicts for the prompt."""
    specs: list[dict] = []
    for key, slot in slot_key_map.items():
        example = (slot.current_text or "")[:_MAX_EXAMPLE_CHARS]
        hard_chars = slot.capacity.max_characters_estimate
        pref_chars = preferred_target_characters(hard_chars)
        specs.append({
            "key": key,
            "role": slot.slot_role.value,
            "label": slot.semantic_label,
            "group": slot.group_id or "",
            "sequence": slot.sequence_index,
            "hard_max_characters": hard_chars,
            "preferred_target_characters": pref_chars,
            "hard_max_lines": slot.capacity.max_lines_estimate,
            "example": example,
        })
    return specs


def build_groups_context(
    groups: list[SlotGroup],
    slot_key_map: dict[str, TemplateSlot],
) -> list[dict]:
    """Build group context dicts for the prompt (reverse-maps slot_id → Kn)."""
    slot_id_to_key = {s.slot_id: k for k, s in slot_key_map.items()}
    result: list[dict] = []
    for group in groups:
        member_keys = [
            slot_id_to_key[sid]
            for sid in group.member_slot_ids
            if sid in slot_id_to_key
        ]
        if member_keys:
            result.append({
                "group_id": group.group_id,
                "group_role": group.group_role,
                "semantic_label": group.semantic_label,
                "member_keys": member_keys,
            })
    return result


# ---------------------------------------------------------------------------
# Assignment builders
# ---------------------------------------------------------------------------


def _build_replace_assignment(
    key: str, slot: TemplateSlot, text: str
) -> SlotDraftAssignment:
    char_count = len(text)
    max_chars = slot.capacity.max_characters_estimate
    max_lines = slot.capacity.max_lines_estimate
    utilization = round(char_count / max_chars, 4) if max_chars > 0 else 0.0
    line_count = text.count("\n") + 1

    return SlotDraftAssignment(
        slot_id=slot.slot_id,
        shape_id=slot.shape_id,
        shape_path=slot.shape_path,
        slot_role=slot.slot_role,
        semantic_label=slot.semantic_label,
        action=SlotDraftAction.REPLACE,
        text=text,
        missing_information=None,
        character_count=char_count,
        capacity_characters=max_chars,
        capacity_utilization=utilization,
        explicit_line_count=line_count,
        max_lines_estimate=max_lines,
        group_id=slot.group_id,
        sequence_index=slot.sequence_index,
    )


def _build_clear_assignment(slot: TemplateSlot) -> SlotDraftAssignment:
    return SlotDraftAssignment(
        slot_id=slot.slot_id,
        shape_id=slot.shape_id,
        shape_path=slot.shape_path,
        slot_role=slot.slot_role,
        semantic_label=slot.semantic_label,
        action=SlotDraftAction.CLEAR,
        text=None,
        missing_information=None,
        character_count=0,
        capacity_characters=slot.capacity.max_characters_estimate,
        capacity_utilization=0.0,
        explicit_line_count=0,
        max_lines_estimate=slot.capacity.max_lines_estimate,
        group_id=slot.group_id,
        sequence_index=slot.sequence_index,
    )


def _build_needs_input_assignment(
    slot: TemplateSlot, missing: str
) -> SlotDraftAssignment:
    return SlotDraftAssignment(
        slot_id=slot.slot_id,
        shape_id=slot.shape_id,
        shape_path=slot.shape_path,
        slot_role=slot.slot_role,
        semantic_label=slot.semantic_label,
        action=SlotDraftAction.NEEDS_INPUT,
        text=None,
        missing_information=missing,
        character_count=0,
        capacity_characters=slot.capacity.max_characters_estimate,
        capacity_utilization=0.0,
        explicit_line_count=0,
        max_lines_estimate=slot.capacity.max_lines_estimate,
        group_id=slot.group_id,
        sequence_index=slot.sequence_index,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SlideContentDraftService:
    """Orchestrates one content draft for a single slide."""

    def __init__(self, generator: ContentDraftGenerator) -> None:
        self._generator = generator

    def draft(
        self,
        brief: ConsultingSlideBrief,
        slot_map: TemplateSlotMap,
        source_material: Optional[str] = None,
    ) -> SlideContentDraft:
        """Generate a SlideContentDraft.  Makes exactly ONE LLM call.

        Raises:
            ContentDraftGenerationError: on provider failure, coverage
                violation, or capacity violation.
        """
        from slidestein.drafting.providers.sap_aicore import ContentDraftGenerationError  # noqa: PLC0415

        # 1-2. Build K mapping and specs.
        slot_key_map = build_slot_key_mapping(slot_map.slots)
        slot_specs = build_slot_specs(slot_key_map)
        groups_context = build_groups_context(slot_map.groups, slot_key_map)
        brief_summary = build_brief_summary(brief)

        # 3. Generate.
        output: ContentDraftModelOutput = self._generator.generate(
            brief=brief,
            source_material=source_material,
            slot_specs=slot_specs,
            groups_context=groups_context,
        )

        # 4. Validate exact coverage (before building assignments).
        supplied_keys = set(slot_key_map.keys())
        returned_keys = (
            {r.slot_key for r in output.replacements}
            | set(output.clear_slots)
            | {n.slot_key for n in output.needs_input}
        )
        missing = supplied_keys - returned_keys
        unknown = returned_keys - supplied_keys
        if missing or unknown:
            parts: list[str] = []
            if missing:
                parts.append(f"missing slots: {sorted(missing)}")
            if unknown:
                parts.append(f"unknown slots: {sorted(unknown)}")
            raise ContentDraftGenerationError(
                "Draft response does not exactly cover supplied slot keys — "
                + "; ".join(parts)
            )

        # 5-8. Map keys → assignments, validate capacity.
        replacement_map = {r.slot_key: r.text for r in output.replacements}
        clear_set = set(output.clear_slots)
        needs_input_map = {n.slot_key: n.missing_information for n in output.needs_input}

        assignments: list[SlotDraftAssignment] = []
        for key, slot in slot_key_map.items():
            if key in replacement_map:
                text = replacement_map[key]
                char_count = len(text)
                max_chars = slot.capacity.max_characters_estimate
                if max_chars > 0 and char_count > max_chars:
                    raise ContentDraftGenerationError(
                        f"Generated text for {key} exceeds capacity: "
                        f"{char_count} chars > {max_chars} max "
                        f"(role={slot.slot_role.value}, label={slot.semantic_label!r})"
                    )
                line_count = text.count("\n") + 1
                max_lines = slot.capacity.max_lines_estimate
                if max_lines > 0 and line_count > max_lines:
                    raise ContentDraftGenerationError(
                        f"Generated text for {key} exceeds line limit: "
                        f"{line_count} lines > {max_lines} max "
                        f"(role={slot.slot_role.value})"
                    )
                assignments.append(_build_replace_assignment(key, slot, text))
            elif key in clear_set:
                assignments.append(_build_clear_assignment(slot))
            else:
                assignments.append(
                    _build_needs_input_assignment(slot, needs_input_map[key])
                )

        # 9. Derive is_complete.
        is_complete = all(
            a.action != SlotDraftAction.NEEDS_INPUT for a in assignments
        )

        return SlideContentDraft(
            schema_version=CONTENT_DRAFT_SCHEMA_VERSION,
            slide_id=slot_map.slide_id,
            deck_id=slot_map.deck_id,
            slide_number=slot_map.slide_number,
            brief_key_message=brief.key_message,
            assignments=assignments,
            open_questions=list(output.open_questions),
            drafting_summary=output.drafting_summary,
            is_complete=is_complete,
        )
