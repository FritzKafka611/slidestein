"""StructuralRecoveryOrchestrator — M10 bounded structural recovery.

Accepts only requests escalated from M9 with route=template_reselection.
Performs one structural recovery action (rebuild OR reselect) and STOPS.

API call budget (per recovery cycle):
  rebuild_current_template:  M6=0 provider calls + M8=1 Vision call → max 1
  reselect_template:         embedding=1 + selection=1 + drafting=1 + M7=1 + M8=1 → max 5

Provider-boundary contract (mirrors M9):
  model_calls counter is incremented IMMEDIATELY BEFORE the first EXTERNAL
  provider/API request is issued.  All deterministic pre-provider work (prompt
  assembly, candidate filtering, preflight) is performed BEFORE incrementing.

  selector.preflight() → deterministic, zero external calls
  model_calls["template_selection"] += 1
  selector.select_prepared()         → exactly one external Vision call

  A failure DURING preflight does NOT increment template_selection.
  A failure DURING select_prepared increments template_selection = 1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from slidestein.drafting.service import build_slot_key_mapping
from slidestein.drafting.validation import validate_draft_slot_map_identity
from slidestein.revision.models import RevisionRoute
from slidestein.slots.models import TemplateSlotMap
from slidestein.slots.versions import SLOT_MAP_SCHEMA_VERSION
from slidestein.structural.diagnosis import StructuralDiagnosisService
from slidestein.structural.errors import (
    StructuralRecoveryError,
    StructuralRecoveryExecutionError,
)
from slidestein.structural.fingerprint import (
    compute_structural_fingerprint,
    compute_structural_fingerprint_from_slot_map,
    compute_structural_fingerprint_slide_space,
)
from slidestein.structural.models import (
    CandidateReference,
    StructuralCandidateEligibility,
    StructuralCandidateInfo,
    StructuralRecoveryPlan,
    StructuralRecoveryResult,
    StructuralRecoveryRoute,
)
from slidestein.structural.versions import (
    STRUCTURAL_RECOVERY_POLICY_VERSION,
    STRUCTURAL_RECOVERY_PROMPT_VERSION,
    STRUCTURAL_RECOVERY_SCHEMA_VERSION,
)

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.drafting.models import SlideContentDraft, SlotDraftAction
    from slidestein.qa.models import VisualQAResult
    from slidestein.qa.reviewer import OverlayBuilder, SlideRenderer
    from slidestein.qa.service import VisualQAService
    from slidestein.retrieval.hybrid import HybridSlideSearch
    from slidestein.retrieval.store import SlideVectorStore
    from slidestein.review.models import ManagerReviewResult
    from slidestein.review.service import ManagerReviewService
    from slidestein.structural.models import StructuralRecoveryRequest
    from slidestein.structural.selector import StructuralTemplateSelector

_log = logging.getLogger(__name__)

# Candidate counts — spec: retrieve 8, Vision receives at most 5
_RETRIEVAL_TOP_K = 8
_VISION_CANDIDATE_LIMIT = 5


class StructuralRecoveryOrchestrator:
    """Bounded structural recovery — one cycle maximum.

    Parameters
    ----------
    searcher:       HybridSlideSearch for candidate retrieval.
    library:        SlideLibrary for record + slot_map lookup and preview paths.
    selector:       StructuralTemplateSelector (Vision-based, SAP AI Core only).
    drafting_service:  SlideContentDraftService (M5.3).
    writeback_service: PowerPointWritebackService (M6) — injected, not instantiated internally.
    manager_review_service: ManagerReviewService (M7).
    visual_qa_service:      VisualQAService (M8).
    renderer:       SlideRenderer for rendering candidate slides.
    diagnosis_service: StructuralDiagnosisService (deterministic, 0 calls).
    """

    def __init__(
        self,
        searcher: "HybridSlideSearch",
        library: object,
        selector: "StructuralTemplateSelector",
        drafting_service: object,
        writeback_service: object,
        manager_review_service: "ManagerReviewService",
        visual_qa_service: "VisualQAService",
        renderer: "SlideRenderer",
        diagnosis_service: Optional[StructuralDiagnosisService] = None,
    ) -> None:
        self._searcher = searcher
        self._library = library
        self._selector = selector
        self._drafting_service = drafting_service
        self._writeback_service = writeback_service
        self._manager_review_service = manager_review_service
        self._visual_qa_service = visual_qa_service
        self._renderer = renderer
        self._diagnosis = diagnosis_service or StructuralDiagnosisService()

    def recover(
        self,
        request: "StructuralRecoveryRequest",
        artifacts_dir: Path,
    ) -> StructuralRecoveryResult:
        """Execute one bounded structural recovery cycle.

        Returns StructuralRecoveryResult.  Raises StructuralRecoveryError only
        for hard pre-provider contract violations (input validation).
        """
        model_calls: dict = {
            "retrieval_embedding": 0,
            "template_selection": 0,
            "drafting": 0,
            "manager_review": 0,
            "visual_qa": 0,
        }

        # ----------------------------------------------------------------
        # Step 1 — Input contract validation (all StructuralRecoveryError)
        # ----------------------------------------------------------------
        self._validate_input_contract(request)

        # ----------------------------------------------------------------
        # Step 2 — Structural diagnosis (includes content identity check)
        # ----------------------------------------------------------------
        plan = self._diagnosis.diagnose(request)

        # ----------------------------------------------------------------
        # Step 3 — Execute route
        # ----------------------------------------------------------------
        if plan.route == StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE:
            return self._execute_rebuild(request, plan, artifacts_dir, model_calls)

        if plan.route == StructuralRecoveryRoute.RESELECT_TEMPLATE:
            return self._execute_reselect(request, plan, artifacts_dir, model_calls)

        # MANUAL_REVIEW
        return StructuralRecoveryResult(
            route=StructuralRecoveryRoute.MANUAL_REVIEW,
            status="escalation_required",
            slide_id=request.current_slot_map.slide_id,
            deck_id=request.current_slot_map.deck_id,
            slide_number=request.current_slot_map.slide_number,
            plan=plan,
            content_changed=False,
            manager_review_effective=request.manager_review,
            final_ready=False,
            model_calls=model_calls,
        )

    # ------------------------------------------------------------------
    # Rebuild current template
    # ------------------------------------------------------------------

    def _execute_rebuild(
        self,
        request: "StructuralRecoveryRequest",
        plan: StructuralRecoveryPlan,
        artifacts_dir: Path,
        model_calls: dict,
    ) -> StructuralRecoveryResult:
        """Rebuild from original template using the same draft and slot map.

        M7: NOT rerun (content unchanged).
        M8: Run exactly once.

        Uses the injected writeback_service — does NOT instantiate internally.
        """
        from slidestein.qa.models import VisualQARequest  # noqa: PLC0415
        from slidestein.writeback.models import PowerPointWritebackRequest  # noqa: PLC0415

        output_pptx = request.output_pptx
        if output_pptx is None:
            raise StructuralRecoveryError(
                "rebuild_current_template requires output_pptx to be specified."
            )

        if output_pptx.exists() and not request.overwrite:
            raise StructuralRecoveryError(
                f"output_pptx already exists and overwrite=False: {output_pptx}"
            )

        # M6 — rebuild from original template using injected service
        wb_request = PowerPointWritebackRequest(
            draft=request.current_draft,
            slot_map=request.current_slot_map,
            source_pptx=request.template_pptx,
            output_pptx=output_pptx,
            overwrite=request.overwrite,
        )
        try:
            wb_plan = self._writeback_service.preflight(wb_request)  # type: ignore[union-attr]
            writeback_result = self._writeback_service.apply(wb_plan)  # type: ignore[union-attr]
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"M6 rebuild writeback failed: {type(exc).__name__}",
                stage="writeback",
                model_calls=model_calls,
            ) from exc

        # M8 — visual QA on rebuilt slide (1 Vision call)
        qa_artifacts = artifacts_dir / "rebuild"
        qa_artifacts.mkdir(parents=True, exist_ok=True)
        qa_request = VisualQARequest(
            template_pptx=request.template_pptx,
            generated_pptx=output_pptx,
            draft=request.current_draft,
            slot_map=request.current_slot_map,
        )
        model_calls["visual_qa"] += 1
        try:
            visual_qa_after = self._visual_qa_service.review(qa_request, qa_artifacts)
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"M8 visual QA after rebuild failed: {type(exc).__name__}",
                stage="visual_qa",
                model_calls=model_calls,
            ) from exc

        # final_ready: existing M7 approve AND new M8 pass
        final_ready = (
            request.manager_review.recommendation == "approve"
            and visual_qa_after.recommendation == "pass"
        )

        return StructuralRecoveryResult(
            route=StructuralRecoveryRoute.REBUILD_CURRENT_TEMPLATE,
            status="rebuilt",
            slide_id=request.current_slot_map.slide_id,
            deck_id=request.current_slot_map.deck_id,
            slide_number=request.current_slot_map.slide_number,
            plan=plan,
            content_changed=False,
            writeback_result=writeback_result,
            manager_review_after=None,
            manager_review_effective=request.manager_review,
            visual_qa_after=visual_qa_after,
            final_ready=final_ready,
            output_pptx=output_pptx,
            model_calls=model_calls,
        )

    # ------------------------------------------------------------------
    # Reselect template
    # ------------------------------------------------------------------

    def _execute_reselect(
        self,
        request: "StructuralRecoveryRequest",
        plan: StructuralRecoveryPlan,
        artifacts_dir: Path,
        model_calls: dict,
    ) -> StructuralRecoveryResult:
        """Retrieve + select + redraft + M6 + M7 + M8.  One cycle, then STOP.

        Uses the injected writeback_service — does NOT instantiate internally.
        """
        from slidestein.qa.models import VisualQARequest  # noqa: PLC0415
        from slidestein.review.models import ManagerReviewRequest  # noqa: PLC0415
        from slidestein.retrieval.request import SlideRetrievalRequest  # noqa: PLC0415
        from slidestein.writeback.models import PowerPointWritebackRequest  # noqa: PLC0415

        brief = request.brief

        # ---- Step R1: Retrieval (1 embedding call) ----
        retrieval_request = self._build_retrieval_request(brief)
        model_calls["retrieval_embedding"] += 1
        try:
            hybrid_results = self._searcher.search(retrieval_request)
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"Hybrid retrieval failed: {type(exc).__name__}",
                stage="retrieval",
                model_calls=model_calls,
            ) from exc

        # ---- Step R2: Filter candidates deterministically ----
        slot_key_map_current = build_slot_key_mapping(request.current_slot_map.slots)
        current_fp = compute_structural_fingerprint_slide_space(
            request.template_pptx,
            request.current_slot_map.slide_number,
            slot_key_map_current,
        )
        (
            candidates_info,
            candidate_slot_maps,
            candidate_records,
            eligibility_records,
            cand_key_to_log_idx,
        ) = self._filter_candidates(
            hybrid_results=hybrid_results,
            current_slide_id=request.current_slot_map.slide_id,
            current_structural_fingerprint=current_fp,
            limit=_VISION_CANDIDATE_LIMIT,
        )

        if not candidates_info:
            _log.warning("No viable candidates after filtering — blocked.")
            return StructuralRecoveryResult(
                route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
                status="blocked",
                slide_id=request.current_slot_map.slide_id,
                deck_id=request.current_slot_map.deck_id,
                slide_number=request.current_slot_map.slide_number,
                plan=plan,
                content_changed=False,
                manager_review_effective=request.manager_review,
                final_ready=False,
                model_calls=model_calls,
                candidate_eligibility_log=eligibility_records,
            )

        # ---- Step R3: Render — current template FIRST (mandatory evidence) ----
        candidate_renders = artifacts_dir / "candidates"
        candidate_renders.mkdir(parents=True, exist_ok=True)

        # Req 6: current template render is mandatory for comparative selection
        current_template_image = self._render_current_template(
            request, candidate_renders
        )
        if current_template_image is None:
            _log.warning(
                "Current template render failed — blocked before selector."
                " Reason: current_template_render_failed"
            )
            return StructuralRecoveryResult(
                route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
                status="blocked",
                slide_id=request.current_slot_map.slide_id,
                deck_id=request.current_slot_map.deck_id,
                slide_number=request.current_slot_map.slide_number,
                plan=plan,
                content_changed=False,
                manager_review_effective=request.manager_review,
                final_ready=False,
                model_calls=model_calls,
                candidate_eligibility_log=eligibility_records,
            )

        # Render candidate images
        rendered_images = self._render_candidates(
            candidates_info, candidate_records, candidate_renders
        )

        # Update eligibility records with render outcomes (one record per candidate)
        for cand in candidates_info:
            success = rendered_images.get(cand.candidate_key) is not None
            idx = cand_key_to_log_idx.get(cand.candidate_key)
            if idx is not None:
                eligibility_records[idx].rendered_successfully = success
                if not success:
                    eligibility_records[idx].eligible = False
                    eligibility_records[idx].exclusion_reason = "render_failed"

        # Filter to renderable candidates only
        renderable_candidates_info = [
            c for c in candidates_info
            if rendered_images.get(c.candidate_key) is not None
        ]
        renderable_candidate_keys = {c.candidate_key for c in renderable_candidates_info}

        if not renderable_candidates_info:
            _log.warning("No renderable candidates — blocked before selector.")
            return StructuralRecoveryResult(
                route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
                status="blocked",
                slide_id=request.current_slot_map.slide_id,
                deck_id=request.current_slot_map.deck_id,
                slide_number=request.current_slot_map.slide_number,
                plan=plan,
                content_changed=False,
                manager_review_effective=request.manager_review,
                final_ready=False,
                model_calls=model_calls,
                candidate_eligibility_log=eligibility_records,
            )

        # Filter candidate maps consistently
        renderable_slot_maps = {k: v for k, v in candidate_slot_maps.items()
                                if k in renderable_candidate_keys}
        renderable_records = {k: v for k, v in candidate_records.items()
                              if k in renderable_candidate_keys}

        # ---- Step R4: Template selection preflight (deterministic) ----
        structural_issues = [
            iss for iss in request.visual_qa.issues
            if iss.category in (
                "visual_hierarchy",
                "alignment_and_spacing",
                "balance_and_whitespace",
                "typography_and_style_consistency",
            )
        ]
        try:
            selection_preflight = self._selector.preflight(
                brief=brief,
                structural_issues=structural_issues,
                candidates=renderable_candidates_info,
                current_slide_id=request.current_slot_map.slide_id,
                rendered_images=rendered_images,
                current_template_image=current_template_image,
            )
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"Template selection preflight failed: {type(exc).__name__}",
                stage="template_selection",
                model_calls=model_calls,
            ) from exc

        # ---- template_selection counter incremented HERE (before external call) ----
        valid_keys = {c.candidate_key for c in renderable_candidates_info}
        model_calls["template_selection"] += 1
        try:
            selection_output = self._selector.select_prepared(
                preflight=selection_preflight,
                valid_keys=valid_keys,
            )
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"Template selection failed: {type(exc).__name__}",
                stage="template_selection",
                model_calls=model_calls,
            ) from exc

        selected_key = selection_output.selected_candidate_key
        selected_info = next(
            (c for c in renderable_candidates_info if c.candidate_key == selected_key), None
        )
        if selected_info is None:
            raise StructuralRecoveryExecutionError(
                f"Selector returned key not in renderable candidates.",
                stage="template_selection",
                model_calls=model_calls,
            )

        selected_slot_map = renderable_slot_maps[selected_key]
        selected_record = renderable_records[selected_key]

        candidate_ref = CandidateReference(
            candidate_key=selected_key,
            slide_id=selected_info.slide_id,
            deck_id=selected_info.deck_id,
            slide_number=selected_info.slide_number,
            hybrid_rank=next(
                (r.rank for r in hybrid_results if r.slide_id == selected_info.slide_id), 0
            ),
            structural_fingerprint=selected_info.structural_fingerprint,
        )

        # ---- Step R5: Redraft from source material (1 text call) ----
        model_calls["drafting"] += 1
        try:
            alternate_draft = self._drafting_service.draft(  # type: ignore[attr-defined]
                brief=brief,
                slot_map=selected_slot_map,
                source_material=request.source_material,
            )
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"Alternate draft failed: {type(exc).__name__}",
                stage="drafting",
                model_calls=model_calls,
            ) from exc

        if not alternate_draft.is_complete:
            _log.warning("Alternate draft is_complete=False — blocked.")
            return StructuralRecoveryResult(
                route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
                status="blocked",
                slide_id=request.current_slot_map.slide_id,
                deck_id=request.current_slot_map.deck_id,
                slide_number=request.current_slot_map.slide_number,
                plan=plan,
                content_changed=True,
                selected_candidate=candidate_ref,
                selected_slot_map=selected_slot_map,
                selected_draft=alternate_draft,
                manager_review_effective=request.manager_review,
                final_ready=False,
                model_calls=model_calls,
                candidate_eligibility_log=eligibility_records,
            )

        # Check for NEEDS_INPUT assignments
        from slidestein.drafting.models import SlotDraftAction  # noqa: PLC0415
        if any(a.action == SlotDraftAction.NEEDS_INPUT for a in alternate_draft.assignments):
            _log.warning("Alternate draft has NEEDS_INPUT assignments — blocked.")
            return StructuralRecoveryResult(
                route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
                status="blocked",
                slide_id=request.current_slot_map.slide_id,
                deck_id=request.current_slot_map.deck_id,
                slide_number=request.current_slot_map.slide_number,
                plan=plan,
                content_changed=True,
                selected_candidate=candidate_ref,
                selected_slot_map=selected_slot_map,
                selected_draft=alternate_draft,
                manager_review_effective=request.manager_review,
                final_ready=False,
                model_calls=model_calls,
                candidate_eligibility_log=eligibility_records,
            )

        # ---- Step R6: M6 writeback using injected service ----
        output_pptx = request.output_pptx
        if output_pptx is None:
            raise StructuralRecoveryError(
                "reselect_template requires output_pptx to be specified."
            )
        if output_pptx.exists() and not request.overwrite:
            raise StructuralRecoveryError(
                f"output_pptx already exists and overwrite=False: {output_pptx}"
            )

        selected_source_pptx = Path(selected_record.source_deck_path)  # type: ignore[union-attr]
        wb_request = PowerPointWritebackRequest(
            draft=alternate_draft,
            slot_map=selected_slot_map,
            source_pptx=selected_source_pptx,
            output_pptx=output_pptx,
            overwrite=request.overwrite,
        )
        try:
            wb_plan = self._writeback_service.preflight(wb_request)  # type: ignore[union-attr]
            writeback_result = self._writeback_service.apply(wb_plan)  # type: ignore[union-attr]
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"M6 alternate writeback failed: {type(exc).__name__}",
                stage="writeback",
                model_calls=model_calls,
            ) from exc

        # ---- Step R7: M7 manager review (content newly drafted → required) ----
        from slidestein.review.models import ManagerReviewRequest  # noqa: PLC0415
        m7_request = ManagerReviewRequest(
            brief=brief,
            draft=alternate_draft,
            slot_map=selected_slot_map,
            source_material=request.source_material,
        )
        model_calls["manager_review"] += 1
        try:
            manager_review_after = self._manager_review_service.review(m7_request)
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"M7 manager review after reselection failed: {type(exc).__name__}",
                stage="manager_review",
                model_calls=model_calls,
            ) from exc

        # ---- Step R8: M8 visual QA on selected alternate ----
        qa_artifacts = artifacts_dir / "reselect"
        qa_artifacts.mkdir(parents=True, exist_ok=True)
        qa_request = VisualQARequest(
            template_pptx=selected_source_pptx,
            generated_pptx=output_pptx,
            draft=alternate_draft,
            slot_map=selected_slot_map,
        )
        model_calls["visual_qa"] += 1
        try:
            visual_qa_after = self._visual_qa_service.review(qa_request, qa_artifacts)
        except Exception as exc:
            raise StructuralRecoveryExecutionError(
                f"M8 visual QA after reselection failed: {type(exc).__name__}",
                stage="visual_qa",
                model_calls=model_calls,
            ) from exc

        # ---- STOP after M8 ----
        final_ready = (
            manager_review_after.recommendation == "approve"
            and visual_qa_after.recommendation == "pass"
        )

        return StructuralRecoveryResult(
            route=StructuralRecoveryRoute.RESELECT_TEMPLATE,
            status="reselected",
            slide_id=request.current_slot_map.slide_id,
            deck_id=request.current_slot_map.deck_id,
            slide_number=request.current_slot_map.slide_number,
            plan=plan,
            content_changed=True,
            selected_candidate=candidate_ref,
            selected_slot_map=selected_slot_map,
            selected_draft=alternate_draft,
            writeback_result=writeback_result,
            manager_review_after=manager_review_after,
            manager_review_effective=manager_review_after,
            visual_qa_after=visual_qa_after,
            final_ready=final_ready,
            output_pptx=output_pptx,
            model_calls=model_calls,
            candidate_eligibility_log=eligibility_records,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_input_contract(request: "StructuralRecoveryRequest") -> None:
        """Validate all input contracts.  Raises StructuralRecoveryError on failure."""
        # M9 route must be template_reselection
        if request.m9_plan.route != RevisionRoute.TEMPLATE_RESELECTION:
            raise StructuralRecoveryError(
                f"M10 only accepts M9 escalations with route=template_reselection. "
                f"Got: {request.m9_plan.route.value!r}."
            )

        draft = request.current_draft
        slot_map = request.current_slot_map

        # Draft / slot_map identity
        validate_draft_slot_map_identity(draft, slot_map, StructuralRecoveryError)

        # Brief ↔ draft key_message
        if request.brief.key_message != draft.brief_key_message:
            raise StructuralRecoveryError(
                f"brief.key_message {request.brief.key_message!r} does not match "
                f"current_draft.brief_key_message {draft.brief_key_message!r}."
            )

        # Manager review identity
        if request.manager_review.slide_id != draft.slide_id:
            raise StructuralRecoveryError(
                f"manager_review.slide_id {request.manager_review.slide_id!r} != "
                f"draft.slide_id {draft.slide_id!r}."
            )
        if (
            request.manager_review.deck_id is not None
            and draft.deck_id is not None
            and request.manager_review.deck_id != draft.deck_id
        ):
            raise StructuralRecoveryError(
                f"manager_review.deck_id {request.manager_review.deck_id!r} != "
                f"draft.deck_id {draft.deck_id!r}."
            )
        if request.manager_review.slide_number != draft.slide_number:
            raise StructuralRecoveryError(
                f"manager_review.slide_number {request.manager_review.slide_number} != "
                f"draft.slide_number {draft.slide_number}."
            )

        # Visual QA identity
        if request.visual_qa.slide_id != draft.slide_id:
            raise StructuralRecoveryError(
                f"visual_qa.slide_id {request.visual_qa.slide_id!r} != "
                f"draft.slide_id {draft.slide_id!r}."
            )
        if (
            request.visual_qa.deck_id is not None
            and draft.deck_id is not None
            and request.visual_qa.deck_id != draft.deck_id
        ):
            raise StructuralRecoveryError(
                f"visual_qa.deck_id {request.visual_qa.deck_id!r} != "
                f"draft.deck_id {draft.deck_id!r}."
            )
        if request.visual_qa.slide_number != draft.slide_number:
            raise StructuralRecoveryError(
                f"visual_qa.slide_number {request.visual_qa.slide_number} != "
                f"draft.slide_number {draft.slide_number}."
            )

        # M9 plan identity
        if request.m9_plan.slide_id != draft.slide_id:
            raise StructuralRecoveryError(
                f"m9_plan.slide_id {request.m9_plan.slide_id!r} != "
                f"draft.slide_id {draft.slide_id!r}."
            )
        if (
            request.m9_plan.deck_id is not None
            and draft.deck_id is not None
            and request.m9_plan.deck_id != draft.deck_id
        ):
            raise StructuralRecoveryError(
                f"m9_plan.deck_id {request.m9_plan.deck_id!r} != "
                f"draft.deck_id {draft.deck_id!r}."
            )
        if request.m9_plan.slide_number != draft.slide_number:
            raise StructuralRecoveryError(
                f"m9_plan.slide_number {request.m9_plan.slide_number} != "
                f"draft.slide_number {draft.slide_number}."
            )

        # Draft completeness
        if not draft.is_complete:
            raise StructuralRecoveryError(
                "current_draft.is_complete must be True for structural recovery."
            )

        from slidestein.drafting.models import SlotDraftAction  # noqa: PLC0415
        for a in draft.assignments:
            if a.action == SlotDraftAction.NEEDS_INPUT:
                raise StructuralRecoveryError(
                    f"current_draft has NEEDS_INPUT assignment for "
                    f"slot_id={a.slot_id!r}. Structural recovery requires a "
                    "fully complete draft."
                )

        # File existence
        if not request.template_pptx.exists() or not request.template_pptx.is_file():
            raise StructuralRecoveryError(
                f"template_pptx not found or not a file: {request.template_pptx}"
            )
        if not request.generated_pptx.exists() or not request.generated_pptx.is_file():
            raise StructuralRecoveryError(
                f"generated_pptx not found or not a file: {request.generated_pptx}"
            )

    def _build_retrieval_request(self, brief: "ConsultingSlideBrief"):
        from slidestein.retrieval.request import SlideRetrievalRequest  # noqa: PLC0415

        return SlideRetrievalRequest(
            query_text=brief.key_message,
            slide_function=brief.slide_function,
            primary_communication_job=brief.primary_communication_job,
            preferred_visual_archetypes=list(brief.preferred_visual_archetypes or []),
            storyline_roles=list(brief.storyline_roles or []),
            density=getattr(brief, "density", None),
            required_content_elements=list(brief.required_content_elements or []),
            top_k=_RETRIEVAL_TOP_K,
        )

    def _filter_candidates(
        self,
        hybrid_results: list,
        current_slide_id: str,
        current_structural_fingerprint: str,
        limit: int,
    ) -> tuple[
        list[StructuralCandidateInfo],
        dict,
        dict,
        list[StructuralCandidateEligibility],
        dict[str, int],
    ]:
        """Filter hybrid results to eligible Vision candidates.

        Processes ALL retrieved results (no early break after limit).
        After limit eligible candidates are found, additional otherwise-eligible
        results are recorded with exclusion_reason="vision_candidate_limit".

        Candidate slot-map policy (M10 v1):
            Candidate templates must have an authoritative cached M5.2
            TemplateSlotMap in the library.  Candidates without a cached
            slot map are excluded with exclusion_reason="slot_map_unavailable".
            This is a deliberate zero-provider-call policy for M10.

        Returns:
            candidates_info         — eligible Vision candidates (max limit)
            candidate_slot_maps     — slot map per candidate_key
            candidate_records       — library record per candidate_key
            eligibility_records     — one StructuralCandidateEligibility per result
            cand_key_to_log_idx     — candidate_key -> index in eligibility_records
                                      (for post-render update)
        """
        candidates_info: list[StructuralCandidateInfo] = []
        candidate_slot_maps: dict = {}
        candidate_records: dict = {}
        eligibility_records: list[StructuralCandidateEligibility] = []
        cand_key_to_log_idx: dict[str, int] = {}

        sc_index = 1
        for result in hybrid_results:  # process ALL — no break after limit
            slide_id = result.slide_id

            log_entry = StructuralCandidateEligibility(
                slide_id=slide_id,
                deck_id=getattr(result, "deck_id", None),
                slide_number=getattr(result, "slide_number", None),
                retrieval_rank=getattr(result, "rank", None),
                eligible=False,
            )

            # Exclude current selected template by stable slide_id
            if slide_id == current_slide_id:
                log_entry.exclusion_reason = "current_template"
                eligibility_records.append(log_entry)
                _log.debug("Excluded current template: %s", slide_id)
                continue

            # Get library record
            record = self._library.get_slide(slide_id)  # type: ignore[union-attr]
            if record is None:
                log_entry.exclusion_reason = "no_library_record"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (no library record): %s", slide_id)
                continue

            # Get slot map from library cache (M10 v1: cache required, 0 provider calls)
            slot_map = self._get_cached_slot_map(slide_id)
            log_entry.slot_map_available = (slot_map is not None)
            if slot_map is None:
                log_entry.exclusion_reason = "slot_map_unavailable"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (no cached slot map): %s", slide_id)
                continue

            # Check slot eligibility
            if not slot_map.slots:
                log_entry.exclusion_reason = "no_slots"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (no slots): %s", slide_id)
                continue

            slot_key_map_c = build_slot_key_mapping(slot_map.slots)

            has_title = any(s.slot_role.value == "title" for s in slot_map.slots)
            log_entry.title_slot_available = has_title
            if not has_title:
                log_entry.exclusion_reason = "no_title_slot"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (no title slot): %s", slide_id)
                continue

            editable_count = len([s for s in slot_map.slots if s.editable])
            log_entry.editable_semantic_slot_count = editable_count
            if editable_count < 1:
                log_entry.exclusion_reason = "no_editable_slots"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (no editable slots): %s", slide_id)
                continue

            # Structural fingerprint using slide-space geometry (falls back to
            # group-local if PPTX unreadable)
            fp = compute_structural_fingerprint_slide_space(
                Path(str(record.source_deck_path)),
                int(result.slide_number),
                slot_key_map_c,
            )
            log_entry.structural_fingerprint = fp
            if fp == current_structural_fingerprint:
                log_entry.exclusion_reason = "structural_clone"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (exact structural clone): %s", slide_id)
                continue

            # Vision candidate limit — record but do not add to Vision candidates
            if len(candidates_info) >= limit:
                log_entry.exclusion_reason = "vision_candidate_limit"
                eligibility_records.append(log_entry)
                _log.debug("Excluded (Vision candidate limit): %s", slide_id)
                continue

            # Eligible — assign candidate key
            candidate_key = f"SC{sc_index}"
            sc_index += 1

            slot_summary = self._build_slot_summary(slot_key_map_c)
            visual_archetype = self._get_visual_archetype(slide_id)

            log_entry.candidate_key = candidate_key
            log_entry.visual_archetype = visual_archetype
            log_entry.eligible = True

            log_idx = len(eligibility_records)
            eligibility_records.append(log_entry)
            cand_key_to_log_idx[candidate_key] = log_idx

            candidates_info.append(
                StructuralCandidateInfo(
                    candidate_key=candidate_key,
                    slide_id=slide_id,
                    deck_id=result.deck_id,
                    slide_number=result.slide_number,
                    has_title_slot=has_title,
                    editable_slot_count=editable_count,
                    slot_count=len(slot_map.slots),
                    slot_summary=slot_summary,
                    structural_fingerprint=fp,
                    visual_archetype=visual_archetype,
                )
            )
            candidate_slot_maps[candidate_key] = slot_map
            candidate_records[candidate_key] = record

        return (
            candidates_info,
            candidate_slot_maps,
            candidate_records,
            eligibility_records,
            cand_key_to_log_idx,
        )

    def _get_cached_slot_map(self, slide_id: str) -> Optional[TemplateSlotMap]:
        """Get a TemplateSlotMap from the library cache (0 Vision calls)."""
        result = self._library.get_slot_map(slide_id, SLOT_MAP_SCHEMA_VERSION)  # type: ignore[union-attr]
        if result is None:
            return None
        slot_map_json, _fp, _at = result
        try:
            return TemplateSlotMap.model_validate_json(slot_map_json)
        except Exception:
            return None

    def _get_visual_archetype(self, slide_id: str) -> str:
        """Best-effort visual archetype lookup (empty string if unavailable)."""
        try:
            from slidestein.classification.versions import CLASSIFICATION_VERSION  # noqa: PLC0415
            cls = self._library.get_classification(slide_id, CLASSIFICATION_VERSION)  # type: ignore[union-attr]
            if cls is not None and cls.profile is not None:
                arch = getattr(cls.profile, "visual_archetype", None)
                if arch:
                    return arch.value if hasattr(arch, "value") else str(arch)
        except Exception:
            pass
        return ""

    @staticmethod
    def _build_slot_summary(slot_key_map: dict) -> str:
        """Build a compact text description of the slot structure."""
        parts = []
        for key in sorted(slot_key_map.keys(), key=lambda k: int(k[1:])):
            slot = slot_key_map[key]
            role = slot.slot_role.value
            label = slot.semantic_label
            cap = slot.capacity.max_characters_estimate
            parts.append(f"{key} ({role}, {label!r}, cap={cap})")
        return "; ".join(parts)

    def _render_candidates(
        self,
        candidates_info: list[StructuralCandidateInfo],
        candidate_records: dict,
        render_dir: Path,
    ) -> dict:
        """Render each candidate slide → {candidate_key: Path}.

        A candidate that fails to render is excluded from the result dict
        (key absent).  Callers must filter candidates_info to match rendered keys.
        """
        rendered: dict = {}
        for cand in candidates_info:
            record = candidate_records[cand.candidate_key]
            out_path = render_dir / f"{cand.candidate_key}.png"

            # Use existing preview if available
            if record.preview_path and Path(record.preview_path).exists():
                rendered[cand.candidate_key] = Path(record.preview_path)
                continue

            # Render fresh
            try:
                source_pptx = Path(record.source_deck_path)
                self._renderer.render(source_pptx, cand.slide_number, out_path)
                rendered[cand.candidate_key] = out_path
            except Exception as exc:
                _log.warning(
                    "Could not render candidate %s (slide_id=%s): %s — excluded from selector.",
                    cand.candidate_key, cand.slide_id, type(exc).__name__
                )
                # Key intentionally absent — caller must filter

        return rendered

    def _render_current_template(
        self,
        request: "StructuralRecoveryRequest",
        render_dir: Path,
    ) -> Optional[Path]:
        """Render the current template slide for comparison reference.

        Returns None if the render fails — the selector contract must declare
        whether it can proceed without the current-template image.  If None
        is returned the caller must handle the missing-render policy.
        """
        try:
            from slidestein.writeback.preflight import resolve_slide_by_stable_id  # noqa: PLC0415
            from slidestein.writeback.errors import PowerPointWritebackError  # noqa: PLC0415

            slide_number, _ = resolve_slide_by_stable_id(
                request.template_pptx,
                request.current_slot_map.deck_id or "",
                request.current_slot_map.slide_id,
            )
            out_path = render_dir / "current_template.png"
            self._renderer.render(request.template_pptx, slide_number, out_path)
            return out_path
        except Exception as exc:
            _log.debug("Could not render current template: %s", type(exc).__name__)
            return None
