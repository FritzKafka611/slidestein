"""Tests for SAPAICoreSlotSemanticAnalyzer — all SDK calls patched."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from slidestein.slots.analysis_models import SlotAnalysisModelOutput
from slidestein.slots.models import NativeShapeDescriptor
from slidestein.slots.providers.sap_aicore import (
    SAPAICoreSlotSemanticAnalyzer,
    SlotAnalysisError,
)
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_analyzer() -> SAPAICoreSlotSemanticAnalyzer:
    return SAPAICoreSlotSemanticAnalyzer(
        ai_core_client=MagicMock(),
        model="test-model",
    )


def _make_descriptor(shape_id: int = 7) -> NativeShapeDescriptor:
    return NativeShapeDescriptor(
        shape_id=shape_id,
        shape_path=str(shape_id),
        shape_type="AUTO_SHAPE",
        x=0, y=0, width=7315200, height=685800,
        x_ratio=0.0, y_ratio=0.0, width_ratio=0.8, height_ratio=0.1,
        z_order=0,
        has_text=True,
        text="Title",
        is_placeholder=True,
        placeholder_type=15,
        placeholder_idx=0,
        is_group=False,
        is_table=False,
        has_text_frame=True,
        font_size_pt=28.0,
        can_edit_text=True,
        source_kind="placeholder",
    )


VALID_OUTPUT_JSON = json.dumps({
    "assessments": [{
        "candidate_key": "S1",
        "include_as_slot": True,
        "slot_role": "title",
        "semantic_label": "Slide title",
        "confidence": 0.95,
        "rationale": "Top spanning shape.",
    }],
    "analysis_summary": "A simple title slide.",
})


CANDIDATES = {"S1": _make_descriptor(7)}


# ---------------------------------------------------------------------------
# Call behaviour
# ---------------------------------------------------------------------------


class TestCallBehavior:
    def test_exactly_one_run_orchestration_call(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=VALID_OUTPUT_JSON) as mock_orch:
            analyzer.analyze(str(png), CANDIDATES)
        mock_orch.assert_called_once()


# ---------------------------------------------------------------------------
# Valid parsing
# ---------------------------------------------------------------------------


class TestValidParsing:
    def test_valid_json_returns_model_output(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=VALID_OUTPUT_JSON):
            result = analyzer.analyze(str(png), CANDIDATES)
        assert isinstance(result, SlotAnalysisModelOutput)

    def test_fenced_json_parsed_correctly(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        fenced = f"```json\n{VALID_OUTPUT_JSON}\n```"
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=fenced):
            result = analyzer.analyze(str(png), CANDIDATES)
        assert result.assessments[0].slot_role == SlotRole.TITLE


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------


class TestKeyValidation:
    def test_unknown_candidate_key_raises(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        output_with_invented_key = json.dumps({
            "assessments": [{
                "candidate_key": "S99",  # not in supplied candidates
                "include_as_slot": True,
                "slot_role": "title",
                "semantic_label": "Invented",
                "confidence": 0.9,
                "rationale": "Invented shape",
            }],
            "analysis_summary": "Test",
        })
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=output_with_invented_key):
            with pytest.raises(SlotAnalysisError, match="unknown"):
                analyzer.analyze(str(png), CANDIDATES)

    def test_duplicate_candidate_key_raises(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        dup_json = json.dumps({
            "assessments": [
                {"candidate_key": "S1", "include_as_slot": True,
                 "slot_role": "title", "semantic_label": "Title",
                 "confidence": 0.9, "rationale": "ok"},
                {"candidate_key": "S1", "include_as_slot": False,
                 "slot_role": "other_text", "semantic_label": "Dup",
                 "confidence": 0.5, "rationale": "dup"},
            ],
            "analysis_summary": "test",
        })
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=dup_json):
            with pytest.raises(SlotAnalysisError):
                analyzer.analyze(str(png), CANDIDATES)


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------


class TestErrorConditions:
    def test_malformed_json_raises_slot_analysis_error(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value="not valid json"):
            with pytest.raises(SlotAnalysisError):
                analyzer.analyze(str(png), CANDIDATES)

    def test_invalid_slot_role_raises(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        bad_role = json.dumps({
            "assessments": [{
                "candidate_key": "S1",
                "include_as_slot": True,
                "slot_role": "not_a_real_role",
                "semantic_label": "Title",
                "confidence": 0.9,
                "rationale": "ok",
            }],
            "analysis_summary": "test",
        })
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=bad_role):
            with pytest.raises(SlotAnalysisError):
                analyzer.analyze(str(png), CANDIDATES)

    def test_sdk_exception_wrapped(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration",
                          side_effect=RuntimeError("SDK failure")):
            with pytest.raises(SlotAnalysisError, match="SDK failure"):
                analyzer.analyze(str(png), CANDIDATES)

    def test_missing_preview_raises_slot_analysis_error(self):
        analyzer = _make_analyzer()
        with pytest.raises(SlotAnalysisError):
            analyzer.analyze("/nonexistent/preview.png", CANDIDATES)

    def test_error_message_contains_no_credentials(self, tmp_path):
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        analyzer._ai_core_client.client_secret = "SECRET_TOKEN_XYZ"
        with patch.object(analyzer, "_run_orchestration",
                          side_effect=RuntimeError("sdk error")):
            try:
                analyzer.analyze(str(png), CANDIDATES)
            except SlotAnalysisError as exc:
                assert "SECRET_TOKEN_XYZ" not in str(exc)


# ---------------------------------------------------------------------------
# Items 1+2: Exact coverage validation in provider
# ---------------------------------------------------------------------------


class TestExactCoverageValidation:
    def _setup(self, tmp_path, output_json: str, candidates: dict) -> SAPAICoreSlotSemanticAnalyzer:
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        patch.object(analyzer, "_run_orchestration", return_value=output_json).start()
        return analyzer

    def test_exact_coverage_accepted(self, tmp_path):
        candidates = {
            "S1": _make_descriptor(1),
            "S2": _make_descriptor(2),
            "S3": _make_descriptor(3),
        }
        output_json = json.dumps({
            "assessments": [
                {"candidate_key": "S1", "include_as_slot": True, "slot_role": "title",
                 "semantic_label": "T", "confidence": 0.9, "rationale": "r"},
                {"candidate_key": "S2", "include_as_slot": True, "slot_role": "body_text",
                 "semantic_label": "B", "confidence": 0.9, "rationale": "r"},
                {"candidate_key": "S3", "include_as_slot": True, "slot_role": "label",
                 "semantic_label": "L", "confidence": 0.9, "rationale": "r"},
            ],
            "analysis_summary": "OK",
        })
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=output_json):
            result = analyzer.analyze(str(png), candidates)
        assert len(result.assessments) == 3

    def test_missing_key_raises(self, tmp_path):
        candidates = {"S1": _make_descriptor(1), "S2": _make_descriptor(2), "S3": _make_descriptor(3)}
        # Only returns S1, S2 — missing S3
        output_json = json.dumps({
            "assessments": [
                {"candidate_key": "S1", "include_as_slot": True, "slot_role": "title",
                 "semantic_label": "T", "confidence": 0.9, "rationale": "r"},
                {"candidate_key": "S2", "include_as_slot": True, "slot_role": "body_text",
                 "semantic_label": "B", "confidence": 0.9, "rationale": "r"},
            ],
            "analysis_summary": "Truncated.",
        })
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=output_json):
            with pytest.raises(SlotAnalysisError, match="missing"):
                analyzer.analyze(str(png), candidates)

    def test_unknown_key_raises(self, tmp_path):
        candidates = {"S1": _make_descriptor(1), "S2": _make_descriptor(2)}
        # Returns S1, S2, S3 — S3 was not supplied
        output_json = json.dumps({
            "assessments": [
                {"candidate_key": "S1", "include_as_slot": True, "slot_role": "title",
                 "semantic_label": "T", "confidence": 0.9, "rationale": "r"},
                {"candidate_key": "S2", "include_as_slot": True, "slot_role": "body_text",
                 "semantic_label": "B", "confidence": 0.9, "rationale": "r"},
                {"candidate_key": "S3", "include_as_slot": True, "slot_role": "label",
                 "semantic_label": "L", "confidence": 0.9, "rationale": "r"},
            ],
            "analysis_summary": "Extra key.",
        })
        png = tmp_path / "preview.png"
        png.write_bytes(b"\x89PNG")
        analyzer = _make_analyzer()
        with patch.object(analyzer, "_run_orchestration", return_value=output_json):
            with pytest.raises(SlotAnalysisError, match="unknown"):
                analyzer.analyze(str(png), candidates)


# ---------------------------------------------------------------------------
# Item 11: max_tokens configuration
# ---------------------------------------------------------------------------


class TestMaxTokensConfiguration:
    def test_default_max_tokens_is_16384(self):
        analyzer = _make_analyzer()
        assert analyzer._max_tokens == 16384

    def test_custom_max_tokens_respected(self):
        analyzer = SAPAICoreSlotSemanticAnalyzer(
            ai_core_client=MagicMock(),
            model="test-model",
            max_tokens=8192,
        )
        assert analyzer._max_tokens == 8192
