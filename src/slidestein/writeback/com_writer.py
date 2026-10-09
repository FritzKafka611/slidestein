"""COM-based write execution for M6 write-back.

Applies a validated WritebackPlan to a working PPTX copy via PowerPoint COM.

Design decisions:
  - Shape targeting: by shape_path (hierarchical ID chain), validated against shape_id.
  - Write method: TextFrame.TextRange.Text = text (direct assignment).
    Known limitation: per-run character formatting (bold/italic/colour on specific
    words) within the target text frame is flattened to the first run's format.
    Frame-level formatting (font, size, colour of the placeholder/text box) is
    preserved by PowerPoint's own text frame handling.
  - Line breaks: draft \n normalised to COM \r (paragraph separator).
  - CLEAR: sets TextRange.Text = "" (empty string); shape is NOT deleted or hidden.
  - COM lifecycle: always closed in finally block (no orphaned POWERPNT.EXE).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from slidestein.drafting.models import SlotDraftAction
from slidestein.writeback.errors import PowerPointWritebackError
from slidestein.writeback.models import WritebackOperation, WritebackPlan

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Line-break normalisation
# ---------------------------------------------------------------------------


def normalize_for_com(text: str) -> str:
    """Convert Python \n line endings to PowerPoint COM paragraph separator \r."""
    return text.replace("\n", "\r")


def normalize_readback(text: str) -> str:
    """Normalise text read back from python-pptx to Python \n endings.

    python-pptx's .text_frame.text uses \n for paragraph boundaries and
    may use \x0b for soft returns within a paragraph.  Both are normalised
    to \n for comparison with draft strings.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n")


# ---------------------------------------------------------------------------
# COM shape resolution
# ---------------------------------------------------------------------------


def _find_in_com_collection(collection: object, shape_id: int) -> Optional[object]:
    """Find a COM shape by Id in a Shapes or GroupItems collection.

    Iterates the COM collection (comtypes makes it iterable).
    Returns None if not found.
    """
    try:
        for shape in collection:  # type: ignore[union-attr]
            try:
                if int(shape.Id) == shape_id:
                    return shape
            except Exception:
                continue
    except Exception:
        pass
    return None


def resolve_com_shape_by_path(slide_com: object, shape_path: str) -> Optional[object]:
    """Resolve a shape_path to a COM shape object.

    shape_path format (from M5.2 slots/inspector.py):
      "7"        — top-level shape with Id 7
      "12/7"     — shape Id 7 inside group Id 12
      "31/46/48" — leaf shape Id 48 somewhere inside group Id 31

    PowerPoint COM's GroupItems collection is FLAT: it contains ALL leaf-level
    descendants of a group, but does NOT include intermediate group shapes.
    For nested paths (depth > 1), we locate the top-level group then search
    GroupItems for the leaf shape Id (final path segment).

    Returns None if any segment cannot be found.
    Never falls back to text matching or bounding-box heuristics.
    """
    parts = shape_path.split("/")
    try:
        top_id = int(parts[0])
    except ValueError:
        return None

    shape = _find_in_com_collection(slide_com.Shapes, top_id)  # type: ignore[union-attr]
    if shape is None:
        return None

    if len(parts) == 1:
        return shape

    # Nested path: leaf is the last segment.  COM GroupItems is flat, so search
    # directly for the leaf Id without navigating intermediate groups.
    try:
        leaf_id = int(parts[-1])
    except ValueError:
        return None

    try:
        group_items = shape.GroupItems
    except Exception:
        return None

    return _find_in_com_collection(group_items, leaf_id)


# ---------------------------------------------------------------------------
# Core write execution
# ---------------------------------------------------------------------------


