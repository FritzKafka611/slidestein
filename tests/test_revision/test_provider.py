"""Tests for SAPAICoreContentReviser (provider-level, _run_orchestration mocked) — v1.1."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from slidestein.revision.models import ContentRevisionModelOutput, RevisionChange
from slidestein.revision.providers.sap_aicore import (
    ContentRevisionGenerationError,
    SAPAICoreContentReviser,
    _strip_fences,
)
from tests.test_revision.conftest import make_brief, make_complete_draft

# v1.1 schema: status, changes (key/action/text), change_summary
VALID_OUTPUT_JSON = json.dumps({
    "status": "revised",
    "changes": [{"key": "K3", "action": "replace", "text": "Shorter revised chart title."}],
    "change_summary": "Tightened K3 to fit within capacity.",
})


def make_reviser() -> SAPAICoreContentReviser:
    return SAPAICoreContentReviser(
        ai_core_client=object(),
        model="claude-3.5-sonnet",
    )


MINIMAL_SLOT_SPECS = [
    {"key": "K3", "role": "exhibit_title", "label": "Chart", "action": "replace",
     "text": "Very long chart title.", "capacity_characters": 40, "capacity_utilization": 1.2,
     "max_lines_estimate": 1},
]


def _call_revise(gen, raw_output, target_keys=None):
    """Helper: call revise() with mocked _run_orchestration."""
    with patch.object(gen, "_run_orchestration", return_value=raw_output):
        return gen.revise(
            brief=make_brief(),
            source_material=None,
            slot_specs=MINIMAL_SLOT_SPECS,
            target_keys=target_keys or ["K3"],
            current_draft=make_complete_draft(),
            revision_feedback=[],
        )


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_plain_json():
    raw = '{"key": "val"}'
    assert _strip_fences(raw) == '{"key": "val"}'


def test_strip_fences_json_block():
    raw = '```json\n{"key": "val"}\n```'
    assert _strip_fences(raw) == '{"key": "val"}'


def test_strip_fences_plain_code_block():
    raw = '```\n{"key": "val"}\n```'
    assert _strip_fences(raw) == '{"key": "val"}'


# ---------------------------------------------------------------------------
# revise() — successful cases
# ---------------------------------------------------------------------------


def test_revise_valid_json_returns_output():
    gen = make_reviser()
    output = _call_revise(gen, VALID_OUTPUT_JSON)
    assert isinstance(output, ContentRevisionModelOutput)
    assert len(output.changes) == 1
    assert output.changes[0].key == "K3"
    assert output.changes[0].text == "Shorter revised chart title."


def test_revise_fenced_json_parsed_correctly():
    fenced = f"```json\n{VALID_OUTPUT_JSON}\n```"
    gen = make_reviser()
    output = _call_revise(gen, fenced)
    assert output.changes[0].key == "K3"


def test_revise_multiple_changes_parsed():
    multi = json.dumps({
        "status": "revised",
        "changes": [
            {"key": "K1", "action": "replace", "text": "New title."},
            {"key": "K3", "action": "replace", "text": "New chart title."},
        ],
        "change_summary": "Revised K1 and K3.",
    })
    gen = make_reviser()
    output = _call_revise(gen, multi, target_keys=["K1", "K3"])
    assert len(output.changes) == 2


def test_revise_blocked_status_parsed():
    blocked = json.dumps({
        "status": "blocked",
        "changes": [],
        "change_summary": "Cannot revise further.",
        "blocked_reason": "Text is already at minimum viable length.",
    })
    gen = make_reviser()
    output = _call_revise(gen, blocked)
    assert output.status == "blocked"
    assert output.blocked_reason is not None


def test_revise_calls_run_orchestration_exactly_once():
    gen = make_reviser()
    with patch.object(gen, "_run_orchestration", return_value=VALID_OUTPUT_JSON) as mock:
        gen.revise(
            brief=make_brief(), source_material=None,
            slot_specs=MINIMAL_SLOT_SPECS, target_keys=["K3"],
            current_draft=make_complete_draft(), revision_feedback=[],
        )
    mock.assert_called_once()


# ---------------------------------------------------------------------------
# revise() — failure cases
# ---------------------------------------------------------------------------


def test_revise_malformed_json_raises_generation_error():
    gen = make_reviser()
    with pytest.raises(ContentRevisionGenerationError, match="parse error"):
        _call_revise(gen, "not json at all")


def test_revise_invalid_schema_raises_generation_error():
    bad_json = json.dumps({"wrong_field": "value"})
    gen = make_reviser()
    with pytest.raises(ContentRevisionGenerationError):
        _call_revise(gen, bad_json)


def test_revise_sdk_exception_wrapped_as_generation_error():
    gen = make_reviser()
    with patch.object(gen, "_run_orchestration", side_effect=RuntimeError("Network error")):
        with pytest.raises(ContentRevisionGenerationError):
            gen.revise(
                brief=make_brief(), source_material=None,
                slot_specs=MINIMAL_SLOT_SPECS, target_keys=["K3"],
                current_draft=make_complete_draft(), revision_feedback=[],
            )


def test_revise_blank_text_in_replace_change_raises_generation_error():
    bad_json = json.dumps({
        "status": "revised",
        "changes": [{"key": "K3", "action": "replace", "text": "   "}],
        "change_summary": "Oops.",
    })
    gen = make_reviser()
    with pytest.raises(ContentRevisionGenerationError):
        _call_revise(gen, bad_json)


def test_revise_extra_fields_raise_generation_error():
    extra_json = json.dumps({
        "status": "revised",
        "changes": [{"key": "K3", "action": "replace", "text": "OK."}],
        "change_summary": "Done.",
        "unexpected_field": "value",
    })
    gen = make_reviser()
    with pytest.raises(ContentRevisionGenerationError):
        _call_revise(gen, extra_json)


def test_revise_error_message_contains_raw_response_excerpt():
    gen = make_reviser()
    with pytest.raises(ContentRevisionGenerationError) as exc_info:
        _call_revise(gen, "INVALID_GIBBERISH")
    assert "INVALID_GIBBERISH" in str(exc_info.value) or "parse error" in str(exc_info.value).lower()


def test_revise_error_message_has_no_secret_keywords():
    gen = make_reviser()
    with patch.object(gen, "_run_orchestration", side_effect=RuntimeError("some error")):
        with pytest.raises(ContentRevisionGenerationError) as exc_info:
            gen.revise(
                brief=make_brief(), source_material=None,
                slot_specs=MINIMAL_SLOT_SPECS, target_keys=["K3"],
                current_draft=make_complete_draft(), revision_feedback=[],
            )
    error_msg = str(exc_info.value).lower()
    assert "secret" not in error_msg
    assert "token" not in error_msg
    assert "password" not in error_msg
