"""TemplateSlotAnalysisService — orchestrates inspection + Vision + capacity + mapping.

Flow:
  1. Load SlideRecord from library.
  2. Check currentness (fingerprint match) — return cached if current & not forced.
  3. Inspect shapes natively (no LLM).
  4. Build candidate mapping S1..Sn for editable shapes only.
  5. Compute analysis input fingerprint.
  6. dry_run=True  → return partial TemplateSlotMap without Vision or persistence.
  7. Call Vision analyzer once.
  8. Validate: model returned only supplied keys; no key invented.
  9. Combine native + Vision data into TemplateSlotMap.
  10. Persist to slide_slot_maps (if not dry_run).
  11. Return TemplateSlotMap.
"""

from __future__ import annotations

from typing import Optional

from slidestein.slots.analysis_models import SlotAnalysisModelOutput
from slidestein.slots.analyzer import SlotSemanticAnalyzer
from slidestein.slots.capacity import estimate_slot_capacity
from slidestein.slots.fingerprint import (
    compute_slot_analysis_input_fingerprint,
    compute_slot_id,
)
from slidestein.slots.inspector import SlideShapeInspector
from slidestein.slots.models import (
    NativeShapeDescriptor,
    SlotCapacity,
    SlotGroup,
    TemplateSlot,
    TemplateSlotMap,
)
from slidestein.slots.versions import (
    SLOT_ANALYSIS_PROMPT_VERSION,
    SLOT_MAP_SCHEMA_VERSION,
)


def _make_candidate_key(index: int) -> str:
    return f"S{index + 1}"


def _build_candidate_dict(
    descriptors: list[NativeShapeDescriptor],
) -> dict[str, NativeShapeDescriptor]:
    """Map S1..Sn keys to editable shape descriptors (stable sort by shape_path)."""
    editable = [d for d in descriptors if d.can_edit_text]
    # Sort by (y, x) position for stable, visual-reading-order keys
    editable_sorted = sorted(editable, key=lambda d: (d.y, d.x))
    return {_make_candidate_key(i): d for i, d in enumerate(editable_sorted)}


def _build_candidate_fingerprint_entry(key: str, d: NativeShapeDescriptor) -> dict:
    return {
        "key": key,
        "shape_path": d.shape_path,
        "shape_type": d.shape_type,
        "x": d.x,
        "y": d.y,
        "width": d.width,
        "height": d.height,
        "can_edit_text": d.can_edit_text,
        "text": d.text,
    }


def _descriptor_to_non_editable_entry(d: NativeShapeDescriptor) -> dict:
    return {
        "shape_id": d.shape_id,
        "shape_path": d.shape_path,
        "source_kind": d.source_kind,
        "x_ratio": d.x_ratio,
        "y_ratio": d.y_ratio,
        "width_ratio": d.width_ratio,
        "height_ratio": d.height_ratio,
        "text": d.text[:100] if d.text else "",
    }


def _descriptor_to_unsupported_entry(d: NativeShapeDescriptor) -> dict:
    return {
        "shape_id": d.shape_id,
        "shape_path": d.shape_path,
        "source_kind": d.source_kind,
        "x_ratio": d.x_ratio,
        "y_ratio": d.y_ratio,
        "width_ratio": d.width_ratio,
        "height_ratio": d.height_ratio,
    }


def _build_geometry_dict(d: NativeShapeDescriptor) -> dict:
    return {
        "x": d.x,
        "y": d.y,
        "width": d.width,
        "height": d.height,
        "x_ratio": d.x_ratio,
        "y_ratio": d.y_ratio,
        "width_ratio": d.width_ratio,
        "height_ratio": d.height_ratio,
    }


