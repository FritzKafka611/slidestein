"""Tests for ShapeSemanticAssessment and SlotAnalysisModelOutput (Vision output models)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from slidestein.slots.analysis_models import (
    ShapeSemanticAssessment,
    SlotAnalysisModelOutput,
)
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assessment(**kwargs) -> ShapeSemanticAssessment:
    defaults = dict(
        candidate_key="S1",
        include_as_slot=True,
        slot_role=SlotRole.TITLE,
        semantic_label="Slide title",
        group_key=None,
        group_role=None,
        sequence_index=None,
        confidence=0.95,
        rationale="Large top-spanning shape.",
    )
    defaults.update(kwargs)
    return ShapeSemanticAssessment(**defaults)


def _make_output(**kwargs) -> SlotAnalysisModelOutput:
    defaults = dict(
        assessments=[_make_assessment()],
        analysis_summary="One title shape detected.",
    )
    defaults.update(kwargs)
    return SlotAnalysisModelOutput(**defaults)


# ---------------------------------------------------------------------------
# ShapeSemanticAssessment
# ---------------------------------------------------------------------------


class TestShapeSemanticAssessment:
    def test_valid_assessment_accepted(self):
        a = _make_assessment()
        assert a.candidate_key == "S1"
        assert a.slot_role == SlotRole.TITLE
        assert a.confidence == 0.95

    def test_confidence_zero_accepted(self):
        a = _make_assessment(confidence=0.0)
        assert a.confidence == 0.0

    def test_confidence_one_accepted(self):
        a = _make_assessment(confidence=1.0)
        assert a.confidence == 1.0

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError, match="confidence"):
            _make_assessment(confidence=-0.01)

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError, match="confidence"):
            _make_assessment(confidence=1.01)

    def test_sequence_index_zero_accepted(self):
        a = _make_assessment(sequence_index=0)
        assert a.sequence_index == 0

    def test_sequence_index_negative_rejected(self):
        with pytest.raises(ValidationError, match="sequence_index"):
            _make_assessment(sequence_index=-1)

    def test_group_key_optional(self):
        a = _make_assessment(group_key=None)
        assert a.group_key is None

    def test_group_key_with_value(self):
        a = _make_assessment(group_key="workstream_1", group_role="workstream")
        assert a.group_key == "workstream_1"

    def test_include_as_slot_false(self):
        a = _make_assessment(include_as_slot=False, slot_role=SlotRole.OTHER_TEXT)
        assert a.include_as_slot is False

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            _make_assessment(phantom_field="bad")  # type: ignore[call-arg]

    def test_all_slot_role_values_accepted(self):
        for role in SlotRole:
            a = _make_assessment(slot_role=role)
            assert a.slot_role == role


# ---------------------------------------------------------------------------
# SlotAnalysisModelOutput
# ---------------------------------------------------------------------------


class TestSlotAnalysisModelOutput:
    def test_valid_output_accepted(self):
        out = _make_output()
        assert len(out.assessments) == 1
        assert out.analysis_summary != ""

    def test_empty_assessments_accepted(self):
        out = _make_output(assessments=[])
        assert out.assessments == []

    def test_multiple_assessments_with_unique_keys_accepted(self):
        a1 = _make_assessment(candidate_key="S1")
        a2 = _make_assessment(candidate_key="S2", slot_role=SlotRole.BODY_TEXT)
        out = _make_output(assessments=[a1, a2])
        assert len(out.assessments) == 2

    def test_duplicate_candidate_key_rejected(self):
        a1 = _make_assessment(candidate_key="S1")
        a2 = _make_assessment(candidate_key="S1", slot_role=SlotRole.BODY_TEXT)
        with pytest.raises(ValidationError, match="Duplicate candidate_key"):
            _make_output(assessments=[a1, a2])

    def test_unknown_field_in_output_rejected(self):
        with pytest.raises(ValidationError):
            SlotAnalysisModelOutput(
                assessments=[],
                analysis_summary="Test",
                phantom_field="bad",  # type: ignore[call-arg]
            )

    def test_unknown_field_in_assessment_rejected(self):
        with pytest.raises(ValidationError):
            SlotAnalysisModelOutput(
                assessments=[{
                    "candidate_key": "S1",
                    "include_as_slot": True,
                    "slot_role": "title",
                    "semantic_label": "Title",
                    "confidence": 0.9,
                    "rationale": "ok",
                    "phantom": "bad",
                }],
                analysis_summary="test",
            )

    def test_json_parse_valid(self):
        payload = {
            "assessments": [{
                "candidate_key": "S1",
                "include_as_slot": True,
                "slot_role": "title",
                "semantic_label": "Slide title",
                "confidence": 0.95,
                "rationale": "Top shape.",
            }],
            "analysis_summary": "Single title slide.",
        }
        out = SlotAnalysisModelOutput.model_validate_json(json.dumps(payload))
        assert out.assessments[0].slot_role == SlotRole.TITLE

    def test_json_parse_invalid_slot_role(self):
        payload = {
            "assessments": [{
                "candidate_key": "S1",
                "include_as_slot": True,
                "slot_role": "not_a_real_role",
                "semantic_label": "Title",
                "confidence": 0.9,
                "rationale": "ok",
            }],
            "analysis_summary": "test",
        }
        with pytest.raises(ValidationError):
            SlotAnalysisModelOutput.model_validate_json(json.dumps(payload))


# ---------------------------------------------------------------------------
# Application-ownership: Vision cannot override shape_id, geometry, or editable
# ---------------------------------------------------------------------------


class TestApplicationOwnership:
    def test_assessment_has_no_shape_id_field(self):
        # ShapeSemanticAssessment must NOT have shape_id — it uses candidate_key
        with pytest.raises((ValidationError, TypeError)):
            ShapeSemanticAssessment(
                candidate_key="S1",
                include_as_slot=True,
                slot_role=SlotRole.TITLE,
                semantic_label="Title",
                confidence=0.9,
                rationale="ok",
                shape_id=99,  # not a valid field
            )

    def test_assessment_has_no_geometry_field(self):
        with pytest.raises((ValidationError, TypeError)):
            ShapeSemanticAssessment(
                candidate_key="S1",
                include_as_slot=True,
                slot_role=SlotRole.TITLE,
                semantic_label="Title",
                confidence=0.9,
                rationale="ok",
                x=100,  # not a valid field
            )

    def test_assessment_has_no_editable_override(self):
        with pytest.raises((ValidationError, TypeError)):
            ShapeSemanticAssessment(
                candidate_key="S1",
                include_as_slot=True,
                slot_role=SlotRole.TITLE,
                semantic_label="Title",
                confidence=0.9,
                rationale="ok",
                editable=False,  # not a valid field
            )
