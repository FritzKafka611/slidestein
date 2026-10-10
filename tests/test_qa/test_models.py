"""Domain model validator tests for M8 Visual QA."""

import pytest
from pydantic import ValidationError

from slidestein.qa.models import (
    NativeCheckStatus,
    NativeCheckType,
    NativeVisualCheck,
    VisualDimensionAssessment,
    VisualQAIssue,
    VisualQAModelOutput,
    VisualQAResult,
)
from slidestein.qa.versions import VISUAL_QA_PROMPT_VERSION, VISUAL_QA_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# VisualDimensionAssessment
# ---------------------------------------------------------------------------


def test_dimension_score_1_accepted():
    d = VisualDimensionAssessment(score=1, rationale="Poor")
    assert d.score == 1


def test_dimension_score_5_accepted():
    d = VisualDimensionAssessment(score=5, rationale="Excellent")
    assert d.score == 5


def test_dimension_score_3_accepted():
    d = VisualDimensionAssessment(score=3, rationale="OK")
    assert d.score == 3


def test_dimension_score_0_rejected():
    with pytest.raises(ValidationError):
        VisualDimensionAssessment(score=0, rationale="Bad")


def test_dimension_score_6_rejected():
    with pytest.raises(ValidationError):
        VisualDimensionAssessment(score=6, rationale="Too high")


def test_dimension_blank_rationale_rejected():
    with pytest.raises(ValidationError):
        VisualDimensionAssessment(score=3, rationale="   ")


def test_dimension_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        VisualDimensionAssessment(score=3, rationale="OK", unknown_field="x")


# ---------------------------------------------------------------------------
# VisualQAIssue
# ---------------------------------------------------------------------------


def test_issue_critical_severity_accepted():
    VisualQAIssue(
        severity="critical",
        category="text_fit_and_clipping",
        issue="Text clipped",
        evidence="Title cut off at edge",
        recommendation="Reduce font size",
    )


def test_issue_minor_severity_accepted():
    VisualQAIssue(
        severity="minor",
        category="balance_and_whitespace",
        issue="Slight imbalance",
        evidence="Left side slightly heavy",
        recommendation="Adjust margins",
    )


def test_issue_invalid_severity_rejected():
    with pytest.raises(ValidationError):
        VisualQAIssue(
            severity="moderate",
            category="text_fit_and_clipping",
            issue="x",
            evidence="y",
            recommendation="z",
        )


def test_issue_invalid_category_rejected():
    with pytest.raises(ValidationError):
        VisualQAIssue(
            severity="major",
            category="content_quality",
            issue="x",
            evidence="y",
            recommendation="z",
        )


def test_issue_all_six_categories_accepted():
    cats = [
        "text_fit_and_clipping",
        "visual_hierarchy",
        "alignment_and_spacing",
        "balance_and_whitespace",
        "typography_and_style_consistency",
        "overall_readability",
    ]
    for cat in cats:
        VisualQAIssue(
            severity="minor",
            category=cat,
            issue="x",
            evidence="y",
            recommendation="z",
        )


def test_issue_slot_keys_default_empty():
    iss = VisualQAIssue(
        severity="minor",
        category="visual_hierarchy",
        issue="x",
        evidence="y",
        recommendation="z",
    )
    assert iss.slot_keys == []


def test_issue_slot_keys_populated():
    iss = VisualQAIssue(
        severity="major",
        category="alignment_and_spacing",
        slot_keys=["K1", "K3"],
        issue="x",
        evidence="y",
        recommendation="z",
    )
    assert iss.slot_keys == ["K1", "K3"]


def test_issue_blank_issue_field_rejected():
    with pytest.raises(ValidationError):
        VisualQAIssue(
            severity="minor",
            category="visual_hierarchy",
            issue="",
            evidence="y",
            recommendation="z",
        )


def test_issue_blank_evidence_rejected():
    with pytest.raises(ValidationError):
        VisualQAIssue(
            severity="minor",
            category="visual_hierarchy",
            issue="x",
            evidence="  ",
            recommendation="z",
        )


# ---------------------------------------------------------------------------
# VisualQAModelOutput
# ---------------------------------------------------------------------------


def _make_dim(score: int = 4) -> dict:
    return {"score": score, "rationale": "OK"}


def _make_valid_output(**overrides) -> dict:
    base = {
        "recommendation": "pass",
        "text_fit_and_clipping": _make_dim(5),
        "visual_hierarchy": _make_dim(4),
        "alignment_and_spacing": _make_dim(4),
        "balance_and_whitespace": _make_dim(4),
        "typography_and_style_consistency": _make_dim(4),
        "overall_readability": _make_dim(4),
        "issues": [],
        "executive_summary": "Looks great.",
    }
    base.update(overrides)
    return base


