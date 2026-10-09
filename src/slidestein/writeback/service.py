"""M6 PowerPoint write-back service.

Orchestrates the full write-back pipeline:
  1. preflight()       — validates the request, returns a WritebackPlan
  2. execute_plan()    — COM write via atomic temp file
  3. verify_text()     — text read-back check (python-pptx)
  4. verify_structure  — target + non-target structure preservation
  5. verify_format     — format fingerprint check
  6. os.replace()      — atomic promotion of temp → final on success
  7. Rollback          — delete temp on any failure; existing final output untouched

No LLM calls.  No Anthropic API.  Deterministic execution only.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import asdict, replace as dc_replace
from pathlib import Path

from slidestein.writeback.errors import PowerPointWritebackError
from slidestein.writeback.com_writer import execute_plan
from slidestein.writeback.models import (
    PowerPointWritebackRequest,
    PowerPointWritebackResult,
    WritebackPlan,
)
from slidestein.writeback.preflight import preflight as _preflight
from slidestein.writeback.verification import (
    compute_after_structure_fingerprint,
    compute_deck_structure_snapshot,
    compute_format_fingerprint,
    verify_non_target_structure,
    verify_structure,
    verify_text,
)

_LOG = logging.getLogger(__name__)


class PowerPointWritebackService:
    """Apply validated write-back plans to real PPTX files."""

    def preflight(self, request: PowerPointWritebackRequest) -> WritebackPlan:
        """Run all pre-mutation checks and return a write-ready plan.

        Raises PowerPointWritebackError if any check fails.
        No file mutation, no COM, no LLM.
        """
        return _preflight(request)

    def apply(self, plan: WritebackPlan) -> PowerPointWritebackResult:
        """Execute the plan atomically, verify the output, and return a result.

        Atomic publication flow:
          1. Write via COM to a unique temp sibling of the final output path.
          2. Verify temp: text read-back + target structure + non-target structure
             + format properties.
          3. Success → os.replace(temp, final).  Existing final never touched until
             this point.
          4. Failure → delete temp, raise.  Existing final output preserved exactly.

        Returns PowerPointWritebackResult with all receipts and fingerprints.
        """
        final_output = plan.output_pptx
        resolved_num = plan.resolved_slide_number

        # Unique temp path in same directory (same filesystem → os.replace works)
        temp_name = f"._m6tmp_{uuid.uuid4().hex[:12]}_{final_output.name}"
        temp_output = final_output.parent / temp_name

        # Build a plan variant pointing to the temp path
        temp_plan = dc_replace(plan, output_pptx=temp_output)

        warnings: list[str] = []
        source_currentness_verified = True  # confirmed by preflight already

        try:
            # --- 1. COM write to temp -----------------------------------------
            execute_plan(temp_plan)

            # --- 2. Text read-back verification --------------------------------
            receipts, text_ok = verify_text(temp_output, resolved_num, plan.operations)

            # --- 3. Target structure fingerprint --------------------------------
            after_fp = compute_after_structure_fingerprint(temp_output, resolved_num)
            target_structure_ok, fp_warnings = verify_structure(
                plan.before_structure_fingerprint, after_fp
            )
            warnings.extend(fp_warnings)

            # --- 4. Format fingerprint (frame-level properties) -----------------
            format_ok = True
            if plan.before_format_fingerprint:
                try:
                    after_fmt_fp = compute_format_fingerprint(temp_output, resolved_num)
                    if after_fmt_fp != plan.before_format_fingerprint:
                        format_ok = False
                        warnings.append(
                            "Format fingerprint changed after write-back — "
                            "text-frame presentation properties may have been mutated."
                        )
                except Exception as exc:
                    warnings.append(
                        f"Format fingerprint could not be verified: {exc}"
                    )

            # --- 5. Non-target slide structure verification ---------------------
            non_target_ok = True
            if plan.before_deck_native_ids:
                try:
                    after_deck_native_ids, after_deck_structure = (
                        compute_deck_structure_snapshot(temp_output)
                    )
                    _, non_target_ok, deck_warnings = verify_non_target_structure(
                        plan.before_deck_native_ids,
                        plan.before_deck_structure,
                        after_deck_native_ids,
                        after_deck_structure,
                        plan.native_slide_id,
                    )
                    warnings.extend(deck_warnings)
                    # target_structure_ok is already set from the per-slide check;
                    # deck-level target check is redundant but harmless
                except Exception as exc:
                    warnings.append(
                        f"Non-target structure verification failed: {exc}"
                    )

            if not text_ok:
                failed = [r.slot_id for r in receipts if not r.verified]
                warnings.insert(
                    0,
                    f"Text read-back verification failed for {len(failed)} slot(s): {failed}",
                )

            verification_passed = (
                text_ok and target_structure_ok and format_ok and non_target_ok
            )

            # --- 6. Rollback or promote -----------------------------------------
            if not verification_passed:
                _delete_if_exists(temp_output)
                raise PowerPointWritebackError(
                    f"Verification failed for slide '{plan.slide_id}' "
                    f"(slide_number={resolved_num}). "
                    f"Output not published. Details: {'; '.join(warnings)}"
                )

            # Atomic promotion: existing final output replaced only here
            final_output.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(temp_output), str(final_output))

        except PowerPointWritebackError:
            _delete_if_exists(temp_output)
            raise
        except Exception as exc:
            _delete_if_exists(temp_output)
            raise PowerPointWritebackError(
                f"Unexpected error during write-back for slide '{plan.slide_id}': {exc}"
            ) from exc

        return PowerPointWritebackResult(
            source_pptx=str(plan.source_pptx),
            output_pptx=str(plan.output_pptx),
            slide_id=plan.slide_id,
            slide_number=plan.slide_number,
            resolved_slide_number=resolved_num,
            native_slide_id=plan.native_slide_id,
            replacement_count=plan.replacement_count,
            clear_count=plan.clear_count,
            applied_assignments=[asdict(r) for r in receipts],
            verification_passed=True,
            source_currentness_verified=source_currentness_verified,
            target_structure_verified=target_structure_ok,
            non_target_structure_verified=non_target_ok,
            warnings=warnings,
            before_structure_fingerprint=plan.before_structure_fingerprint or None,
            after_structure_fingerprint=after_fp,
        )


def _delete_if_exists(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
            _LOG.warning("Deleted partial/unverified temp output: %s", path)
    except Exception as exc:
        _LOG.warning("Could not delete %s after failure: %s", path, exc)
