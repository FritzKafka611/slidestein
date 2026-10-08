"""SlideClassificationService — orchestrates PPTX slide → SlideSemanticProfile.

Pipeline inside classify_slide():
  1. build_slide_classification_input  — validate, extract text and structural metadata
  2. renderer.render_preview           — render PNG into a temporary directory
  3. classifier.classify               — Claude Vision structured output

The preview PNG is scoped to a TemporaryDirectory and deleted automatically
when the context exits.  The source PPTX is opened read-only and never modified.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from slidestein.classification.classifier import SlideClassifier
from slidestein.classification.input_builder import build_slide_classification_input
from slidestein.domain.models import SlideSemanticProfileV2
from slidestein.pptx.adapter import PPTMasterAdapter


class SlideClassificationService:
    """Orchestrates E2E classification of a single slide from a PPTX deck.

    Accepts injected dependencies so unit tests operate without
    PowerPoint, LibreOffice, or an Anthropic API key.

    Parameters
    ----------
    classifier:
        Any SlideClassifier implementation (AnthropicSlideClassifier or a test double).
    renderer:
        Any PPTMasterAdapter that implements render_preview.
    """

    def __init__(
        self,
        classifier: SlideClassifier,
        renderer: PPTMasterAdapter,
    ) -> None:
        self._classifier = classifier
        self._renderer = renderer

    def classify_slide(
        self,
        pptx_path: Path,
        slide_number: int,
        slide_id: str | None = None,
        existing_preview_path: Path | None = None,
    ) -> SlideSemanticProfileV2:
        """Classify slide_number in pptx_path and return its semantic profile.

        The source PPTX is opened read-only and never written to.  A temporary
        PNG preview is rendered unless existing_preview_path is provided and
        the file exists.

        Parameters
        ----------
        pptx_path:
            Path to the source PPTX.
        slide_number:
            1-indexed slide number.
        slide_id:
            Override the slide_id used in the classification input.  When None
            (default), the legacy ``make_slide_id`` formula is used.  Pass the
            UUID5 slide_id from an indexed SlideRecord for persistent flows.
        existing_preview_path:
            If set and the file exists, reuse this preview instead of rendering
            a new one.  Avoids unnecessary re-rendering for batch classification.

        Raises
        ------
        FileNotFoundError
            If pptx_path does not exist.
        ValueError
            If slide_number is out of range or the file is not a valid PPTX.
        RuntimeError
            If preview rendering fails.
        SlideClassificationError
            If the classifier fails for any reason.
        """
        pptx_path = pptx_path.resolve()

        if existing_preview_path is not None and existing_preview_path.exists():
            classification_input = build_slide_classification_input(
                pptx_path=pptx_path,
                slide_number=slide_number,
                preview_path=existing_preview_path,
                slide_id=slide_id,
            )
            return self._classifier.classify(classification_input)

        with TemporaryDirectory() as tmp:
            preview_png = Path(tmp) / f"slide_{slide_number:03d}.png"

            classification_input = build_slide_classification_input(
                pptx_path=pptx_path,
                slide_number=slide_number,
                preview_path=preview_png,
                slide_id=slide_id,
            )

            self._renderer.render_preview(pptx_path, slide_number, preview_png)

            return self._classifier.classify(classification_input)
