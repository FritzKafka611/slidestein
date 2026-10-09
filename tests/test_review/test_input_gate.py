"""Tests for is_complete input gate — service must reject incomplete drafts."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.review.errors import ManagerReviewError
from slidestein.review.service import ManagerReviewService
from tests.test_review.conftest import make_brief, make_complete_draft, make_slot_map, make_model_output
from slidestein.review.models import ManagerReviewRequest


def _make_service(mock_output=None):
    reviewer = MagicMock()
    if mock_output is not None:
        reviewer.review.return_value = mock_output
    else:
        reviewer.review.return_value = make_model_output()
    return ManagerReviewService(reviewer=reviewer), reviewer


def test_incomplete_draft_raises_before_reviewer_called() -> None:
    svc, reviewer = _make_service()
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(is_complete=False),
        slot_map=make_slot_map(),
    )
    with pytest.raises(ManagerReviewError):
        svc.review(request)
    reviewer.review.assert_not_called()


def test_error_message_mentions_is_complete() -> None:
    svc, _ = _make_service()
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(is_complete=False),
        slot_map=make_slot_map(),
    )
    with pytest.raises(ManagerReviewError, match="is_complete"):
        svc.review(request)


def test_complete_draft_reviewer_called_once() -> None:
    svc, reviewer = _make_service()
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(is_complete=True),
        slot_map=make_slot_map(),
    )
    svc.review(request)
    reviewer.review.assert_called_once()


def test_complete_draft_does_not_raise() -> None:
    svc, _ = _make_service()
    request = ManagerReviewRequest(
        brief=make_brief(),
        draft=make_complete_draft(is_complete=True),
        slot_map=make_slot_map(),
    )
    result = svc.review(request)
    assert result is not None
