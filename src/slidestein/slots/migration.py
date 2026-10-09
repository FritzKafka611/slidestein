"""Deterministic normalization of legacy cached TemplateSlotMap exclusion semantics.

M5.2 introduced the correct semantic split:

    non_editable_elements          -- technically non-editable native shapes
    excluded_editable_candidates   -- editable shapes Vision declined as slots

Legacy maps (produced before this distinction existed) stored both categories
mixed inside non_editable_elements with excluded_editable_candidates == [].

normalize_cached_slot_map() re-partitions using the current native shape
descriptors as the authoritative source of technical editability.

Properties:
- Deterministic : same descriptors always produce the same result
- Idempotent    : normalize(normalize(m)) == normalize(m)
- Zero-Vision   : no LLM calls
- Lossless      : slots, groups, IDs, geometry, fingerprint, summary unchanged
"""

from __future__ import annotations

from slidestein.slots.models import NativeShapeDescriptor, TemplateSlotMap


def normalize_cached_slot_map(
    slot_map: TemplateSlotMap,
    descriptors: list[NativeShapeDescriptor],
) -> TemplateSlotMap:
    """Re-partition exclusion lists using current native shape descriptors.

    Shapes that are technically non-editable (can_edit_text=False, not a
    chart/table) belong in non_editable_elements.  All other entries from
    the combined exclusion pool belong in excluded_editable_candidates.

    unsupported_elements (charts, tables, SmartArt) are never touched.

    Returns a new TemplateSlotMap; all other fields are unchanged copies.
    """
    # Authoritative set of native non-editable shape paths from current
    # inspection results.  This is the single source of truth.
    native_non_editable_paths: set[str] = {
        d.shape_path
        for d in descriptors
        if not d.can_edit_text and d.source_kind not in ("chart", "table")
    }

    # Merge both exclusion lists, deduplicating by shape_path (first wins).
    # This makes the function safe to call on already-normalised maps and
    # on maps that may have ended up with an entry in both lists.
    seen: set[str] = set()
    combined: list[dict] = []
    for entry in list(slot_map.non_editable_elements) + list(slot_map.excluded_editable_candidates):
        sp = entry.get("shape_path", "")
        if sp not in seen:
            seen.add(sp)
            combined.append(entry)

    # Partition using native truth.
    new_non_editable: list[dict] = []
    new_excluded_editable: list[dict] = []
    for entry in combined:
        if entry.get("shape_path", "") in native_non_editable_paths:
            new_non_editable.append(entry)
        else:
            new_excluded_editable.append(entry)

    return slot_map.model_copy(update={
        "non_editable_elements": new_non_editable,
        "excluded_editable_candidates": new_excluded_editable,
    })


def exclusion_changed(original: TemplateSlotMap, normalized: TemplateSlotMap) -> bool:
    """Return True if normalization moved any entry between exclusion lists."""
    orig_ne = {e.get("shape_path", "") for e in original.non_editable_elements}
    norm_ne = {e.get("shape_path", "") for e in normalized.non_editable_elements}
    return orig_ne != norm_ne
