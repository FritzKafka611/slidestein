"""Tests for vision reranking sort order and result composition."""

from __future__ import annotations

import pytest

from slidestein.reranking.rubric import (
    DEFAULT_VISION_WEIGHTS,
    VisualCandidateAssessment,
    VisualRerankModelOutput,
    VisionRerankWeights,
    compute_visual_score,
)
from slidestein.reranking.result import VisionRankedCandidate, VisionRerankResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assessment(
    key: str,
    csf: int = 3,
    ccf: int = 3,
    vh: int = 3,
    af: int = 3,
    df: int = 3,
) -> VisualCandidateAssessment:
    return VisualCandidateAssessment(
        candidate_key=key,
        communication_structure_fit=csf,
        content_capacity_fit=ccf,
        visual_hierarchy=vh,
        argument_flow=af,
        density_fit=df,
        rationale="rationale",
        strengths=["s"],
        limitations=["l"],
    )


def _ranked(
    key: str,
    vision_rank: int,
    visual_score: float,
    hybrid_rank: int,
    hybrid_score: float = 0.6,
    slide_number: int = 1,
) -> VisionRankedCandidate:
    return VisionRankedCandidate(
        vision_rank=vision_rank,
        candidate_key=key,
        slide_id=f"slide-{key}",
        slide_number=slide_number,
        visual_score=visual_score,
        communication_structure_fit=3,
        content_capacity_fit=3,
        visual_hierarchy=3,
        argument_flow=3,
        density_fit=3,
        original_hybrid_rank=hybrid_rank,
        hybrid_score=hybrid_score,
        semantic_score=0.5,
        rationale="rationale",
        strengths=["s"],
        limitations=["l"],
    )


def _simulate_ranking(
    assessments: list[VisualCandidateAssessment],
    hybrid_ranks: dict[str, int],
    hybrid_scores: dict[str, float],
    slide_numbers: dict[str, int],
    weights: VisionRerankWeights = DEFAULT_VISION_WEIGHTS,
) -> list[VisionRankedCandidate]:
    """Simulate the ranking logic from VisionSlideRerankService."""
    scored = []
    for a in assessments:
        score = compute_visual_score(a, weights)
        scored.append((score, hybrid_ranks[a.candidate_key], a))

    scored.sort(key=lambda t: (-t[0], t[1]))

    ranked = []
    for vision_rank, (score, _, a) in enumerate(scored, 1):
        ranked.append(
            VisionRankedCandidate(
                vision_rank=vision_rank,
                candidate_key=a.candidate_key,
                slide_id=f"slide-{a.candidate_key}",
                slide_number=slide_numbers[a.candidate_key],
                visual_score=score,
                communication_structure_fit=a.communication_structure_fit,
                content_capacity_fit=a.content_capacity_fit,
                visual_hierarchy=a.visual_hierarchy,
                argument_flow=a.argument_flow,
                density_fit=a.density_fit,
                original_hybrid_rank=hybrid_ranks[a.candidate_key],
                hybrid_score=hybrid_scores[a.candidate_key],
                semantic_score=0.5,
                rationale=a.rationale,
                strengths=a.strengths,
                limitations=a.limitations,
            )
        )
    return ranked


# ---------------------------------------------------------------------------
# A. Higher visual_score wins even if hybrid rank is worse
# ---------------------------------------------------------------------------


class TestHigherVisualScoreWins:
    def test_higher_visual_score_beats_lower_despite_worse_hybrid_rank(self) -> None:
        # C1: hybrid rank 1 (better), but low visual scores
        # C2: hybrid rank 2 (worse), but high visual scores
        assessments = [
            _assessment("C1", csf=2, ccf=2, vh=2, af=2, df=2),
            _assessment("C2", csf=5, ccf=5, vh=5, af=5, df=5),
        ]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 1, "C2": 2},
            hybrid_scores={"C1": 0.9, "C2": 0.6},
            slide_numbers={"C1": 10, "C2": 14},
        )
        assert ranked[0].candidate_key == "C2"
        assert ranked[1].candidate_key == "C1"

    def test_vision_rank_1_is_highest_visual_score(self) -> None:
        assessments = [
            _assessment("C1", csf=3, ccf=3, vh=3, af=3, df=3),
            _assessment("C2", csf=5, ccf=5, vh=5, af=4, df=4),
            _assessment("C3", csf=4, ccf=4, vh=4, af=4, df=4),
        ]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 1, "C2": 2, "C3": 3},
            hybrid_scores={"C1": 0.9, "C2": 0.7, "C3": 0.8},
            slide_numbers={"C1": 1, "C2": 2, "C3": 3},
        )
        scores = [r.visual_score for r in ranked]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# B. Equal visual_score uses hybrid rank as tie-break
# ---------------------------------------------------------------------------


