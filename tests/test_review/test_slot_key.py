"""Tests for K-key mapping contract — reuse of M5.3 build_slot_key_mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.drafting.service import build_slot_key_mapping
from slidestein.review.errors import ManagerReviewError
from slidestein.review.models import ManagerReviewIssue, ManagerReviewRequest
from slidestein.review.service import ManagerReviewService
from tests.test_review.conftest import (
    make_brief,
    make_complete_draft,
    make_model_output,
    make_slot,
    make_slot_map,
)


def _make_service(mock_output=None):
    reviewer = MagicMock()
    reviewer.review.return_value = mock_output or make_model_output()
    return ManagerReviewService(reviewer=reviewer), reviewer


def test_slot_key_mapping_matches_drafting_service() -> None:
    slot_map = make_slot_map()
    direct = build_slot_key_mapping(slot_map.slots)
    svc, reviewer = _make_service()
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=slot_map,
    )
    svc.review(request)
    # reviewer.review was called with (brief, source_material, slot_review_specs)
    call_args = reviewer.review.call_args
    slot_specs = call_args[0][2]  # third positional arg
    spec_keys = [s["key"] for s in slot_specs]
    assert spec_keys == list(direct.keys())


def test_same_slot_map_same_ordering_multiple_calls() -> None:
    slot_map = make_slot_map()
    first = list(build_slot_key_mapping(slot_map.slots).keys())
    second = list(build_slot_key_mapping(slot_map.slots).keys())
    assert first == second


def test_empty_slots_produces_empty_mapping() -> None:
    empty_map = make_slot_map(slots=[])
    result = build_slot_key_mapping(empty_map.slots)
    assert result == {}


def test_valid_slot_key_in_issue_passes_validation() -> None:
    slot_map = make_slot_map()
    # K1 is the first slot in the map
    key_map = build_slot_key_mapping(slot_map.slots)
    first_key = list(key_map.keys())[0]

    issue = ManagerReviewIssue(
        severity="major",
        category="core_message_clarity",
        slot_keys=[first_key],
        issue="Issue on first slot.",
        recommendation="Fix it.",
    )
    output = make_model_output(issues=[issue])
    svc, _ = _make_service(mock_output=output)
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=slot_map,
    )
    result = svc.review(request)
    assert len(result.issues) == 1


def test_unknown_slot_key_in_issue_raises_error() -> None:
    issue = ManagerReviewIssue(
        severity="major",
        category="core_message_clarity",
        slot_keys=["K99"],  # no such key
        issue="Issue on K99.",
        recommendation="Fix it.",
    )
    output = make_model_output(issues=[issue])
    svc, _ = _make_service(mock_output=output)
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
    )
    with pytest.raises(ManagerReviewError, match="K99"):
        svc.review(request)


def test_slot_assignment_matching_action_text() -> None:
    svc, reviewer = _make_service()
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(),
        slot_map=make_slot_map(),
    )
    svc.review(request)
    slot_specs = reviewer.review.call_args[0][2]
    replace_specs = [s for s in slot_specs if s["action"] == "replace"]
    assert len(replace_specs) >= 1
    assert all(s["text"] is not None for s in replace_specs)