def execute_plan(plan: WritebackPlan) -> None:
    """Apply all operations in the plan to a working copy via PowerPoint COM.

    Flow:
      1. Copy source → working temp copy.
      2. Open working copy in COM.
      3. Navigate to target slide.
      4. Resolve each shape by path; validate shape_id; set text.
      5. SaveAs output_pptx.
      6. Close and quit COM.
      7. Delete working temp copy.

    The caller (service.py) handles verification and promotion/rollback.
    Raises PowerPointWritebackError on any COM or resolution failure.
    """
    try:
        import comtypes.client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise PowerPointWritebackError(
            "comtypes is required for PowerPoint COM operations. "
            "Install: uv add comtypes"
        ) from exc

    source_pptx = plan.source_pptx
    output_pptx = plan.output_pptx
    slide_number = plan.resolved_slide_number  # stable-identity-resolved ordinal

    # Ensure output parent exists
    output_pptx.parent.mkdir(parents=True, exist_ok=True)

    # Working copy: source is opened via COM; SaveAs writes to output.
    ppt = None
    prs = None
    try:
        ppt = comtypes.client.CreateObject("PowerPoint.Application")
        ppt.Visible = 1

        prs = ppt.Presentations.Open(
            str(source_pptx.resolve()),
            ReadOnly=False,
            WithWindow=False,
        )

        slide = prs.Slides(slide_number)

        for op in plan.operations:
            _apply_operation(slide, op, slide_number)

        prs.SaveAs(str(output_pptx.resolve()))

    except PowerPointWritebackError:
        raise
    except Exception as exc:
        raise PowerPointWritebackError(
            f"PowerPoint COM write-back failed for slide {slide_number} "
            f"of {source_pptx.name}: {exc}"
        ) from exc
    finally:
        _safe_close(prs)
        _safe_quit(ppt)


def _apply_operation(
    slide_com: object,
    op: WritebackOperation,
    slide_number: int,
) -> None:
    """Resolve and write one operation.  Raises PowerPointWritebackError on failure."""
    shape = resolve_com_shape_by_path(slide_com, op.shape_path)
    if shape is None:
        raise PowerPointWritebackError(
            f"Cannot resolve shape_path {op.shape_path!r} for slot "
            f"{op.slot_id!r} on slide {slide_number} via COM. "
            "Preflight should have caught this — source may have changed."
        )

    try:
        actual_id = int(shape.Id)
    except Exception as exc:
        raise PowerPointWritebackError(
            f"Cannot read Id of shape at {op.shape_path!r}: {exc}"
        ) from exc

    if actual_id != op.shape_id:
        raise PowerPointWritebackError(
            f"Shape at path {op.shape_path!r} has Id={actual_id} in COM, "
            f"expected shape_id={op.shape_id} (slot {op.slot_id!r})"
        )

    try:
        tf = shape.TextFrame
        tr = tf.TextRange
    except Exception as exc:
        raise PowerPointWritebackError(
            f"Cannot access TextFrame for shape {op.shape_path!r} "
            f"(slot {op.slot_id!r}): {exc}"
        ) from exc

    if op.action == SlotDraftAction.REPLACE:
        com_text = normalize_for_com(op.text or "")
        try:
            tr.Text = com_text
        except Exception as exc:
            raise PowerPointWritebackError(
                f"Failed to set text for shape {op.shape_path!r} "
                f"(slot {op.slot_id!r}): {exc}"
            ) from exc

    elif op.action == SlotDraftAction.CLEAR:
        try:
            tr.Text = ""
        except Exception as exc:
            raise PowerPointWritebackError(
                f"Failed to clear text for shape {op.shape_path!r} "
                f"(slot {op.slot_id!r}): {exc}"
            ) from exc

    else:
        # NEEDS_INPUT must never reach execution — defensive guard
        raise PowerPointWritebackError(
            f"Impossible: action={op.action.value!r} reached execution "
            f"for slot {op.slot_id!r}. Preflight must reject needs_input."
        )


# ---------------------------------------------------------------------------
# COM lifecycle helpers
# ---------------------------------------------------------------------------


def _safe_close(prs: Optional[object]) -> None:
    if prs is not None:
        try:
            prs.Close()  # type: ignore[union-attr]
        except Exception:
            pass


def _safe_quit(ppt: Optional[object]) -> None:
    if ppt is not None:
        try:
            ppt.Quit()  # type: ignore[union-attr]
        except Exception:
            pass
