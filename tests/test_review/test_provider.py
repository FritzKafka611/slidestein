"""Tests for SAPAICoreManagerReviewer — patch _run_orchestration (v1.1)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from slidestein.review.providers.sap_aicore import (
    ManagerReviewGenerationError,
    SAPAICoreManagerReviewer,
)
from tests.test_review.conftest import make_brief, make_model_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reviewer() -> SAPAICoreManagerReviewer:
    return SAPAICoreManagerReviewer(
        ai_core_client=object(),
        model="claude-3.5-sonnet",
    )


def _valid_json() -> str:
    dim = {"score": 4, "rationale": "Good."}
    data = {
        "recommendation": "approve",
        "answer_first_title": dim,
        "core_message_clarity": dim,
        "vertical_logic": dim,
        "exhibit_title_consistency": dim,
        "mece_structure": dim,
        "content_density": dim,
        "executive_summary": "Overall a solid draft.",
    }
    return json.dumps(data)


def _fenced_json() -> str:
    return "```json\n" + _valid_json() + "\n```"


_SLOT_SPECS = [
    {"key": "K1", "role": "title", "label": "Title", "action": "replace",
     "text": "Digital cost focus.",
     "character_count": 19, "capacity_characters": 70, "capacity_utilization": 0.27,
     "explicit_line_count": 1, "max_lines_estimate": 1,
     "group_id": None, "sequence_index": None},
]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_json_returns_model_output() -> None:
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=_valid_json()):
        output = gen.review(make_brief(), None, _SLOT_SPECS)
    assert output.recommendation == "approve"


def test_fenced_json_parsed_correctly() -> None:
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=_fenced_json()):
        output = gen.review(make_brief(), None, _SLOT_SPECS)
    assert output.recommendation == "approve"


def test_run_orchestration_called_exactly_once() -> None:
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=_valid_json()) as mock_orch:
        gen.review(make_brief(), None, _SLOT_SPECS)
    mock_orch.assert_called_once()


def test_group_descriptions_accepted_as_kwarg() -> None:
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=_valid_json()):
        output = gen.review(
            make_brief(), None, _SLOT_SPECS,
            group_descriptions=[{"group_id": "g1", "group_role": "row", "semantic_label": "Row 1",
                                  "member_keys": ["K1"], "sequence_index": 0}],
        )
    assert output.recommendation == "approve"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_invalid_score_raises_generation_error() -> None:
    dim = {"score": 99, "rationale": "Out of range."}
    data = {
        "recommendation": "approve",
        "answer_first_title": dim,
        "core_message_clarity": dim,
        "vertical_logic": dim,
        "exhibit_title_consistency": dim,
        "mece_structure": dim,
        "content_density": dim,
        "executive_summary": "Good.",
    }
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=json.dumps(data)):
        with pytest.raises(ManagerReviewGenerationError):
            gen.review(make_brief(), None, _SLOT_SPECS)


def test_invalid_recommendation_raises_generation_error() -> None:
    dim = {"score": 4, "rationale": "OK."}
    data = {
        "recommendation": "reject",  # invalid
        "answer_first_title": dim,
        "core_message_clarity": dim,
        "vertical_logic": dim,
        "exhibit_title_consistency": dim,
        "mece_structure": dim,
        "content_density": dim,
        "executive_summary": "Good.",
    }
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=json.dumps(data)):
        with pytest.raises(ManagerReviewGenerationError):
            gen.review(make_brief(), None, _SLOT_SPECS)


def test_malformed_json_raises_generation_error_with_raw() -> None:
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value="not json at all"):
        with pytest.raises(ManagerReviewGenerationError, match="Raw response"):
            gen.review(make_brief(), None, _SLOT_SPECS)


def test_sdk_exception_wrapped_as_generation_error() -> None:
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", side_effect=RuntimeError("SDK went bang")):
        with pytest.raises(ManagerReviewGenerationError, match="SAP AI Core"):
            gen.review(make_brief(), None, _SLOT_SPECS)


def test_error_message_safe_no_credentials() -> None:
    """SDK exception type is reported; str(exc) is NOT interpolated."""
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration",
                      side_effect=RuntimeError("connection refused")):
        try:
            gen.review(make_brief(), None, _SLOT_SPECS)
        except ManagerReviewGenerationError as exc:
            msg = str(exc)
            assert "SAP AI Core" in msg
            assert "RuntimeError" in msg
            # str(exc) content must NOT be in the message
            assert "connection refused" not in msg
            # No credentials
            assert "client_secret" not in msg
            assert "access_token" not in msg


def test_error_message_does_not_include_arbitrary_exc_string() -> None:
    """Provider must not embed arbitrary exception messages."""
    gen = _make_reviewer()
    sentinel = "super_secret_credential_xyz_12345"
    with patch.object(gen, "_run_orchestration",
                      side_effect=RuntimeError(sentinel)):
        try:
            gen.review(make_brief(), None, _SLOT_SPECS)
        except ManagerReviewGenerationError as exc:
            assert sentinel not in str(exc)


def test_extra_fields_forbidden_triggers_generation_error() -> None:
    dim = {"score": 4, "rationale": "OK."}
    data = {
        "recommendation": "approve",
        "answer_first_title": dim,
        "core_message_clarity": dim,
        "vertical_logic": dim,
        "exhibit_title_consistency": dim,
        "mece_structure": dim,
        "content_density": dim,
        "executive_summary": "Good.",
        "surprise_field": "bad",
    }
    gen = _make_reviewer()
    with patch.object(gen, "_run_orchestration", return_value=json.dumps(data)):
        with pytest.raises(ManagerReviewGenerationError):
            gen.review(make_brief(), None, _SLOT_SPECS)


def test_deployment_id_cached_after_first_call() -> None:
    gen = _make_reviewer()

    mock_client = MagicMock()
    gen._ai_core_client = mock_client

    mock_deployment = MagicMock()
    mock_deployment.scenario_id = "orchestration"
    mock_deployment.id = "dep-123"

    mock_client.deployment.query.return_value = MagicMock(resources=[mock_deployment])

    d1 = gen._get_orchestration_deployment_id()
    d2 = gen._get_orchestration_deployment_id()

    assert d1 == d2 == "dep-123"
    mock_client.deployment.query.assert_called_once()
