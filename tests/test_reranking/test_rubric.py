"""Tests for VisionRerankWeights, VisualCandidateAssessment, VisualRerankModelOutput,
and compute_visual_score."""

from __future__ import annotations

import pytest

from slidestein.reranking.rubric import (
    DEFAULT_VISION_WEIGHTS,
    VisualCandidateAssessment,
    VisualRerankModelOutput,
    VisionRerankWeights,
    compute_visual_score,
)


# ---------------------------------------------------------------------------
# VisionRerankWeights — defaults and validation
# ---------------------------------------------------------------------------


def _assessment(key: str = "C1", **scores) -> VisualCandidateAssessment:
    defaults = dict(
        communication_structure_fit=3,
        content_capacity_fit=3,
        visual_hierarchy=3,
        argument_flow=3,
        density_fit=3,
        rationale="test rationale",
        strengths=["s1"],
        limitations=["l1"],
    )
    defaults.update(scores)
    return VisualCandidateAssessment(candidate_key=key, **defaults)


class TestVisionRerankWeights:
    def test_default_values(self) -> None:
        w = VisionRerankWeights()
        assert w.communication_structure_fit == 0.30
        assert w.content_capacity_fit == 0.25
        assert w.visual_hierarchy == 0.20
        assert w.argument_flow == 0.15
        assert w.density_fit == 0.10

    def test_default_weights_sum_to_one(self) -> None:
        w = VisionRerankWeights()
        total = (
            w.communication_structure_fit
            + w.content_capacity_fit
            + w.visual_hierarchy
            + w.argument_flow
            + w.density_fit
        )
        assert abs(total - 1.0) < 1e-9

    def test_is_frozen(self) -> None:
        w = VisionRerankWeights()
        with pytest.raises(Exception):
            w.communication_structure_fit = 0.5  # type: ignore[misc]

    def test_defaults_are_valid(self) -> None:
        VisionRerankWeights()  # must not raise

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            VisionRerankWeights(
                communication_structure_fit=-0.1,
                content_capacity_fit=0.35,
                visual_hierarchy=0.30,
                argument_flow=0.25,
                density_fit=0.20,
            )

    def test_sum_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="sum"):
            VisionRerankWeights(
                communication_structure_fit=0.20,
                content_capacity_fit=0.20,
                visual_hierarchy=0.20,
                argument_flow=0.10,
                density_fit=0.10,
            )  # sum = 0.80

    def test_sum_above_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="sum"):
            VisionRerankWeights(
                communication_structure_fit=0.40,
                content_capacity_fit=0.30,
                visual_hierarchy=0.20,
                argument_flow=0.15,
                density_fit=0.10,
            )  # sum = 1.15

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError):
            VisionRerankWeights(
                communication_structure_fit=float("nan"),
                content_capacity_fit=0.25,
                visual_hierarchy=0.20,
                argument_flow=0.15,
                density_fit=0.10,
            )

    def test_inf_rejected(self) -> None:
        with pytest.raises(ValueError):
            VisionRerankWeights(
                communication_structure_fit=float("inf"),
                content_capacity_fit=0.25,
                visual_hierarchy=0.20,
                argument_flow=0.15,
                density_fit=0.10,
            )


# ---------------------------------------------------------------------------
# VisualCandidateAssessment — score range validation
# ---------------------------------------------------------------------------


class TestVisualCandidateAssessment:
    def test_score_1_accepted(self) -> None:
        a = _assessment(communication_structure_fit=1)
        assert a.communication_structure_fit == 1

    def test_score_5_accepted(self) -> None:
        a = _assessment(density_fit=5)
        assert a.density_fit == 5

    def test_score_0_rejected(self) -> None:
        with pytest.raises(Exception):
            _assessment(communication_structure_fit=0)

    def test_score_6_rejected(self) -> None:
        with pytest.raises(Exception):
            _assessment(content_capacity_fit=6)

    def test_all_fields_populated(self) -> None:
        a = _assessment(
            "C2",
            communication_structure_fit=4,
            content_capacity_fit=3,
            visual_hierarchy=5,
            argument_flow=4,
            density_fit=3,
        )
        assert a.candidate_key == "C2"
        assert a.communication_structure_fit == 4
        assert a.content_capacity_fit == 3
        assert a.visual_hierarchy == 5
        assert a.argument_flow == 4
        assert a.density_fit == 3


# ---------------------------------------------------------------------------
# VisualRerankModelOutput — coverage validation
# ---------------------------------------------------------------------------