class TemplateSlotAnalysisService:
    """Orchestrates the full slot analysis pipeline for one slide."""

    def __init__(
        self,
        library: object,       # SlideLibrary (context manager already entered)
        inspector: Optional[SlideShapeInspector] = None,
        analyzer: Optional[SlotSemanticAnalyzer] = None,
        provider_name: str = "sap_ai_core",
        model_name: str = "unknown",
    ) -> None:
        self._library = library
        self._inspector = inspector or SlideShapeInspector()
        self._analyzer = analyzer
        self._provider_name = provider_name
        self._model_name = model_name

    def analyze(
        self,
        slide_id: str,
        force: bool = False,
        dry_run: bool = False,
    ) -> TemplateSlotMap:
        """Run (or return cached) slot analysis for one slide.

        Args:
            slide_id: stable slide identifier.
            force: if True, bypass the currentness cache and re-analyse.
            dry_run: if True, skip the Vision call and persistence.  Returns a
                     partial TemplateSlotMap with empty slots (useful for
                     inspecting candidates before spending a Vision token).

        Raises:
            ValueError: slide not found in library, or preview missing.
            SlotAnalysisError: if Vision call fails.
        """
        record = self._library.get_record(slide_id)  # type: ignore[union-attr]
        if record is None:
            raise ValueError(f"Slide not found in library: {slide_id!r}")

        # ---------------------------------------------------------------
        # 1. Inspect natively
        # ---------------------------------------------------------------
        descriptors = self._inspector.inspect(record)

        # ---------------------------------------------------------------
        # 2. Build candidates (editable only, sorted by visual position)
        # ---------------------------------------------------------------
        candidates = _build_candidate_dict(descriptors)

        # ---------------------------------------------------------------
        # 3. Compute fingerprint
        # ---------------------------------------------------------------
        fp_entries = [
            _build_candidate_fingerprint_entry(k, d)
            for k, d in sorted(candidates.items())
        ]
        fingerprint = compute_slot_analysis_input_fingerprint(
            slide_id=slide_id,
            candidates=fp_entries,
            slot_map_schema_version=SLOT_MAP_SCHEMA_VERSION,
            prompt_version=SLOT_ANALYSIS_PROMPT_VERSION,
        )

        # ---------------------------------------------------------------
        # 4. Check cache (unless forced)
        # ---------------------------------------------------------------
        if not force and not dry_run:
            if self._library.slot_map_is_current(  # type: ignore[union-attr]
                slide_id, SLOT_MAP_SCHEMA_VERSION, fingerprint,
                provider=self._provider_name,
                model=self._model_name,
            ):
                cached = self._library.get_slot_map(slide_id, SLOT_MAP_SCHEMA_VERSION)  # type: ignore[union-attr]
                if cached is not None:
                    from slidestein.slots.migration import exclusion_changed, normalize_cached_slot_map  # noqa: PLC0415
                    raw_map = TemplateSlotMap.model_validate_json(cached[0])
                    normalized = normalize_cached_slot_map(raw_map, descriptors)
                    if exclusion_changed(raw_map, normalized):
                        self._library.patch_slot_map_json(  # type: ignore[union-attr]
                            slide_id, SLOT_MAP_SCHEMA_VERSION, normalized.model_dump_json()
                        )
                    return normalized

        # ---------------------------------------------------------------
        # 5. Classify shapes into editable / non-editable / unsupported
        # ---------------------------------------------------------------
        editable_paths = {d.shape_path for d in candidates.values()}
        non_editable: list[dict] = []
        unsupported: list[dict] = []

        for d in descriptors:
            if d.shape_path in editable_paths:
                continue  # will be handled by Vision
            if d.source_kind in ("chart", "table"):
                unsupported.append(_descriptor_to_unsupported_entry(d))
            else:
                # All non-editable shapes — including group parent nodes — are
                # preserved here.  Editable children of a group appear in
                # candidates under their own shape_paths and are independent.
                if not d.can_edit_text:
                    non_editable.append(_descriptor_to_non_editable_entry(d))

        slide_width = record.slide_width_emu if record.slide_width_emu else 9144000
        slide_height = record.slide_height_emu if record.slide_height_emu else 5143500

        # ---------------------------------------------------------------
        # 6. dry_run: return without Vision or persistence
        # ---------------------------------------------------------------
        if dry_run:
            candidate_map = [
                {
                    "candidate_key": k,
                    "shape_id": d.shape_id,
                    "shape_path": d.shape_path,
                    "source_kind": d.source_kind,
                    "text_preview": d.text[:80] if d.text else "",
                    "x_ratio": d.x_ratio,
                    "y_ratio": d.y_ratio,
                    "width_ratio": d.width_ratio,
                    "height_ratio": d.height_ratio,
                    "can_edit_text": d.can_edit_text,
                    "capacity": estimate_slot_capacity(d).model_dump(),
                }
                for k, d in sorted(candidates.items())
            ]
            return TemplateSlotMap(
                schema_version=SLOT_MAP_SCHEMA_VERSION,
                slide_id=slide_id,
                deck_id=getattr(record, "deck_id", None),
                slide_number=record.slide_number,
                slide_width=slide_width,
                slide_height=slide_height,
                slots=[],
                non_editable_elements=non_editable,
                excluded_editable_candidates=[],
                unsupported_elements=unsupported,
                groups=[],
                analysis_summary=(
                    f"DRY RUN — {len(candidates)} editable candidate(s), "
                    f"no Vision call made."
                ),
                slot_analysis_input_fingerprint=fingerprint,
                candidate_map=candidate_map,
            )

        # ---------------------------------------------------------------
        # 7. Vision analysis (one call)
        # ---------------------------------------------------------------
        if self._analyzer is None:
            raise ValueError(
                "No SlotSemanticAnalyzer configured — cannot run Vision analysis. "
                "Pass analyzer= to the service, or use dry_run=True."
            )

        preview_path = str(record.preview_path) if record.preview_path else None
        if not preview_path:
            raise ValueError(
                f"No preview image for slide {slide_id!r}. "
                "Re-index the slide with preview rendering enabled."
            )

        vision_output: SlotAnalysisModelOutput = self._analyzer.analyze(
            preview_path=preview_path,
            candidates=candidates,
        )

        # ---------------------------------------------------------------
        # 8. Validate exact candidate coverage BEFORE building any slots
        # ---------------------------------------------------------------
        # Duplicate detection already happens inside SlotAnalysisModelOutput
        # (model_validator on raw assessment list).  Here we enforce that
        # returned_keys == supplied_keys: no missing, no unknown.
        from slidestein.slots.providers.sap_aicore import SlotAnalysisError  # noqa: PLC0415
        supplied_keys = set(candidates.keys())
        returned_keys = {a.candidate_key for a in vision_output.assessments}
        missing_keys = supplied_keys - returned_keys
        unknown_keys = returned_keys - supplied_keys
        if missing_keys or unknown_keys:
            parts = []
            if missing_keys:
                parts.append(f"missing: {sorted(missing_keys)}")
            if unknown_keys:
                parts.append(f"unknown: {sorted(unknown_keys)}")
            raise SlotAnalysisError(
                f"Vision response does not exactly cover supplied candidates — "
                + "; ".join(parts)
            )

        # ---------------------------------------------------------------
        # 9. Merge Vision assessments with native descriptors
        # ---------------------------------------------------------------
        assessment_map = {a.candidate_key: a for a in vision_output.assessments}

        slots: list[TemplateSlot] = []
        excluded_editable: list[dict] = []  # editable candidates Vision declined as slots

        # Reverse map: candidate_key → shape_path (unused here, kept for clarity)
        key_to_path = {k: d.shape_path for k, d in candidates.items()}

        for key in sorted(candidates.keys()):
            descriptor = candidates[key]
            assessment = assessment_map[key]  # guaranteed present after coverage check

            capacity: SlotCapacity = estimate_slot_capacity(descriptor)
            slot_id = compute_slot_id(slide_id, descriptor.shape_path)

            if not assessment.include_as_slot:
                excluded_editable.append(_descriptor_to_non_editable_entry(descriptor))
                continue

            from slidestein.slots.roles import SlotRole  # noqa: PLC0415
            slot = TemplateSlot(
                slot_id=slot_id,
                shape_id=descriptor.shape_id,
                shape_path=descriptor.shape_path,
                slot_role=assessment.slot_role,
                semantic_label=assessment.semantic_label,
                editable=descriptor.can_edit_text,  # application-owned
                confidence=assessment.confidence,
                current_text=descriptor.text,
                geometry=_build_geometry_dict(descriptor),
                capacity=capacity,
                group_id=assessment.group_key,
                sequence_index=assessment.sequence_index,
                notes=assessment.rationale,
            )
            slots.append(slot)

        # ---------------------------------------------------------------
        # 9. Build slot groups from Vision assessments
        # ---------------------------------------------------------------
        groups_map: dict[str, SlotGroup] = {}
        for slot in slots:
            if slot.group_id is None:
                continue
            gk = slot.group_id
            if gk not in groups_map:
                # Find group_role from the first assessment with this group_key
                group_role = ""
                for a in vision_output.assessments:
                    if a.group_key == gk and a.group_role:
                        group_role = a.group_role
                        break
                groups_map[gk] = SlotGroup(
                    group_id=gk,
                    group_role=group_role,
                    member_slot_ids=[],
                    semantic_label=group_role or gk,
                )
            groups_map[gk].member_slot_ids.append(slot.slot_id)

        # Sort groups by first member's sequence_index
        groups = sorted(groups_map.values(), key=lambda g: g.group_id)

        # ---------------------------------------------------------------
        # 10. Build TemplateSlotMap
        # ---------------------------------------------------------------
        slot_map = TemplateSlotMap(
            schema_version=SLOT_MAP_SCHEMA_VERSION,
            slide_id=slide_id,
            deck_id=getattr(record, "deck_id", None),
            slide_number=record.slide_number,
            slide_width=slide_width,
            slide_height=slide_height,
            slots=slots,
            non_editable_elements=non_editable,
            excluded_editable_candidates=excluded_editable,
            unsupported_elements=unsupported,
            groups=groups,
            analysis_summary=vision_output.analysis_summary,
            slot_analysis_input_fingerprint=fingerprint,
        )

        # ---------------------------------------------------------------
        # 11. Persist
        # ---------------------------------------------------------------
        self._library.upsert_slot_map(  # type: ignore[union-attr]
            slide_id=slide_id,
            version=SLOT_MAP_SCHEMA_VERSION,
            fingerprint=fingerprint,
            prompt_version=SLOT_ANALYSIS_PROMPT_VERSION,
            provider=self._provider_name,
            model=self._model_name,
            slot_map_json=slot_map.model_dump_json(),
        )

        return slot_map
