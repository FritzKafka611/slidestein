"""SlideSteinPipeline — orchestrates all nine pipeline stages.

Each stage is a separate method that accepts a typed input model and returns
a typed output model.  All are stubbed as NotImplementedError so later tasks
can implement them one at a time without touching this file's structure.

Dependency rule: this module may import from domain, library, and pptx.
It must never embed consulting or PowerPoint logic itself.
"""

from __future__ import annotations

from pathlib import Path

from slidestein.config import Settings
from slidestein.domain.models import (
    DraftedContent,
    GeneratedSlide,
    ReviewResult,
    SelectedSlide,
    SlideBrief,
    SlideCandidate,
    UserRequest,
)
from slidestein.library.store import SlideLibrary
from slidestein.pptx.adapter import PPTMasterAdapter


class SlideSteinPipeline:
    def __init__(
        self,
        settings: Settings,
        library: SlideLibrary,
        ppt_adapter: PPTMasterAdapter,
    ) -> None:
        self._settings = settings
        self._library = library
        self._ppt = ppt_adapter

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, request: UserRequest) -> GeneratedSlide:
        """Execute all stages and return the finished slide."""
        brief = self._translate_to_brief(request)
        candidates = self._retrieve_candidates(brief)
        selected = self._select_best_candidate(candidates, brief)
        drafted = self._draft_content(selected, brief)
        generated = self._generate_pptx(drafted)
        reviewed = self._manager_review(generated, drafted)
        if not reviewed.review.approved:
            reviewed = self._apply_revision(reviewed, reviewed.review)
        return reviewed

    # ------------------------------------------------------------------
    # Stage 1 — brief translation
    # ------------------------------------------------------------------

    def _translate_to_brief(self, request: UserRequest) -> SlideBrief:
        """Call Claude to convert natural language into a SlideBrief."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Stage 2 — candidate retrieval
    # ------------------------------------------------------------------

    def _retrieve_candidates(self, brief: SlideBrief) -> list[SlideCandidate]:
        """Query the SlideLibrary for templates matching the brief."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Stage 3 — vision selection
    # ------------------------------------------------------------------

    def _select_best_candidate(
        self,
        candidates: list[SlideCandidate],
        brief: SlideBrief,
    ) -> SelectedSlide:
        """Render candidates and ask Claude Vision to pick the best structure."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Stage 4 — content drafting
    # ------------------------------------------------------------------

    def _draft_content(self, selected: SelectedSlide, brief: SlideBrief) -> DraftedContent:
        """Call Claude to fill each content slot while respecting max_chars."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Stage 5 — PPTX generation
    # ------------------------------------------------------------------

    def _generate_pptx(self, drafted: DraftedContent) -> GeneratedSlide:
        """Hand filled slots to PPTMasterAdapter and write an editable PPTX."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Stage 6 — manager review
    # ------------------------------------------------------------------

    def _manager_review(
        self,
        generated: GeneratedSlide,
        drafted: DraftedContent,
    ) -> GeneratedSlide:
        """Call Claude to review seven consulting-quality dimensions."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Stage 7 — one-shot revision (only if review fails)
    # ------------------------------------------------------------------

    def _apply_revision(
        self,
        generated: GeneratedSlide,
        review: ReviewResult,
    ) -> GeneratedSlide:
        """Apply the reviewer's instructions and regenerate — at most once."""
        raise NotImplementedError