class TestVisualRerankModelOutput:
    def test_valid_output_accepted(self) -> None:
        out = VisualRerankModelOutput(
            assessments=[_assessment("C1"), _assessment("C2"), _assessment("C3")]
        )
        out.validate_coverage({"C1", "C2", "C3"})  # must not raise

    def test_reordered_assessments_accepted(self) -> None:
        out = VisualRerankModelOutput(
            assessments=[_assessment("C3"), _assessment("C1"), _assessment("C2")]
        )
        out.validate_coverage({"C1", "C2", "C3"})  # order does not matter

    def test_missing_candidate_rejected(self) -> None:
        out = VisualRerankModelOutput(
            assessments=[_assessment("C1"), _assessment("C3")]
        )
        with pytest.raises(ValueError, match="missing"):
            out.validate_coverage({"C1", "C2", "C3"})

    def test_duplicate_candidate_rejected(self) -> None:
        with pytest.raises(Exception):
            VisualRerankModelOutput(
                assessments=[_assessment("C1"), _assessment("C1"), _assessment("C2")]
            )

    def test_unknown_candidate_rejected(self) -> None:
        out = VisualRerankModelOutput(
            assessments=[_assessment("C1"), _assessment("C2"), _assessment("C4")]
        )
        with pytest.raises(ValueError, match="unknown"):
            out.validate_coverage({"C1", "C2", "C3"})

    def test_malformed_json_rejected(self) -> None:
        with pytest.raises(Exception):
            VisualRerankModelOutput.model_validate_json("not json at all")

    def test_fenced_json_parsed_after_strip(self) -> None:
        from slidestein.reranking.providers.sap_aicore import _strip_fences

        fenced = (
            "```json\n"
            '{"assessments": [{'
            '"candidate_key": "C1",'
            '"communication_structure_fit": 4,'
            '"content_capacity_fit": 3,'
            '"visual_hierarchy": 4,'
            '"argument_flow": 3,'
            '"density_fit": 4,'
            '"rationale": "test",'
            '"strengths": ["good"],'
            '"limitations": ["none"]'
            "}]}\n```"
        )
        stripped = _strip_fences(fenced)
        out = VisualRerankModelOutput.model_validate_json(stripped)
        assert len(out.assessments) == 1
        assert out.assessments[0].candidate_key == "C1"


# ---------------------------------------------------------------------------
# compute_visual_score
# ---------------------------------------------------------------------------


class TestComputeVisualScore:
    def test_all_fives_gives_one(self) -> None:
        a = _assessment(
            communication_structure_fit=5,
            content_capacity_fit=5,
            visual_hierarchy=5,
            argument_flow=5,
            density_fit=5,
        )
        assert abs(compute_visual_score(a) - 1.0) < 1e-9

    def test_all_ones_gives_point_two(self) -> None:
        a = _assessment(
            communication_structure_fit=1,
            content_capacity_fit=1,
            visual_hierarchy=1,
            argument_flow=1,
            density_fit=1,
        )
        assert abs(compute_visual_score(a) - 0.2) < 1e-9

    def test_exact_calculation(self) -> None:
        """(5*0.30 + 4*0.25 + 3*0.20 + 4*0.15 + 5*0.10) / 5 = 4.20/5 = 0.84"""
        a = _assessment(
            communication_structure_fit=5,
            content_capacity_fit=4,
            visual_hierarchy=3,
            argument_flow=4,
            density_fit=5,
        )
        w = VisionRerankWeights()
        expected = (5 * 0.30 + 4 * 0.25 + 3 * 0.20 + 4 * 0.15 + 5 * 0.10) / 5.0
        assert abs(compute_visual_score(a, w) - expected) < 1e-9

    def test_custom_weights(self) -> None:
        w = VisionRerankWeights(
            communication_structure_fit=0.50,
            content_capacity_fit=0.20,
            visual_hierarchy=0.15,
            argument_flow=0.10,
            density_fit=0.05,
        )
        a = _assessment(
            communication_structure_fit=5,
            content_capacity_fit=3,
            visual_hierarchy=3,
            argument_flow=3,
            density_fit=3,
        )
        expected = (5 * 0.50 + 3 * 0.20 + 3 * 0.15 + 3 * 0.10 + 3 * 0.05) / 5.0
        assert abs(compute_visual_score(a, w) - expected) < 1e-9

    def test_score_in_unit_interval(self) -> None:
        for score_val in [1, 2, 3, 4, 5]:
            a = _assessment(
                communication_structure_fit=score_val,
                content_capacity_fit=score_val,
                visual_hierarchy=score_val,
                argument_flow=score_val,
                density_fit=score_val,
            )
            s = compute_visual_score(a)
            assert 0.0 <= s <= 1.0, f"score {s} out of [0,1] for rubric value {score_val}"
