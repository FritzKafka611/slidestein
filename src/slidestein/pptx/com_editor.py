"""PowerPointComEditor — native text editing via Microsoft PowerPoint COM.

Architecture contract:
  - Uses Microsoft PowerPoint COM for in-place text replacement.
  - Does NOT reconstruct slides; shapes, charts, tables, and effects are
    preserved by PowerPoint's own COM layer.
  - PowerPoint instances are always closed in a finally block.

COM API used for text replacement (Step 3 investigation result):
  TextRange.Replace(FindWhat, ReplaceWhat, After, MatchCase, WholeWords)

  Parameters are positional — the COM interface names the second parameter
  ReplaceWhat (not ReplaceWith), so keyword-argument calls silently fail.
  All Replace() calls use positional arguments.

  Chosen over TextFrame.TextRange.Text = "..." assignment because:
    - Replace operates within the existing run structure, preserving per-run
      character formatting (font size, bold, italic, colour, hyperlinks).
    - Assigning .Text replaces the entire frame and discards all run formatting.
    - Replace handles text that spans multiple runs correctly.

  Called in a loop (After=0 each time) until the return value is None, so that
  ALL occurrences in a shape are replaced, not just the first.

Fail-closed contract:
  - COM errors during Replace() propagate as PowerPointComEditorError.
    They are NEVER silently swallowed.
  - After SaveAs, every matched key is re-verified by reading the output file
    via python-pptx.  If the old text is still present, status=ERROR and the
    CLI exits non-zero.

SVG editing via PPTMasterRealAdapter.replace_text_in_slide is the FALLBACK route
for edits that cannot be expressed through native COM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger(__name__)

# PowerPoint COM type constant: msoPlaceholder
_MSO_PLACEHOLDER = 14

# MsoTriState values used in Replace()
_MSO_TRUE = -1   # msoTrue  — use instead of Python True for MsoTriState params
_MSO_FALSE = 0   # msoFalse


class ReplacementStatus(str, Enum):
    """Outcome of a single old->new text replacement request."""

    NO_MATCH = "NO_MATCH"
    REPLACED_AND_VERIFIED = "REPLACED_AND_VERIFIED"
    ERROR = "ERROR"


@dataclass
class ReplacementResult:
    """Structured outcome for one replacement key.

    Fields:
      requested         — the old text that was requested for replacement
      replacement       — the new text
      status            — NO_MATCH / REPLACED_AND_VERIFIED / ERROR
      occurrences_before — how many times old text appeared in source (python-pptx count)
      occurrences_after  — how many times old text appears in output after SaveAs
      matched           — True if old text was found in at least one shape's TextRange.Text
      replaced          — True if TextRange.Replace() was called and returned non-None
      verified          — True if occurrences_after == 0 (old text gone from output)
      error             — human-readable explanation when status == ERROR
    """

    requested: str
    replacement: str
    status: ReplacementStatus
    occurrences_before: int = 0
    occurrences_after: int = 0
    matched: bool = False
    replaced: bool = False
    verified: bool = False
    error: Optional[str] = None


@dataclass
class TextTarget:
    """A text-bearing shape identified by its COM / OOXML metadata.

    shape_id matches PowerPoint COM's shape.Id and python-pptx's shape.shape_id.
    These are stable across open/close cycles and consistent between the two APIs.

    placeholder_type is the MsoPlaceholderType integer (1=title, 2=body, etc.)
    or None if the shape is not a placeholder.

    text_bounds is (left, top, width, height) in PowerPoint points (72 pt = 1 in),
    or None if the property could not be read.
    """

    shape_id: int
    shape_name: str
    current_text: str
    placeholder_type: Optional[int] = None
    paragraph_count: int = 0
    text_bounds: Optional[tuple[float, float, float, float]] = None


class PowerPointComEditorError(RuntimeError):
    """Raised when a PowerPoint COM editing operation fails unrecoverably."""


class PowerPointComEditor:
    """Edits PPTX text natively using Microsoft PowerPoint COM.

    Each public method opens a fresh PowerPoint COM instance and always closes
    it in a finally block.  This avoids stale COM instances at the cost of one
    PowerPoint launch per call.

    Requirements:
      - Microsoft PowerPoint installed on this machine.
      - comtypes package available in the current Python environment.
    """

    def enumerate_text_shapes(
        self,
        pptx_path: Path,
        slide_number: int = 1,
    ) -> list[TextTarget]:
        """Return all text-bearing shapes on *slide_number* of *pptx_path*.

        Opens the file read-only.  Useful for verifying that text changes took
        effect after replace_text(), and for inspecting shape metadata.
        """
        try:
            import comtypes.client  # type: ignore[import-untyped]
        except ImportError as exc:
            raise PowerPointComEditorError(
                "comtypes is required for PowerPoint COM operations. "
                "Install: uv add comtypes"
            ) from exc

        ppt = comtypes.client.CreateObject("PowerPoint.Application")
        ppt.Visible = 1
        try:
            prs = ppt.Presentations.Open(
                str(pptx_path.resolve()),
                ReadOnly=True,
                WithWindow=False,
            )
            try:
                slide = prs.Slides(slide_number)
                return _collect_text_targets(slide)
            finally:
                prs.Close()
        except PowerPointComEditorError:
            raise
        except Exception as exc:
            raise PowerPointComEditorError(
                f"Failed to enumerate text shapes in {pptx_path}: {exc}"
            ) from exc
        finally:
            try:
                ppt.Quit()
            except Exception:
                pass

    def replace_text(
        self,
        source_pptx: Path,
        replacements: dict[str, str],
        output_path: Path,
        slide_number: int = 1,
    ) -> list[ReplacementResult]:
        """Replace text across all shapes on *slide_number* and save to *output_path*.

        Returns one ReplacementResult per non-empty key in *replacements*:
          NO_MATCH            — old text not found in any shape's TextRange.Text
          REPLACED_AND_VERIFIED — old text replaced and output file confirms absence
          ERROR               — Replace() returned non-None but old text still present
                                in output (SaveAs succeeded but edit did not persist)

        Raises PowerPointComEditorError on any COM error during the edit session.
        Never silently converts a failed edit to apparent success.
        """
        try:
            import comtypes.client  # type: ignore[import-untyped]
        except ImportError as exc:
            raise PowerPointComEditorError(
                "comtypes is required for PowerPoint COM operations. "
                "Install: uv add comtypes"
            ) from exc

        active_replacements = {k: v for k, v in replacements.items() if k}
        if not active_replacements:
            return []

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Count occurrences in source before editing — use python-pptx so the
        # count reads from the actual OOXML rather than COM's display buffer.
        before_counts: dict[str, int] = {
            old: _count_in_slide_text(source_pptx, old, slide_number)
            for old in active_replacements
        }

        matched_keys: list[str] = []

        ppt = comtypes.client.CreateObject("PowerPoint.Application")
        ppt.Visible = 1
        try:
            prs = ppt.Presentations.Open(
                str(source_pptx.resolve()),
                ReadOnly=False,
                WithWindow=False,
            )
            try:
                slide = prs.Slides(slide_number)
                for shape in slide.Shapes:
                    if not shape.HasTextFrame:
                        continue
                    tf = shape.TextFrame
                    if not tf.HasText:
                        continue
                    try:
                        tr = tf.TextRange
                        current_text = tr.Text
                    except Exception as exc:
                        # Cannot read this shape's text — skip without attempting
                        # an edit so we don't risk a false-positive match.
                        _LOG.debug("Cannot read text from shape: %s", exc)
                        continue
                    for old, new in active_replacements.items():
                        if old not in current_text:
                            continue
                        # _replace_all raises on COM error — fail closed.
                        _replace_all(tr, old, new)
                        if old not in matched_keys:
                            matched_keys.append(old)
                prs.SaveAs(str(output_path.resolve()))
            finally:
                prs.Close()
        except PowerPointComEditorError:
            raise
        except Exception as exc:
            raise PowerPointComEditorError(
                f"PowerPoint COM editing failed for {source_pptx}: {exc}"
            ) from exc
        finally:
            try:
                ppt.Quit()
            except Exception:
                pass

        # Build results.  For each matched key, verify the replacement persisted
        # by counting occurrences in the saved output file.
        results: list[ReplacementResult] = []
        for old, new in active_replacements.items():
            occ_before = before_counts[old]

            if old not in matched_keys:
                results.append(ReplacementResult(
                    requested=old,
                    replacement=new,
                    status=ReplacementStatus.NO_MATCH,
                    occurrences_before=occ_before,
                    occurrences_after=occ_before,
                    matched=False,
                    replaced=False,
                    verified=False,
                ))
                continue

            occ_after = _count_in_slide_text(output_path, old, slide_number)
            verified = occ_after == 0

            results.append(ReplacementResult(
                requested=old,
                replacement=new,
                status=(
                    ReplacementStatus.REPLACED_AND_VERIFIED
                    if verified
                    else ReplacementStatus.ERROR
                ),
                occurrences_before=occ_before,
                occurrences_after=occ_after,
                matched=True,
                replaced=True,
                verified=verified,
                error=(
                    None if verified else (
                        f"SaveAs succeeded but {old!r} still present "
                        f"{occ_after} time(s) in output (occurrences_before={occ_before})"
                    )
                ),
            ))

        return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_all(
    text_range: object,
    old: str,
    new: str,
    max_iterations: int = 500,
) -> None:
    """Replace all occurrences of *old* with *new* within *text_range*.

    Calls TextRange.Replace() in a loop until it returns None (no more matches).
    Parameters are positional because the COM interface names the second param
    ReplaceWhat (not ReplaceWith) and keyword calls silently fail.

    Any COM exception propagates to the caller — this function does NOT catch
    or swallow errors.  The caller is responsible for wrapping in
    PowerPointComEditorError where appropriate.
    """
    for _ in range(max_iterations):
        # Positional: Replace(FindWhat, ReplaceWhat, After, MatchCase, WholeWords)
        result = text_range.Replace(old, new, 0, _MSO_TRUE, _MSO_FALSE)
        if result is None:
            break
        if old in new:  # safety: prevent infinite loop when new contains old
            break


def _count_in_slide_text(pptx_path: Path, text: str, slide_number: int = 1) -> int:
    """Count occurrences of *text* across all text shape frames on *slide_number*.

    Uses python-pptx to read the OOXML directly, independent of the COM layer.
    This is used both for pre-edit baseline counts and post-edit verification.
    """
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    slide = prs.slides[slide_number - 1]
    total = 0
    for shape in slide.shapes:
        if shape.has_text_frame:
            total += shape.text_frame.text.count(text)
    return total


def _collect_text_targets(slide: object) -> list[TextTarget]:
    """Build a TextTarget list from all text-bearing shapes on a COM slide."""
    targets: list[TextTarget] = []

    for shape in slide.Shapes:
        try:
            if not shape.HasTextFrame:
                continue
            tf = shape.TextFrame
            if not tf.HasText:
                continue

            text = str(tf.TextRange.Text)

            ph_type: Optional[int] = None
            try:
                if shape.Type == _MSO_PLACEHOLDER:
                    ph_type = int(shape.PlaceholderFormat.Type)
            except Exception:
                pass

            para_count = 0
            try:
                # PowerPoint COM: TextRange.Paragraphs is a method, not a property
                para_count = int(tf.TextRange.Paragraphs().Count)
            except Exception:
                try:
                    para_count = int(tf.TextRange.Paragraphs.Count)
                except Exception:
                    pass

            bounds: Optional[tuple[float, float, float, float]] = None
            try:
                bounds = (
                    float(shape.Left),
                    float(shape.Top),
                    float(shape.Width),
                    float(shape.Height),
                )
            except Exception:
                pass

            targets.append(
                TextTarget(
                    shape_id=int(shape.Id),
                    shape_name=str(shape.Name),
                    current_text=text,
                    placeholder_type=ph_type,
                    paragraph_count=para_count,
                    text_bounds=bounds,
                )
            )
        except Exception as exc:
            _LOG.debug("Skipping shape during enumeration: %s", exc)
            continue

    return targets
