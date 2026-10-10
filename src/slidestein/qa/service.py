"""VisualQAService — orchestrates render + native inspection + Vision review (v1.1).

Flow:
  1.  Validate draft completeness (is_complete must be True; no needs_input).
  2.  Validate draft ↔ slot-map identity (IDs, per-slot shape identity).
  3.  Resolve stable target slide in template deck.
  4.  Resolve stable target slide in generated deck.
  5.  Build deterministic K1..Kn slot key mapping.
  5b. Read live generated geometry (actual shape positions in generated PPTX).
  5c. Verify generated PPTX content matches draft assignments (before Vision).
  6.  Render generated slide → generated_render_path.
  7.  Render template reference slide → template_render_path.
  8.  Create K-key overlay (using live generated geometry) → overlay_render_path.
  9.  Collect native deterministic checks.
  10. Build compact slot specs for Vision (with live generated_geometry).
  11. Invoke Vision reviewer exactly once (no retry).
  12. Validate slot key refs in issues against K mapping.
  13. Compute average_score arithmetically.
  14. Build and return VisualQAResult.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from slidestein.drafting.models import SlotDraftAction
from slidestein.drafting.service import build_slot_key_mapping
from slidestein.drafting.validation import validate_draft_slot_map_identity
from slidestein.qa.errors import LiveGeometryError, VisualQAError
from slidestein.qa.models import (
    VisualQARequest,
    VisualQAResult,
)
from slidestein.qa.overlay import read_live_slot_geometries
from slidestein.qa.reviewer import (
    NativeInspectorProtocol,
    OverlayBuilder,
    SlideRenderer,
    VisualQAReviewer,
)
from slidestein.writeback.errors import PowerPointWritebackError
from slidestein.writeback.preflight import resolve_slide_by_stable_id
from slidestein.writeback.verification import read_shape_text
from slidestein.writeback.com_writer import normalize_readback

if TYPE_CHECKING:
    pass


class VisualQAService:
    def __init__(
        self,
        reviewer: VisualQAReviewer,
        renderer: SlideRenderer,
        overlay_builder: OverlayBuilder,
        native_inspector: NativeInspectorProtocol,
    ) -> None:
        self._reviewer = reviewer
        self._renderer = renderer
        self._overlay_builder = overlay_builder
        self._native_inspector = native_inspector

    def review(
        self,
        request: VisualQARequest,
        artifacts_dir: Path,
    ) -> VisualQAResult:
        # ------------------------------------------------------------------
        # Step 1 — Validate completeness
        # ------------------------------------------------------------------
        if not request.draft.is_complete:
            raise VisualQAError(
                "Draft is not complete (is_complete=False). "
                "Visual QA requires a fully complete draft with no NEEDS_INPUT assignments."
            )

        for a in request.draft.assignments:
            if a.action == SlotDraftAction.NEEDS_INPUT:
                raise VisualQAError(
                    f"Draft assignment for slot_id {a.slot_id!r} has "
                    "action=needs_input. Visual QA requires all assignments to be "
                    "replace or clear."
                )

        # ------------------------------------------------------------------
        # Step 2 — Validate draft ↔ slot-map identity
        # ------------------------------------------------------------------
        validate_draft_slot_map_identity(
            request.draft,
            request.slot_map,
            VisualQAError,
        )

        draft = request.draft
        slot_map = request.slot_map

        # ------------------------------------------------------------------
        # Step 3 — Resolve stable slide in template deck
        # ------------------------------------------------------------------
        if not slot_map.deck_id:
            raise VisualQAError(
                f"slot_map.deck_id is not set for slide {slot_map.slide_id!r}. "
                "deck_id is required for stable slide targeting."
            )

        try:
            template_slide_number, _template_native_id = resolve_slide_by_stable_id(
                request.template_pptx,
                slot_map.deck_id,
                slot_map.slide_id,
            )
        except PowerPointWritebackError as exc:
            raise VisualQAError(
                f"Cannot resolve slide in template PPTX: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 4 — Resolve stable slide in generated deck
        # ------------------------------------------------------------------
        try:
            generated_slide_number, _gen_native_id = resolve_slide_by_stable_id(
                request.generated_pptx,
                slot_map.deck_id,
                slot_map.slide_id,
            )
        except PowerPointWritebackError as exc:
            raise VisualQAError(
                f"Cannot resolve slide in generated PPTX: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 5 — Build deterministic K1..Kn mapping
        # ------------------------------------------------------------------
        slot_key_map = build_slot_key_mapping(slot_map.slots)

        # ------------------------------------------------------------------
        # Step 5b — Read live generated geometry
        # ------------------------------------------------------------------
        try:
            live_geometries = read_live_slot_geometries(
                request.generated_pptx, generated_slide_number, slot_key_map
            )
        except LiveGeometryError as exc:
            raise VisualQAError(
                f"Cannot read live geometry from generated PPTX: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 5c — Verify generated PPTX content matches draft
        # ------------------------------------------------------------------
        assignments_by_slot_id = {a.slot_id: a for a in draft.assignments}
        for key, slot in slot_key_map.items():
            assignment = assignments_by_slot_id[slot.slot_id]
            if assignment.action == SlotDraftAction.NEEDS_INPUT:
                # Already blocked in Step 1; defensive only
                continue

            actual_text = read_shape_text(
                request.generated_pptx, generated_slide_number, slot.shape_path
            )

            if assignment.action == SlotDraftAction.REPLACE:
                expected = normalize_readback(assignment.text or "")
                if actual_text is None:
                    raise VisualQAError(
                        f"Content verification failed for {key} (slot_id={slot.slot_id!r}, "
                        f"shape_path={slot.shape_path!r}): shape not found or has no text frame "
                        "in generated PPTX — PPTX does not correspond to the supplied draft."
                    )
                if normalize_readback(actual_text) != expected:
                    raise VisualQAError(
                        f"Content verification failed for {key} (slot_id={slot.slot_id!r}): "
                        f"generated PPTX text does not match draft assignment. "
                        "Generated PPTX does not correspond to the supplied draft."
                    )
            elif assignment.action == SlotDraftAction.CLEAR:
                if actual_text is None:
                    raise VisualQAError(
                        f"Content verification failed for {key} (slot_id={slot.slot_id!r}, "
                        f"shape_path={slot.shape_path!r}): shape not found or has no text "
                        "frame in generated PPTX. A missing shape is never a successful CLEAR."
                    )
                if normalize_readback(actual_text) != "":
                    raise VisualQAError(
                        f"Content verification failed for {key} (slot_id={slot.slot_id!r}, "
                        f"shape_path={slot.shape_path!r}): slot is marked CLEAR but "
                        "generated PPTX contains non-empty text — "
                        "PPTX does not correspond to the supplied draft."
                    )

        # ------------------------------------------------------------------
        # Step 6 — Render generated slide
        # ------------------------------------------------------------------
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        generated_render_path = artifacts_dir / "generated.png"
        try:
            self._renderer.render(
                request.generated_pptx, generated_slide_number, generated_render_path
            )
        except Exception as exc:
            raise VisualQAError(
                f"Failed to render generated slide: {type(exc).__name__}: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 7 — Render template reference slide
        # ------------------------------------------------------------------
        template_render_path = artifacts_dir / "template.png"
        try:
            self._renderer.render(
                request.template_pptx, template_slide_number, template_render_path
            )
        except Exception as exc:
            raise VisualQAError(
                f"Failed to render template slide: {type(exc).__name__}: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 8 — Create K-key overlay using LIVE generated geometry
        # ------------------------------------------------------------------
        overlay_render_path = artifacts_dir / "overlay.png"
        try:
            self._overlay_builder.build(
                generated_render_path, overlay_render_path, live_geometries
            )
        except Exception as exc:
            raise VisualQAError(
                f"Failed to create K-key overlay: {type(exc).__name__}: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 9 — Collect native deterministic checks
        # ------------------------------------------------------------------
        try:
            native_checks = self._native_inspector.inspect(
                request.generated_pptx,
                generated_slide_number,
                slot_key_map,
                slot_map,
            )
        except Exception as exc:
            raise VisualQAError(
                f"Native inspection failed: {type(exc).__name__}: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Step 10 — Build compact slot specs for Vision
        # ------------------------------------------------------------------
        slot_specs: list[dict] = []
        for key, slot in slot_key_map.items():
            assignment = assignments_by_slot_id[slot.slot_id]
            live_geo = live_geometries.get(key, {})
            spec: dict = {
                "key": key,
                "role": slot.slot_role.value,
                "semantic_label": slot.semantic_label,
                "action": assignment.action.value,
                "generated_geometry": {
                    "x_ratio": live_geo.get("x_ratio", 0.0),
                    "y_ratio": live_geo.get("y_ratio", 0.0),
                    "width_ratio": live_geo.get("width_ratio", 0.0),
                    "height_ratio": live_geo.get("height_ratio", 0.0),
                },
            }
            # Include text only for replace actions; do NOT send historical current_text
            if assignment.action == SlotDraftAction.REPLACE:
                spec["final_text"] = assignment.text or ""
                spec["capacity_utilization"] = assignment.capacity_utilization
            slot_specs.append(spec)

        # Serialize native checks for Vision (dict representation)
        native_checks_dicts = [
            {
                "check_type": chk.check_type.value,
                "slot_key": chk.slot_key,
                "status": chk.status.value,
                "details": chk.details,
            }
            for chk in native_checks
        ]

        # ------------------------------------------------------------------
        # Step 11 — Invoke Vision reviewer exactly once
        # ------------------------------------------------------------------
        model_output = self._reviewer.review(
            generated_image=generated_render_path,
            template_image=template_render_path,
            overlay_image=overlay_render_path,
            slot_specs=slot_specs,
            native_checks=native_checks_dicts,
        )

        # ------------------------------------------------------------------
        # Step 12 — Validate slot key refs in issues
        # ------------------------------------------------------------------
        for issue in model_output.issues:
            seen_keys: set[str] = set()
            for k in issue.slot_keys:
                if k not in slot_key_map:
                    raise VisualQAError(
                        f"Issue references unknown slot key {k!r}. "
                        f"Valid keys: {sorted(slot_key_map.keys())}"
                    )
                if k in seen_keys:
                    raise VisualQAError(
                        f"Issue contains duplicate slot key {k!r} in slot_keys list"
                    )
                seen_keys.add(k)

        # ------------------------------------------------------------------
        # Step 13 — Compute average_score arithmetically
        # ------------------------------------------------------------------
        scores = [
            model_output.text_fit_and_clipping.score,
            model_output.visual_hierarchy.score,
            model_output.alignment_and_spacing.score,
            model_output.balance_and_whitespace.score,
            model_output.typography_and_style_consistency.score,
            model_output.overall_readability.score,
        ]
        average_score = round(sum(scores) / 6, 4)

        # ------------------------------------------------------------------
        # Step 14 — Build and return VisualQAResult
        # ------------------------------------------------------------------
        return VisualQAResult(
            slide_id=draft.slide_id,
            deck_id=draft.deck_id,
            slide_number=draft.slide_number,
            resolved_generated_slide_number=generated_slide_number,
            recommendation=model_output.recommendation,
            text_fit_and_clipping=model_output.text_fit_and_clipping,
            visual_hierarchy=model_output.visual_hierarchy,
            alignment_and_spacing=model_output.alignment_and_spacing,
            balance_and_whitespace=model_output.balance_and_whitespace,
            typography_and_style_consistency=model_output.typography_and_style_consistency,
            overall_readability=model_output.overall_readability,
            average_score=average_score,
            native_checks=native_checks,
            issues=model_output.issues,
            executive_summary=model_output.executive_summary,
            generated_render_path=str(generated_render_path),
            template_render_path=str(template_render_path),
            overlay_render_path=str(overlay_render_path),
        )