class TestTieBreakByHybridRank:
    def test_equal_visual_score_lower_hybrid_rank_wins(self) -> None:
        assessments = [
            _assessment("C1", csf=3, ccf=3, vh=3, af=3, df=3),
            _assessment("C2", csf=3, ccf=3, vh=3, af=3, df=3),
        ]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 1, "C2": 2},
            hybrid_scores={"C1": 0.8, "C2": 0.7},
            slide_numbers={"C1": 5, "C2": 6},
        )
        assert ranked[0].candidate_key == "C1"
        assert ranked[1].candidate_key == "C2"

    def test_equal_visual_score_second_candidate_with_better_hybrid_wins(self) -> None:
        # C2 has better hybrid rank (1) vs C1 (3)
        assessments = [
            _assessment("C1", csf=4, ccf=3, vh=3, af=3, df=3),
            _assessment("C2", csf=4, ccf=3, vh=3, af=3, df=3),
        ]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 3, "C2": 1},
            hybrid_scores={"C1": 0.6, "C2": 0.9},
            slide_numbers={"C1": 7, "C2": 8},
        )
        assert ranked[0].candidate_key == "C2"


# ---------------------------------------------------------------------------
# C. Hybrid score does NOT enter visual_score
# ---------------------------------------------------------------------------


class TestHybridScoreNotInVisualScore:
    def test_visual_score_unaffected_by_hybrid_score(self) -> None:
        """Two candidates with identical rubric scores but different hybrid scores
        must produce identical visual scores."""
        a1 = _assessment("C1", csf=4, ccf=3, vh=4, af=3, df=3)
        a2 = _assessment("C2", csf=4, ccf=3, vh=4, af=3, df=3)
        s1 = compute_visual_score(a1)
        s2 = compute_visual_score(a2)
        assert abs(s1 - s2) < 1e-9

    def test_visual_score_formula_uses_only_rubric_scores(self) -> None:
        a = _assessment("C1", csf=5, ccf=4, vh=3, af=4, df=5)
        w = DEFAULT_VISION_WEIGHTS
        expected = (5*0.30 + 4*0.25 + 3*0.20 + 4*0.15 + 5*0.10) / 5.0
        assert abs(compute_visual_score(a, w) - expected) < 1e-9


# ---------------------------------------------------------------------------
# D. Result score explanations match computed visual_score
# ---------------------------------------------------------------------------


class TestResultScoreConsistency:
    def test_ranked_candidate_visual_score_matches_rubric(self) -> None:
        assessments = [_assessment("C1", csf=5, ccf=4, vh=3, af=4, df=5)]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 1},
            hybrid_scores={"C1": 0.7},
            slide_numbers={"C1": 14},
        )
        r = ranked[0]
        recomputed = compute_visual_score(
            VisualCandidateAssessment(
                candidate_key=r.candidate_key,
                communication_structure_fit=r.communication_structure_fit,
                content_capacity_fit=r.content_capacity_fit,
                visual_hierarchy=r.visual_hierarchy,
                argument_flow=r.argument_flow,
                density_fit=r.density_fit,
                rationale="",
                strengths=[],
                limitations=[],
            )
        )
        assert abs(r.visual_score - recomputed) < 1e-9

    def test_all_ranked_candidates_scores_match_rubric(self) -> None:
        assessments = [
            _assessment("C1", csf=5, ccf=5, vh=5, af=5, df=5),
            _assessment("C2", csf=3, ccf=3, vh=3, af=3, df=3),
            _assessment("C3", csf=1, ccf=1, vh=1, af=1, df=1),
        ]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 1, "C2": 2, "C3": 3},
            hybrid_scores={"C1": 0.9, "C2": 0.7, "C3": 0.5},
            slide_numbers={"C1": 1, "C2": 2, "C3": 3},
        )
        for r in ranked:
            a = VisualCandidateAssessment(
                candidate_key=r.candidate_key,
                communication_structure_fit=r.communication_structure_fit,
                content_capacity_fit=r.content_capacity_fit,
                visual_hierarchy=r.visual_hierarchy,
                argument_flow=r.argument_flow,
                density_fit=r.density_fit,
                rationale="",
                strengths=[],
                limitations=[],
            )
            assert abs(r.visual_score - compute_visual_score(a)) < 1e-9


# ---------------------------------------------------------------------------
# E. Selected slide is vision rank #1
# ---------------------------------------------------------------------------


class TestSelectedSlideIsRankOne:
    def test_selected_slide_has_highest_visual_score(self) -> None:
        assessments = [
            _assessment("C1", csf=3, ccf=3, vh=3, af=3, df=3),
            _assessment("C2", csf=5, ccf=5, vh=5, af=5, df=5),
            _assessment("C3", csf=4, ccf=4, vh=4, af=4, df=4),
        ]
        ranked = _simulate_ranking(
            assessments,
            hybrid_ranks={"C1": 1, "C2": 2, "C3": 3},
            hybrid_scores={"C1": 0.9, "C2": 0.7, "C3": 0.8},
            slide_numbers={"C1": 1, "C2": 2, "C3": 3},
        )
        winner = ranked[0]
        assert winner.candidate_key == "C2"
        assert winner.vision_rank == 1
        for other in ranked[1:]:
            assert winner.visual_score >= other.visual_score
