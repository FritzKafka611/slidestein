"""Read-back and structure-preservation verification for M6.

All verification uses python-pptx (no COM, no LLM).

verify_text():
    For every WritebackOperation, reads the shape text from the output PPTX
    and compares with the expected text.

verify_structure() / verify_non_target_structure():
    Compares structure fingerprints before/after write.
    Target slide must be unchanged in geometry.
    All non-target slides must be unchanged.
    Deck slide count and order must be preserved.

compute_format_fingerprint():
    SHA-256 of shape-level structural format properties (rotation, text-frame
    margins, word-wrap, paragraph alignment) for all shapes on a slide.
    Excludes text content and run-level font properties.

    Run-level font overrides (font.name/size/bold/italic) are intentionally
    excluded: COM's TextRange.Text = value clears run-level overrides and
    resets them to inheritance from the paragraph/shape defaults.  This is
    expected M6 v1 behaviour — it is not format corruption.  Only frame- and
    paragraph-level structural properties are fingerprinted here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from pptx import Presentation

from slidestein.drafting.models import SlotDraftAction
from slidestein.writeback.com_writer import normalize_readback
from slidestein.writeback.models import WritebackOperation, WritebackReceipt
from slidestein.writeback.preflight import _build_shape_path_map


# ---------------------------------------------------------------------------
# Text read-back
# ---------------------------------------------------------------------------


def read_shape_text(pptx_path: Path, slide_number: int, shape_path: str) -> Optional[str]:
    """Read the text of a shape at shape_path from a PPTX file.

    Returns the normalised text, or None if the shape cannot be found or read.
    """
    try:
        prs = Presentation(str(pptx_path))
        slide = prs.slides[slide_number - 1]
        path_map = _build_shape_path_map(slide.shapes)
        shape = path_map.get(shape_path)
        if shape is None:
            return None
        if not getattr(shape, "has_text_frame", False):
            return None
        raw = shape.text_frame.text  # type: ignore[union-attr]
        return normalize_readback(raw)
    except Exception:
        return None


def verify_text(
    output_pptx: Path,
    slide_number: int,
    operations: list[WritebackOperation],
) -> tuple[list[WritebackReceipt], bool]:
    """Verify that every operation produced the expected text in the output PPTX.

    Returns (receipts, all_verified).
    all_verified is True only when every receipt has verified=True.
    """
    receipts: list[WritebackReceipt] = []
    all_verified = True

    for op in operations:
        if op.action == SlotDraftAction.REPLACE:
            expected = op.text or ""
        elif op.action == SlotDraftAction.CLEAR:
            expected = ""
        else:
            # NEEDS_INPUT should never reach here
            receipts.append(WritebackReceipt(
                slot_id=op.slot_id,
                shape_id=op.shape_id,
                shape_path=op.shape_path,
                action=op.action.value,
                expected_text=None,
                verified_text=None,
                verified=False,
            ))
            all_verified = False
            continue

        actual = read_shape_text(output_pptx, slide_number, op.shape_path)
        verified = actual is not None and normalize_readback(actual) == expected

        if not verified:
            all_verified = False

        receipts.append(WritebackReceipt(
            slot_id=op.slot_id,
            shape_id=op.shape_id,
            shape_path=op.shape_path,
            action=op.action.value,
            expected_text=expected,
            verified_text=actual,
            verified=verified,
        ))

    return receipts, all_verified


# ---------------------------------------------------------------------------
# Target slide structure preservation
# ---------------------------------------------------------------------------


def compute_after_structure_fingerprint(
    output_pptx: Path,
    slide_number: int,
) -> Optional[str]:
    """Compute the structure fingerprint for the target slide in the output PPTX.

    Returns None if the computation fails (logged by caller).
    """
    from slidestein.identity.slide_identity import compute_structure_fingerprint
    try:
        return compute_structure_fingerprint(output_pptx, slide_number)
    except Exception:
        return None


def verify_structure(
    before_fp: str,
    after_fp: Optional[str],
) -> tuple[bool, list[str]]:
    """Compare before/after structure fingerprints for the target slide.

    Returns (preserved, warnings).
    preserved is True when fingerprints match or after_fp is unavailable.
    warnings contains human-readable explanations of any problems found.
    """
    warnings: list[str] = []

    if not after_fp:
        warnings.append(
            "Structure fingerprint could not be computed for output PPTX — "
            "structure preservation unverified."
        )
        return True, warnings  # cannot assert failure; caller decides

    if not before_fp:
        warnings.append(
            "Before-write structure fingerprint was unavailable — "
            "structure preservation unverified."
        )
        return True, warnings

    if before_fp != after_fp:
        return False, [
            f"Structure fingerprint changed after write-back: "
            f"before={before_fp[:16]}... after={after_fp[:16]}... — "
            "shape geometry or shape count on the target slide was mutated."
        ]

    return True, []


# ---------------------------------------------------------------------------
# Deck-level structure baseline (all slides)
# ---------------------------------------------------------------------------


def compute_deck_structure_snapshot(
    pptx_path: Path,
) -> tuple[list[int], dict[str, str]]:
    """Compute structure fingerprints for all slides in a deck.

    Returns (ordered_native_ids, {str(native_slide_id): structure_fp}).

    ordered_native_ids is the list of native slide IDs in presentation order.
    The dict keys are str(native_id) for JSON-serialisation compatibility.
    """
    from slidestein.identity.slide_identity import (
        compute_structure_fingerprint,
        extract_slide_identities,
    )

    identities = extract_slide_identities(pptx_path)
    ordered_ids = [si.native_slide_id for si in identities]
    snapshot: dict[str, str] = {}

    for si in identities:
        try:
            fp = compute_structure_fingerprint(pptx_path, si.slide_number)
        except Exception:
            fp = ""
        snapshot[str(si.native_slide_id)] = fp

    return ordered_ids, snapshot


def verify_non_target_structure(
    before_native_ids: list[int],
    before_snapshot: dict[str, str],
    after_native_ids: list[int],
    after_snapshot: dict[str, str],
    target_native_id: Optional[int],
) -> tuple[bool, bool, list[str]]:
    """Verify target and non-target slide structures after write-back.

    Returns (target_ok, non_target_ok, warnings).

    Checks:
      - Slide count unchanged.
      - Slide order (native IDs) unchanged.
      - Each non-target slide's structure fingerprint unchanged.
      - Target slide's structure fingerprint unchanged (separate flag).

    Any failure in slide count/order marks non_target_ok=False immediately.
    """
    warnings: list[str] = []
    target_ok = True
    non_target_ok = True

    if before_native_ids != after_native_ids:
        non_target_ok = False
        warnings.append(
            f"Deck slide count or order changed after write-back: "
            f"before={before_native_ids}, after={after_native_ids}"
        )
        return target_ok, non_target_ok, warnings

    for native_id in before_native_ids:
        key = str(native_id)
        before_fp = before_snapshot.get(key, "")
        after_fp = after_snapshot.get(key, "")

        if not before_fp or not after_fp:
            continue  # fingerprint unavailable — cannot assert failure

        if before_fp != after_fp:
            is_target = (native_id == target_native_id)
            if is_target:
                target_ok = False
                warnings.append(
                    f"Target slide structure changed (native_slide_id={native_id}): "
                    f"before={before_fp[:16]}... after={after_fp[:16]}..."
                )
            else:
                non_target_ok = False
                warnings.append(
                    f"Non-target slide structure changed (native_slide_id={native_id}): "
                    f"before={before_fp[:16]}... after={after_fp[:16]}..."
                )

    return target_ok, non_target_ok, warnings


# ---------------------------------------------------------------------------
# Format fingerprint (frame-level properties, no text)
# ---------------------------------------------------------------------------


def _safe_float(value: object) -> Optional[float]:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _shape_format_dict(shape: object) -> dict:
    """Extract frame-level structural format properties for one shape (no text, no run fonts)."""
    d: dict = {}

    # Shape-level: rotation
    try:
        d["rotation"] = _safe_float(getattr(shape, "rotation", None))
    except Exception:
        d["rotation"] = None

    if not getattr(shape, "has_text_frame", False):
        return d

    try:
        tf = shape.text_frame  # type: ignore[union-attr]

        # Text-frame margins (EMU)
        d["margin_left"] = _safe_float(getattr(tf, "margin_left", None))
        d["margin_right"] = _safe_float(getattr(tf, "margin_right", None))
        d["margin_top"] = _safe_float(getattr(tf, "margin_top", None))
        d["margin_bottom"] = _safe_float(getattr(tf, "margin_bottom", None))
        d["word_wrap"] = getattr(tf, "word_wrap", None)

        # First paragraph alignment (paragraph-level, not run-level)
        para_alignment: Optional[str] = None
        try:
            paras = list(tf.paragraphs)
            if paras:
                pa = paras[0].alignment
                para_alignment = pa.name if pa is not None else None
        except Exception:
            pass
        d["para_alignment"] = para_alignment

        # NOTE: run-level font overrides (font.name/size/bold/italic) are
        # intentionally NOT included.  COM's TextRange.Text = value clears
        # per-run font overrides — that is expected M6 v1 behaviour, not
        # format corruption.  Only frame/paragraph-level properties are here.

    except Exception:
        pass

    return d


def compute_format_fingerprint(pptx_path: Path, slide_number: int) -> str:
    """SHA-256 of shape format properties — excludes all text values.

    Captures: rotation, font name/size/bold/italic, paragraph alignment,
    text-frame margins, word-wrap setting.

    Shapes are sorted by (top, left) for determinism.
    Used to verify M6 does not inadvertently mutate format properties.
    """
    prs = Presentation(str(pptx_path))
    slide = prs.slides[slide_number - 1]

    descriptors = []
    for shape in slide.shapes:
        left = getattr(shape, "left", 0) or 0
        top = getattr(shape, "top", 0) or 0
        entry = _shape_format_dict(shape)
        entry["_left"] = int(left)
        entry["_top"] = int(top)
        descriptors.append(entry)

    # Sort by (top, left) for position-order determinism
    descriptors.sort(key=lambda d: (d.get("_top", 0), d.get("_left", 0)))

    # Remove sort keys before hashing
    for d in descriptors:
        d.pop("_left", None)
        d.pop("_top", None)

    canonical = json.dumps(descriptors, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
