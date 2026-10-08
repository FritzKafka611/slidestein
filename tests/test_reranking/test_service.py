"""Tests for VisionSlideRerankService — mocks all boundaries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.reranking.brief import VisualRerankBrief
from slidestein.reranking.candidates import VisualCandidateInput
from slidestein.reranking.result import VisionRerankResult
from slidestein.reranking.rubric import VisualCandidateAssessment, VisualRerankModelOutput
from slidestein.reranking.service import VisionSlideRerankService
from slidestein.retrieval.request import SlideRetrievalRequest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_hybrid_result(
    slide_id: str,
    deck_id: str,
    slide_number: int,
    rank: int,
    hybrid_score: float,
    semantic_score: float,
) -> MagicMock:
    r = MagicMock()
    r.slide_id = slide_id
    r.deck_id = deck_id
    r.slide_number = slide_number
    r.rank = rank
    r.hybrid_score = hybrid_score
    r.semantic_score = semantic_score
    return r


def _make_assessment(key: str, score: int = 3) -> VisualCandidateAssessment:
    return VisualCandidateAssessment(
        candidate_key=key,
        communication_structure_fit=score,
        content_capacity_fit=score,
        visual_hierarchy=score,
        argument_flow=score,
        density_fit=score,
        rationale="rationale",
        strengths=["strength"],
        limitations=["limitation"],
    )


def _make_slide_record(slide_id: str, preview: str) -> MagicMock:
    r = MagicMock()
    r.slide_id = slide_id
    r.preview_path = preview
    return r


def _build_service(
    hybrid_results,
    slide_records,
    model_output,
    preview_files_exist: bool = True,
) -> tuple[VisionSlideRerankService, MagicMock, MagicMock, MagicMock]:
    searcher = MagicMock()
    searcher.search.return_value = hybrid_results

    library = MagicMock()
    library.get_slide.side_effect = lambda sid: slide_records.get(sid)

    reranker = MagicMock()
    reranker.assess.return_value = model_output

    svc = VisionSlideRerankService(searcher, library, reranker)

    if preview_files_exist:
        with patch("slidestein.reranking.service.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            MockPath.side_effect = lambda p: _mock_path(p, exists=True)

    return svc, searcher, library, reranker


def _mock_path(p, exists: bool) -> MagicMock:
    m = MagicMock(spec=Path)
    m.__str__ = lambda self: str(p)
    m.exists.return_value = exists
    return m


def _default_results(n: int = 3):
    return [
        _make_hybrid_result(
            slide_id=f"slide-{i}",
            deck_id="deck-1",
            slide_number=i,
            rank=i,
            hybrid_score=1.0 - 0.1 * i,
            semantic_score=0.5,
        )
        for i in range(1, n + 1)
    ]


def _default_records(slide_ids, preview_dir="/previews"):
    return {
        sid: _make_slide_record(sid, f"{preview_dir}/{sid}.png")
        for sid in slide_ids
    }


def _default_model_output(keys):
    return VisualRerankModelOutput(
        assessments=[_make_assessment(k) for k in keys]
    )


# ---------------------------------------------------------------------------
# A. Candidate k validation
# ---------------------------------------------------------------------------


class TestCandidateKValidation:
    def test_candidate_k_1_rejected(self) -> None:
        svc = VisionSlideRerankService(MagicMock(), MagicMock(), MagicMock())
        with pytest.raises(ValueError, match="candidate_k"):
            svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=1)

    def test_candidate_k_9_rejected(self) -> None:
        svc = VisionSlideRerankService(MagicMock(), MagicMock(), MagicMock())
        with pytest.raises(ValueError, match="candidate_k"):
            svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=9)

    def test_candidate_k_2_accepted(self) -> None:
        results = _default_results(2)
        records = _default_records(["slide-1", "slide-2"])
        model_output = _default_model_output(["C1", "C2"])

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()
        reranker.assess.return_value = model_output

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            result = svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=2)
        assert isinstance(result, VisionRerankResult)

    def test_candidate_k_8_accepted(self) -> None:
        results = _default_results(8)
        slide_ids = [f"slide-{i}" for i in range(1, 9)]
        records = _default_records(slide_ids)
        candidate_keys = [f"C{i}" for i in range(1, 9)]
        model_output = _default_model_output(candidate_keys)

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()
        reranker.assess.return_value = model_output

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            result = svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=8)
        assert isinstance(result, VisionRerankResult)


# ---------------------------------------------------------------------------
# B. Hybrid search called with correct top_k
# ---------------------------------------------------------------------------


class TestHybridSearchTopK:
    def test_searcher_called_with_candidate_k_as_top_k(self) -> None:
        results = _default_results(5)
        records = _default_records([r.slide_id for r in results])
        model_output = _default_model_output([f"C{i}" for i in range(1, 6)])

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()
        reranker.assess.return_value = model_output

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=5)

        call_args = searcher.search.call_args[0][0]
        assert call_args.top_k == 5


# ---------------------------------------------------------------------------
# C. Preview path resolution fails fast
# ---------------------------------------------------------------------------


class TestPreviewFastFail:
    def test_missing_slide_in_library_raises_runtime_error(self) -> None:
        results = _default_results(3)
        records = _default_records(["slide-1", "slide-2"])  # slide-3 missing

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            with pytest.raises(RuntimeError):
                svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=3)

    def test_null_preview_path_raises_runtime_error(self) -> None:
        results = _default_results(2)
        record_with_null = _make_slide_record("slide-1", None)
        records = {"slide-1": record_with_null, "slide-2": _make_slide_record("slide-2", "/p2.png")}
        record_with_null.preview_path = None

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()

        svc = VisionSlideRerankService(searcher, library, reranker)
        with pytest.raises(RuntimeError, match="preview"):
            with patch.object(Path, "exists", return_value=True):
                svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=2)

    def test_nonexistent_preview_file_raises_runtime_error(self) -> None:
        results = _default_results(2)
        records = _default_records(["slide-1", "slide-2"])

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()

        svc = VisionSlideRerankService(searcher, library, reranker)
        with pytest.raises(RuntimeError, match="Preview file not found"):
            with patch.object(Path, "exists", return_value=False):
                svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=2)


# ---------------------------------------------------------------------------
# D. Single reranker.assess call
# ---------------------------------------------------------------------------


class TestSingleVisionCall:
    def test_reranker_assess_called_exactly_once(self) -> None:
        results = _default_results(3)
        records = _default_records([r.slide_id for r in results])
        model_output = _default_model_output(["C1", "C2", "C3"])

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()
        reranker.assess.return_value = model_output

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=3)

        assert reranker.assess.call_count == 1


# ---------------------------------------------------------------------------
# E. Candidate key assignment
# ---------------------------------------------------------------------------


class TestCandidateKeyAssignment:
    def test_candidates_assigned_c1_through_cn(self) -> None:
        results = _default_results(4)
        records = _default_records([r.slide_id for r in results])
        model_output = _default_model_output(["C1", "C2", "C3", "C4"])

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()
        reranker.assess.return_value = model_output

        captured = {}

        def capture_assess(brief, candidates):
            captured["keys"] = [c.candidate_key for c in candidates]
            return model_output

        reranker.assess.side_effect = capture_assess

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=4)

        assert captured["keys"] == ["C1", "C2", "C3", "C4"]


# ---------------------------------------------------------------------------
# F. Result structure
# ---------------------------------------------------------------------------


class TestResultStructure:
    def _run(self, n: int = 3) -> VisionRerankResult:
        results = _default_results(n)
        slide_ids = [r.slide_id for r in results]
        records = _default_records(slide_ids)
        model_output = _default_model_output([f"C{i}" for i in range(1, n + 1)])

        searcher = MagicMock()
        searcher.search.return_value = results
        library = MagicMock()
        library.get_slide.side_effect = lambda sid: records.get(sid)
        reranker = MagicMock()
        reranker.assess.return_value = model_output

        svc = VisionSlideRerankService(searcher, library, reranker)
        with patch.object(Path, "exists", return_value=True):
            return svc.rerank(SlideRetrievalRequest(query_text="test"), candidate_k=n)

    def test_result_has_selected_slide_id(self) -> None:
        r = self._run()
        assert r.selected_slide_id != ""

    def test_selected_is_vision_rank_1(self) -> None:
        r = self._run()
        winner = r.ranked_candidates[0]
        assert winner.vision_rank == 1
        assert r.selected_slide_id == winner.slide_id

    def test_ranked_candidates_has_all_entries(self) -> None:
        r = self._run(5)
        assert len(r.ranked_candidates) == 5

    def test_vision_rerank_version_populated(self) -> None:
        from slidestein.reranking.versions import VISION_RERANK_VERSION, VISION_RERANK_PROMPT_VERSION
        r = self._run()
        assert r.vision_rerank_version == VISION_RERANK_VERSION
        assert r.prompt_version == VISION_RERANK_PROMPT_VERSION
