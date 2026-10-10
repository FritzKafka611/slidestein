"""M9 revision services (v1.1).

ContentRevisionService        — applies one content revision cycle (1 SAP text call)
BoundedRevisionOrchestrator   — routes, optionally revises, re-reviews, and stops
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from slidestein.drafting.models import SlotDraftAction, SlotDraftAssignment
from slidestein.drafting.service import build_slot_key_mapping, validate_text_capacity
from slidestein.revision.errors import RevisionError, RevisionExecutionError
from slidestein.revision.models import (
    ContentRevisionResult,
    RevisionCycleResult,
    RevisionRequest,
    RevisionRoute,
)
from slidestein.revision.router import RevisionRouter

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.drafting.models import SlideContentDraft
    from slidestein.qa.models import VisualQAResult
    from slidestein.qa.service import VisualQAService
    from slidestein.review.models import ManagerReviewResult
    from slidestein.review.service import ManagerReviewService
    from slidestein.revision.models import RevisionChange, RevisionPlan
    from slidestein.revision.reviser import ContentReviser
    from slidestein.slots.models import TemplateSlotMap
    from slidestein.writeback.models import PowerPointWritebackResult

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ContentRevisionPreflight
# ---------------------------------------------------------------------------


@dataclass
class ContentRevisionPreflight:
    """Deterministic pre-provider state for one content revision cycle.

    Produced by ContentRevisionService.preflight() — zero provider calls.
    Consumed by ContentRevisionService.execute() — one provider call.
    """

    brief: Any
    draft: Any
    source_material: Optional[str]
    slot_key_map: dict
    assignments_by_slot_id: dict
    slot_specs: list
    target_keys: list
    revision_feedback: list
    revision_plan: Any


# ---------------------------------------------------------------------------
# ContentRevisionService
# ---------------------------------------------------------------------------


class ContentRevisionService:
    """Apply one content revision patch to an existing draft.

    Call order:
      preflight(...)  — deterministic checks, zero provider calls.
                        Raises RevisionError on any failure.
      execute(pf)     — one SAP AI Core text call.
                        Caller must increment its attempt counter before calling.
      revise(...)     — convenience wrapper: preflight + execute in one call.

    Non-target slots are preserved exactly (verified by model_dump comparison).
    Capacity is validated after the patch for REPLACE changes.
    Returns ContentRevisionResult (status="revised" or status="blocked").
    """

    def __init__(self, reviser: "ContentReviser") -> None:
        self._reviser = reviser

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def revise(
        self,
        brief: "ConsultingSlideBrief",
        draft: "SlideContentDraft",
        slot_map: "TemplateSlotMap",
        source_material: Optional[str],
        revision_plan: "RevisionPlan",
        manager_review: Optional["ManagerReviewResult"] = None,
        visual_qa: Optional["VisualQAResult"] = None,
    ) -> ContentRevisionResult:
        """Run preflight then execute.  Exactly 1 SAP AI Core call."""
        pf = self.preflight(
            brief=brief,
            draft=draft,
            slot_map=slot_map,
            source_material=source_material,
            revision_plan=revision_plan,
            manager_review=manager_review,
            visual_qa=visual_qa,
        )
        return self.execute(pf)

    def preflight(
        self,
        brief: "ConsultingSlideBrief",
        draft: "SlideContentDraft",
        slot_map: "TemplateSlotMap",
        source_material: Optional[str],
        revision_plan: "RevisionPlan",
        manager_review: Optional["ManagerReviewResult"] = None,
        visual_qa: Optional["VisualQAResult"] = None,
    ) -> ContentRevisionPreflight:
        """Run all deterministic pre-provider checks.  Zero provider calls.

        Raises RevisionError on any failure (bad index, missing context, etc.).
        Returns ContentRevisionPreflight for use by execute().
        """
        slot_key_map = build_slot_key_mapping(slot_map.slots)
        assignments_by_slot_id = {a.slot_id: a for a in draft.assignments}

        slot_specs: list[dict] = []
        for key, slot in slot_key_map.items():
            assignment = assignments_by_slot_id.get(slot.slot_id)
            if assignment is None:
                continue
            slot_specs.append({
                "key": key,
                "role": slot.slot_role.value,
                "label": slot.semantic_label,
                "action": assignment.action.value,
                "text": assignment.text,
                "capacity_characters": assignment.capacity_characters,
                "capacity_utilization": assignment.capacity_utilization,
                "max_lines_estimate": assignment.max_lines_estimate,
            })

        target_keys = revision_plan.target_slot_keys

        # Validate feedback indexes BEFORE provider invocation.
        # Any bad index or missing review context raises RevisionError (0 API calls).
        _validate_feedback_indexes(revision_plan, manager_review, visual_qa)

        # Build revision_feedback from plan indexes using actual M7/M8 issue objects.
        revision_feedback = _build_revision_feedback(revision_plan, manager_review, visual_qa)

        return ContentRevisionPreflight(
            brief=brief,
            draft=draft,
            source_material=source_material,
            slot_key_map=slot_key_map,
            assignments_by_slot_id=assignments_by_slot_id,
            slot_specs=slot_specs,
            target_keys=target_keys,
            revision_feedback=revision_feedback,
            revision_plan=revision_plan,
        )

    def execute(self, preflight: ContentRevisionPreflight) -> ContentRevisionResult:
        """Execute the provider call and apply post-provider validation.

        The caller must increment its attempt counter BEFORE calling this method.
        Every execute() call constitutes exactly one provider attempt.
        Raises RevisionError for post-provider validation failures (unknown key,
        outside-target scope, capacity violation, minimal-change violation).
        """
        from slidestein.drafting.versions import CONTENT_DRAFT_SCHEMA_VERSION  # noqa: PLC0415

        # ONE API call
        model_output = self._reviser.revise(
            brief=preflight.brief,
            source_material=preflight.source_material,
            slot_specs=preflight.slot_specs,
            target_keys=preflight.target_keys,
            current_draft=preflight.draft,
            revision_feedback=preflight.revision_feedback,
        )

        # Handle blocked status
        if model_output.status == "blocked":
            return ContentRevisionResult(
                status="blocked",
                revised_draft=None,
                applied_changes=[],
                change_summary=model_output.change_summary,
                blocked_reason=model_output.blocked_reason,
            )

        # --- Validate changes before applying ---

        # 1. Check for duplicate keys in changes
        seen_keys: set[str] = set()
        for change in model_output.changes:
            if change.key in seen_keys:
                raise RevisionError(
                    f"Reviser returned duplicate change for key {change.key!r}. "
                    "Each key may appear at most once in changes."
                )
            seen_keys.add(change.key)

        # 2. Validate all changed keys are known AND within target scope
        slot_key_map = preflight.slot_key_map
        assignments_by_slot_id = preflight.assignments_by_slot_id
        change_map = {c.key: c for c in model_output.changes}
        target_set = set(preflight.target_keys)
        for key in change_map:
            if key not in slot_key_map:
                raise RevisionError(
                    f"Reviser returned change for unknown key {key!r}. "
                    f"Valid keys: {sorted(slot_key_map.keys())}"
                )
            if key not in target_set:
                raise RevisionError(
                    f"Reviser returned change for key {key!r} which is outside "
                    f"the revision plan target scope {sorted(target_set)}."
                )

        # 3. Capture before snapshots for exact minimal-change guarantee
        before_by_slot_id: dict[str, dict] = {
            a.slot_id: a.model_dump() for a in preflight.draft.assignments
        }

        # 4. Build patched assignments
        patched_assignments: list[SlotDraftAssignment] = []
        for key, slot in slot_key_map.items():
            original = assignments_by_slot_id[slot.slot_id]
            if key in change_map:
                change = change_map[key]
                if original.action not in (SlotDraftAction.REPLACE, SlotDraftAction.CLEAR):
                    raise RevisionError(
                        f"Reviser attempted to change slot {key!r} which has "
                        f"action={original.action.value!r}. "
                        "Reviser may only change REPLACE or CLEAR slots."
                    )
                patched = _apply_change(original, change, key)
                patched_assignments.append(patched)
            else:
                patched_assignments.append(original)

        # 5. Verify untouched assignments are exactly unchanged
        for a in patched_assignments:
            if a.slot_id not in {slot_key_map[k].slot_id for k in change_map
                                  if k in slot_key_map}:
                before = before_by_slot_id.get(a.slot_id)
                after = a.model_dump()
                if before is not None and before != after:
                    raise RevisionError(
                        f"Non-target slot {a.slot_id!r} was mutated by the patch. "
                        "Exact minimal-change guarantee violated."
                    )

        from slidestein.drafting.models import SlideContentDraft  # noqa: PLC0415

        revised_draft = SlideContentDraft(
            schema_version=CONTENT_DRAFT_SCHEMA_VERSION,
            slide_id=preflight.draft.slide_id,
            deck_id=preflight.draft.deck_id,
            slide_number=preflight.draft.slide_number,
            brief_key_message=preflight.draft.brief_key_message,
            assignments=patched_assignments,
            open_questions=preflight.draft.open_questions,
            drafting_summary=f"[M9 revision] {model_output.change_summary}",
            is_complete=True,
        )

        return ContentRevisionResult(
            status="revised",
            revised_draft=revised_draft,
            applied_changes=model_output.changes,
            change_summary=model_output.change_summary,
        )


# ---------------------------------------------------------------------------
# BoundedRevisionOrchestrator
# ---------------------------------------------------------------------------


class BoundedRevisionOrchestrator:
    """Orchestrate one bounded revision cycle.

    For content_revision route:
      1. ContentRevisionService.revise()   — 1 SAP text call
         If blocked → stop immediately (no M6/M7/M8)
      2. PowerPointWritebackService.apply() — 0 API calls (COM write)
      3. ManagerReviewService.review()     — 1 SAP text call
      4. VisualQAService.review()          — 1 SAP Vision call
      STOP — one cycle hard limit.

    model_calls counters are incremented BEFORE each provider invocation.
    Failures count as attempts (not excluded from budget).

    Maximum total: 3 API calls (revision + manager_review + visual_qa).

    On failure: raises RevisionExecutionError carrying model_calls at point of failure
    and the stage name, so callers can record accurate attempt accounting.
    """

    def __init__(
        self,
        content_revision_service: ContentRevisionService,
        manager_review_service: "ManagerReviewService",
        visual_qa_service: "VisualQAService",
        artifacts_dir: Path,
    ) -> None:
        self._content_revision_service = content_revision_service
        self._manager_review_service = manager_review_service
        self._visual_qa_service = visual_qa_service
        self._artifacts_dir = artifacts_dir

    def revise(self, request: RevisionRequest) -> RevisionCycleResult:
        model_calls: dict = {"revision": 0, "manager_review": 0, "visual_qa": 0}

        # Step 1 — Deterministic routing (0 API calls); raises RevisionError on contract error
        router = RevisionRouter()
        plan = router.route(request)

        slide_id = plan.slide_id
        deck_id = plan.deck_id
        slide_number = plan.slide_number

        if plan.route == RevisionRoute.FINALIZE:
            return RevisionCycleResult(
                route=plan.route,
                slide_id=slide_id,
                deck_id=deck_id,
                slide_number=slide_number,
                plan=plan,
                status="finalized",
                final_ready=True,
                model_calls=dict(model_calls),
            )

        if plan.route != RevisionRoute.CONTENT_REVISION:
            return RevisionCycleResult(
                route=plan.route,
                slide_id=slide_id,
                deck_id=deck_id,
                slide_number=slide_number,
                plan=plan,
                status="escalation_required",
                final_ready=False,
                model_calls=dict(model_calls),
            )

        # Step 2 — Content revision (1 SAP text call)
        # Step 2a-pre: File preflight — deterministic, 0 provider calls.
        # All failures here are RevisionError with revision=0 (not yet incremented).
        if not request.source_material or not request.source_material.strip():
            raise RevisionError(
                "content_revision requires non-empty source_material."
            )
        if request.template_pptx is None:
            raise RevisionError(
                "content_revision requires template_pptx."
            )
        if not request.template_pptx.exists():
            raise RevisionError(
                f"template_pptx not found: {request.template_pptx}"
            )
        if not request.template_pptx.is_file():
            raise RevisionError(
                f"template_pptx is not a file: {request.template_pptx}"
            )
        if request.output_pptx is None:
            raise RevisionError(
                "content_revision requires output_pptx."
            )
        if request.output_pptx.exists() and not request.overwrite:
            raise RevisionError(
                f"output_pptx already exists and overwrite=False: {request.output_pptx}"
            )

        # Step 2a: Deterministic preflight — 0 provider calls, 0 attempts.
        # RevisionError propagates directly; model_calls["revision"] stays 0.
        preflight = self._content_revision_service.preflight(
            brief=request.brief,
            draft=request.draft,
            slot_map=request.slot_map,
            source_material=request.source_material,
            revision_plan=plan,
            manager_review=request.manager_review,
            visual_qa=request.visual_qa,
        )
        # Step 2b: Provider execution. Increment AFTER preflight, right before
        # the provider boundary. Any failure here (including post-provider
        # RevisionError) must surface as RevisionExecutionError with revision=1.
        model_calls["revision"] += 1
        try:
            content_result = self._content_revision_service.execute(preflight)
        except Exception as exc:
            raise RevisionExecutionError(
                f"Content revision failed: {type(exc).__name__}",
                stage="content_revision",
                model_calls=dict(model_calls),
            ) from exc

        # Handle blocked status — stop immediately, no M6/M7/M8
        if content_result.status == "blocked":
            return RevisionCycleResult(
                route=plan.route,
                slide_id=slide_id,
                deck_id=deck_id,
                slide_number=slide_number,
                plan=plan,
                status="blocked",
                final_ready=False,
                model_calls=dict(model_calls),
            )

        revised_draft = content_result.revised_draft

        # Step 3 — M6 write-back (0 API calls, COM write)
        # Uses original template_pptx — NOT the revised draft's own path.
        # Any exception — including RevisionError wrapping PowerPointWritebackError
        # from _run_writeback — must preserve the already-counted revision attempt.
        revised_pptx = request.output_pptx
        writeback_result: Optional[Any] = None
        try:
            writeback_result = self._run_writeback(request, revised_draft, revised_pptx)
        except Exception as exc:
            raise RevisionExecutionError(
                "Write-back failed after content revision: PowerPointWritebackError",
                stage="writeback",
                model_calls=dict(model_calls),
            ) from exc

        # Step 4 — M7 re-review (1 SAP text call)
        from slidestein.review.models import ManagerReviewRequest  # noqa: PLC0415

        model_calls["manager_review"] += 1
        try:
            m7_request = ManagerReviewRequest(
                brief=request.brief,
                draft=revised_draft,
                slot_map=request.slot_map,
                source_material=request.source_material,
            )
            manager_review_after = self._manager_review_service.review(m7_request)
        except Exception as exc:
            raise RevisionExecutionError(
                f"Post-revision manager review failed: {type(exc).__name__}",
                stage="manager_review",
                model_calls=dict(model_calls),
            ) from exc

        # Step 5 — M8 visual re-QA (1 SAP Vision call)
        from slidestein.qa.models import VisualQARequest  # noqa: PLC0415

        model_calls["visual_qa"] += 1
        try:
            qa_request = VisualQARequest(
                template_pptx=request.template_pptx,
                generated_pptx=revised_pptx,
                draft=revised_draft,
                slot_map=request.slot_map,
            )
            visual_qa_after = self._visual_qa_service.review(
                qa_request, self._artifacts_dir
            )
        except Exception as exc:
            raise RevisionExecutionError(
                f"Post-revision visual QA failed: {type(exc).__name__}",
                stage="visual_qa",
                model_calls=dict(model_calls),
            ) from exc

        # Step 6 — Determine final_ready
        final_ready = (
            manager_review_after.recommendation == "approve"
            and visual_qa_after.recommendation == "pass"
        )

        return RevisionCycleResult(
            route=plan.route,
            slide_id=slide_id,
            deck_id=deck_id,
            slide_number=slide_number,
            plan=plan,
            status="revised",
            revised_draft=revised_draft,
            writeback_result=writeback_result,
            manager_review_after=manager_review_after,
            visual_qa_after=visual_qa_after,
            final_ready=final_ready,
            output_pptx=revised_pptx,
            model_calls=dict(model_calls),
        )

    @staticmethod
    def _run_writeback(
        request: RevisionRequest,
        revised_draft: "SlideContentDraft",
        output_pptx: Path,
    ) -> Optional["PowerPointWritebackResult"]:
        """Apply revised draft to the ORIGINAL template PPTX via M6."""
        from slidestein.writeback.errors import PowerPointWritebackError  # noqa: PLC0415
        from slidestein.writeback.models import PowerPointWritebackRequest  # noqa: PLC0415
        from slidestein.writeback.service import PowerPointWritebackService  # noqa: PLC0415

        output_pptx.parent.mkdir(parents=True, exist_ok=True)
        wb_request = PowerPointWritebackRequest(
            draft=revised_draft,
            slot_map=request.slot_map,
            source_pptx=request.template_pptx,
            output_pptx=output_pptx,
            overwrite=request.overwrite,
        )
        svc = PowerPointWritebackService()
        try:
            plan = svc.preflight(wb_request)
            return svc.apply(plan)
        except PowerPointWritebackError as exc:
            raise RevisionError(
                "Write-back preflight/apply failed: PowerPointWritebackError"
            ) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_change(
    original: "SlotDraftAssignment",
    change: "RevisionChange",
    key: str,
) -> "SlotDraftAssignment":
    """Apply a single RevisionChange to an assignment, returning the patched assignment."""
    if change.action == "replace":
        new_text = change.text  # guaranteed non-empty by model validator
        validate_text_capacity(
            text=new_text,
            max_chars=original.capacity_characters,
            max_lines=original.max_lines_estimate,
            key=key,
            error_factory=RevisionError,
        )
        char_count = len(new_text)
        max_chars = original.capacity_characters
        utilization = round(char_count / max_chars, 4) if max_chars > 0 else 0.0
        line_count = new_text.count("\n") + 1
        return SlotDraftAssignment(
            slot_id=original.slot_id,
            shape_id=original.shape_id,
            shape_path=original.shape_path,
            slot_role=original.slot_role,
            semantic_label=original.semantic_label,
            action=SlotDraftAction.REPLACE,
            text=new_text,
            missing_information=None,
            character_count=char_count,
            capacity_characters=original.capacity_characters,
            capacity_utilization=utilization,
            explicit_line_count=line_count,
            max_lines_estimate=original.max_lines_estimate,
            group_id=original.group_id,
            sequence_index=original.sequence_index,
        )
    elif change.action == "clear":
        return SlotDraftAssignment(
            slot_id=original.slot_id,
            shape_id=original.shape_id,
            shape_path=original.shape_path,
            slot_role=original.slot_role,
            semantic_label=original.semantic_label,
            action=SlotDraftAction.CLEAR,
            text=None,
            missing_information=None,
            character_count=0,
            capacity_characters=original.capacity_characters,
            capacity_utilization=0.0,
            explicit_line_count=0,
            max_lines_estimate=original.max_lines_estimate,
            group_id=original.group_id,
            sequence_index=original.sequence_index,
        )
    else:
        raise RevisionError(f"Unknown change action: {change.action!r}")


def _validate_feedback_indexes(
    revision_plan: "RevisionPlan",
    manager_review: Optional[Any],
    visual_qa: Optional[Any],
) -> None:
    """Raise RevisionError for any invalid feedback index or missing review context.

    Called BEFORE provider invocation — zero API calls consumed on failure.
    """
    if revision_plan.manager_issue_indexes or revision_plan.factual_flag_indexes:
        if manager_review is None:
            raise RevisionError(
                "revision_plan references manager_issue_indexes or factual_flag_indexes "
                "but manager_review was not provided."
            )
        n_issues = len(manager_review.issues)
        for idx in revision_plan.manager_issue_indexes:
            if idx < 0 or idx >= n_issues:
                raise RevisionError(
                    f"manager_issue_indexes contains invalid index {idx}. "
                    f"manager_review has {n_issues} issue(s) "
                    f"(valid range 0..{n_issues - 1})."
                )
        n_flags = len(manager_review.factual_flags)
        for idx in revision_plan.factual_flag_indexes:
            if idx < 0 or idx >= n_flags:
                raise RevisionError(
                    f"factual_flag_indexes contains invalid index {idx}. "
                    f"manager_review has {n_flags} factual flag(s) "
                    f"(valid range 0..{n_flags - 1})."
                )
    if revision_plan.visual_issue_indexes:
        if visual_qa is None:
            raise RevisionError(
                "revision_plan references visual_issue_indexes "
                "but visual_qa was not provided."
            )
        n_visual = len(visual_qa.issues)
        for idx in revision_plan.visual_issue_indexes:
            if idx < 0 or idx >= n_visual:
                raise RevisionError(
                    f"visual_issue_indexes contains invalid index {idx}. "
                    f"visual_qa has {n_visual} issue(s) "
                    f"(valid range 0..{n_visual - 1})."
                )


def _build_revision_feedback(
    revision_plan: "RevisionPlan",
    manager_review: Optional[Any] = None,
    visual_qa: Optional[Any] = None,
) -> list[dict]:
    """Build revision_feedback from plan issue indexes and actual M7/M8 issue objects.

    Indexes have already been validated by _validate_feedback_indexes — access directly.
    Uses ONLY actual object fields — no fabricated defaults.
    Feedback is ADVISORY; the factual universe is brief + source_material.
    """
    feedback: list[dict] = []
    if manager_review is not None:
        for idx in revision_plan.manager_issue_indexes:
            iss = manager_review.issues[idx]
            feedback.append({
                "source": "manager_review",
                "severity": getattr(iss, "severity", ""),
                "category": getattr(iss, "category", ""),
                "slot_keys": list(getattr(iss, "slot_keys", [])),
                "issue": getattr(iss, "issue", ""),
                "recommendation": getattr(iss, "recommendation", ""),
            })
        for idx in revision_plan.factual_flag_indexes:
            iss = manager_review.factual_flags[idx]
            feedback.append({
                "source": "manager_factual_flag",
                "severity": getattr(iss, "severity", ""),
                "category": getattr(iss, "category", ""),
                "slot_keys": list(getattr(iss, "slot_keys", [])),
                "issue": getattr(iss, "issue", ""),
                "recommendation": getattr(iss, "recommendation", ""),
            })
    if visual_qa is not None:
        for idx in revision_plan.visual_issue_indexes:
            iss = visual_qa.issues[idx]
            feedback.append({
                "source": "visual_qa",
                "severity": getattr(iss, "severity", ""),
                "category": getattr(iss, "category", ""),
                "slot_keys": list(getattr(iss, "slot_keys", [])),
                "issue": getattr(iss, "issue", ""),
                "evidence": getattr(iss, "evidence", ""),
                "recommendation": getattr(iss, "recommendation", ""),
            })
    return feedback