def test_model_output_pass_accepted():
    out = VisualQAModelOutput.model_validate(_make_valid_output(recommendation="pass"))
    assert out.recommendation == "pass"


def test_model_output_revise_accepted():
    out = VisualQAModelOutput.model_validate(_make_valid_output(recommendation="revise"))
    assert out.recommendation == "revise"


def test_model_output_invalid_recommendation():
    with pytest.raises(ValidationError):
        VisualQAModelOutput.model_validate(_make_valid_output(recommendation="approve"))


def test_model_output_unknown_recommendation():
    with pytest.raises(ValidationError):
        VisualQAModelOutput.model_validate(_make_valid_output(recommendation="unknown"))


def test_model_output_extra_fields_forbidden():
    data = _make_valid_output()
    data["average_score"] = 4.5
    with pytest.raises(ValidationError):
        VisualQAModelOutput.model_validate(data)


def test_model_output_blank_summary_rejected():
    with pytest.raises(ValidationError):
        VisualQAModelOutput.model_validate(_make_valid_output(executive_summary=""))


# ---------------------------------------------------------------------------
# NativeVisualCheck
# ---------------------------------------------------------------------------


def test_native_check_pass():
    chk = NativeVisualCheck(
        check_type=NativeCheckType.OUTSIDE_SLIDE_BOUNDS,
        slot_key="K1",
        status=NativeCheckStatus.PASS,
        details="Within bounds",
    )
    assert chk.status == NativeCheckStatus.PASS


def test_native_check_fail():
    chk = NativeVisualCheck(
        check_type=NativeCheckType.TEXT_OVERFLOW,
        slot_key="K3",
        status=NativeCheckStatus.FAIL,
        details="Overflows by 20pt",
    )
    assert chk.status == NativeCheckStatus.FAIL


def test_native_check_unknown():
    chk = NativeVisualCheck(
        check_type=NativeCheckType.TEXT_OVERFLOW,
        slot_key="K2",
        status=NativeCheckStatus.UNKNOWN,
        details="COM not available",
    )
    assert chk.status == NativeCheckStatus.UNKNOWN


def test_native_check_no_slot_key():
    chk = NativeVisualCheck(
        check_type=NativeCheckType.RENDERING_IDENTITY,
        slot_key=None,
        status=NativeCheckStatus.PASS,
        details="Slide resolved",
    )
    assert chk.slot_key is None


# ---------------------------------------------------------------------------
# VisualQAResult
# ---------------------------------------------------------------------------


def test_result_schema_version_default():
    result = VisualQAResult(
        slide_id="sid",
        deck_id=None,
        slide_number=2,
        resolved_generated_slide_number=2,
        recommendation="pass",
        text_fit_and_clipping=VisualDimensionAssessment(score=5, rationale="Good"),
        visual_hierarchy=VisualDimensionAssessment(score=4, rationale="Good"),
        alignment_and_spacing=VisualDimensionAssessment(score=4, rationale="Good"),
        balance_and_whitespace=VisualDimensionAssessment(score=4, rationale="Good"),
        typography_and_style_consistency=VisualDimensionAssessment(score=4, rationale="Good"),
        overall_readability=VisualDimensionAssessment(score=4, rationale="Good"),
        average_score=4.1667,
        executive_summary="Good.",
        generated_render_path="outputs/m8/generated.png",
        template_render_path="outputs/m8/template.png",
        overlay_render_path="outputs/m8/overlay.png",
    )
    assert result.schema_version == VISUAL_QA_SCHEMA_VERSION
    assert result.prompt_version == VISUAL_QA_PROMPT_VERSION


def test_result_json_round_trip():
    result = VisualQAResult(
        slide_id="sid",
        deck_id="did",
        slide_number=2,
        resolved_generated_slide_number=2,
        recommendation="revise",
        text_fit_and_clipping=VisualDimensionAssessment(score=2, rationale="Clipped"),
        visual_hierarchy=VisualDimensionAssessment(score=3, rationale="OK"),
        alignment_and_spacing=VisualDimensionAssessment(score=3, rationale="OK"),
        balance_and_whitespace=VisualDimensionAssessment(score=3, rationale="OK"),
        typography_and_style_consistency=VisualDimensionAssessment(score=3, rationale="OK"),
        overall_readability=VisualDimensionAssessment(score=3, rationale="OK"),
        average_score=2.8333,
        executive_summary="Needs work.",
        generated_render_path="p1",
        template_render_path="p2",
        overlay_render_path="p3",
    )
    restored = VisualQAResult.model_validate_json(result.model_dump_json())
    assert restored.recommendation == "revise"
    assert restored.average_score == 2.8333
    assert restored.slide_id == "sid"
