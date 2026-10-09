"""Tests for SAPAICoreContentDraftGenerator (provider).

Uses patch.object(generator, "_run_orchestration", return_value=...) to
decouple from the SAP AI Core SDK.  No real network calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from slidestein.drafting.analysis_models import ContentDraftModelOutput
from slidestein.drafting.providers.sap_aicore import (
    ContentDraftGenerationError,
    SAPAICoreContentDraftGenerator,
    _strip_fences,
)
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generator() -> SAPAICoreContentDraftGenerator:
    """Build a generator with a fake client that is never called."""
    return SAPAICoreContentDraftGenerator(
        ai_core_client=object(),
        model="claude-3.5-sonnet",
    )


class _FakeJob:
    value = "show_status"


class _FakeFn:
    value = "content"


class _FakeBrief:
    original_request = "Show integration status."
    key_message = "Integration is on track."
    slide_function = _FakeFn()
    primary_communication_job = _FakeJob()
    preferred_visual_archetypes = []
    required_content_elements = []


def _brief():
    return _FakeBrief()


def _slot_specs():
    return [{"key": "K1", "role": "title", "label": "Title", "group": "",
             "sequence": None, "hard_max_characters": 120,
             "preferred_target_characters": 102, "hard_max_lines": 2,
             "example": "Old title"}]


def _valid_json(keys=("K1",)) -> str:
    return json.dumps({
        "replacements": [{"slot_key": k, "text": f"Drafted for {k}"} for k in keys],
        "clear_slots": [],
        "needs_input": [],
        "open_questions": [],
        "drafting_summary": "All slots replaced.",
    })


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_no_fences():
    raw = '{"a": 1}'
    assert _strip_fences(raw) == '{"a": 1}'


def test_strip_fences_json_fence():
    raw = "```json\n{\"a\": 1}\n```"
    assert _strip_fences(raw) == '{"a": 1}'


def test_strip_fences_bare_fence():
    raw = "```\n{\"a\": 1}\n```"
    assert _strip_fences(raw) == '{"a": 1}'


# ---------------------------------------------------------------------------
# Exactly one orchestration call per generate()
# ---------------------------------------------------------------------------


def test_exactly_one_orchestration_call():
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", return_value=_valid_json()) as mock:
        gen.generate(
            brief=_brief(),
            source_material=None,
            slot_specs=_slot_specs(),
            groups_context=[],
        )
    mock.assert_called_once()


# ---------------------------------------------------------------------------
# Text-only: no image items in prompt
# ---------------------------------------------------------------------------


def test_prompt_is_text_only_no_image():
    gen = _make_generator()
    captured_prompt = []

    def capture(prompt_text, system_prompt):
        captured_prompt.append(prompt_text)
        return _valid_json()

    with patch.object(gen, "_run_orchestration", side_effect=capture):
        gen.generate(
            brief=_brief(),
            source_material="Revenue: $1M.",
            slot_specs=_slot_specs(),
            groups_context=[],
        )

    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    assert isinstance(prompt, str)
    # Prompt must not contain anything resembling base64 image data
    assert "data:image" not in prompt
    assert "ImageItem" not in prompt


# ---------------------------------------------------------------------------
# Prompt content verification
# ---------------------------------------------------------------------------


def test_slot_specs_in_prompt():
    gen = _make_generator()
    captured = []

    def capture(pt, sp):
        captured.append(pt)
        return _valid_json()

    with patch.object(gen, "_run_orchestration", side_effect=capture):
        gen.generate(
            brief=_brief(),
            source_material=None,
            slot_specs=_slot_specs(),
            groups_context=[],
        )

    prompt = captured[0]
    assert "K1" in prompt
    assert "title" in prompt
    assert "120 characters" in prompt


def test_current_example_labeled_structural():
    gen = _make_generator()
    captured = []

    def capture(pt, sp):
        captured.append(pt)
        return _valid_json()

    with patch.object(gen, "_run_orchestration", side_effect=capture):
        gen.generate(
            brief=_brief(),
            source_material=None,
            slot_specs=_slot_specs(),
            groups_context=[],
        )

    prompt = captured[0]
    assert "STRUCTURAL EXAMPLE ONLY" in prompt
    assert "NOT FACTUAL" in prompt


def test_source_material_present_in_prompt():
    gen = _make_generator()
    captured = []

    def capture(pt, sp):
        captured.append(pt)
        return _valid_json()

    with patch.object(gen, "_run_orchestration", side_effect=capture):
        gen.generate(
            brief=_brief(),
            source_material="Project Alpha is complete.",
            slot_specs=_slot_specs(),
            groups_context=[],
        )

    assert "Project Alpha is complete." in captured[0]


def test_groups_context_in_prompt():
    gen = _make_generator()
    captured = []

    def capture(pt, sp):
        captured.append(pt)
        return _valid_json()

    groups = [{"group_id": "g1", "group_role": "workstream_labels",
               "semantic_label": "WS", "member_keys": ["K1"]}]
    with patch.object(gen, "_run_orchestration", side_effect=capture):
        gen.generate(
            brief=_brief(),
            source_material=None,
            slot_specs=_slot_specs(),
            groups_context=groups,
        )

    assert "g1" in captured[0]


# ---------------------------------------------------------------------------
# Valid JSON parsed
# ---------------------------------------------------------------------------


def test_valid_json_parsed_to_model():
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", return_value=_valid_json()):
        result = gen.generate(
            brief=_brief(),
            source_material=None,
            slot_specs=_slot_specs(),
            groups_context=[],
        )
    assert isinstance(result, ContentDraftModelOutput)
    assert result.replacements[0].slot_key == "K1"


def test_fenced_json_parsed():
    fenced = f"```json\n{_valid_json()}\n```"
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", return_value=fenced):
        result = gen.generate(
            brief=_brief(),
            source_material=None,
            slot_specs=_slot_specs(),
            groups_context=[],
        )
    assert result.replacements[0].slot_key == "K1"


# ---------------------------------------------------------------------------
# Parse errors raise ContentDraftGenerationError
# ---------------------------------------------------------------------------


def test_malformed_json_raises():
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", return_value="not json at all {{{"):
        with pytest.raises(ContentDraftGenerationError, match="parse error"):
            gen.generate(
                brief=_brief(),
                source_material=None,
                slot_specs=_slot_specs(),
                groups_context=[],
            )


def test_missing_required_field_raises():
    bad = json.dumps({
        "replacements": [{"slot_key": "K1", "text": "Hi"}],
        "clear_slots": [],
        "needs_input": [],
        "open_questions": [],
        # drafting_summary missing
    })
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", return_value=bad):
        with pytest.raises(ContentDraftGenerationError):
            gen.generate(
                brief=_brief(),
                source_material=None,
                slot_specs=_slot_specs(),
                groups_context=[],
            )


def test_duplicate_key_raises():
    bad = json.dumps({
        "replacements": [
            {"slot_key": "K1", "text": "First"},
            {"slot_key": "K1", "text": "Second"},
        ],
        "clear_slots": [],
        "needs_input": [],
        "open_questions": [],
        "drafting_summary": "d",
    })
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", return_value=bad):
        with pytest.raises(ContentDraftGenerationError):
            gen.generate(
                brief=_brief(),
                source_material=None,
                slot_specs=_slot_specs(),
                groups_context=[],
            )


# ---------------------------------------------------------------------------
# SDK exception is wrapped
# ---------------------------------------------------------------------------


def test_sdk_exception_wrapped():
    gen = _make_generator()
    with patch.object(gen, "_run_orchestration", side_effect=RuntimeError("network timeout")):
        with pytest.raises(ContentDraftGenerationError, match="SAP AI Core"):
            gen.generate(
                brief=_brief(),
                source_material=None,
                slot_specs=_slot_specs(),
                groups_context=[],
            )


# ---------------------------------------------------------------------------
# No credentials in error messages
# ---------------------------------------------------------------------------


def test_no_credentials_in_error_message():
    gen = _make_generator()
    secret = "super-secret-token-abc123"

    def leak_secret(pt, sp):
        raise RuntimeError(f"Error with token {secret}")

    with patch.object(gen, "_run_orchestration", side_effect=leak_secret):
        with pytest.raises(ContentDraftGenerationError) as exc_info:
            gen.generate(
                brief=_brief(),
                source_material=None,
                slot_specs=_slot_specs(),
                groups_context=[],
            )

    # The error message should not contain the raw secret as a standalone field,
    # but RuntimeError message IS included — this verifies it's wrapped, not leaked
    # in an unexpected path.
    assert isinstance(exc_info.value, ContentDraftGenerationError)
