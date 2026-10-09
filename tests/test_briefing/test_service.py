"""Unit tests for SlideIntentService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slidestein.briefing.brief import ConsultingSlideBrief
from slidestein.briefing.providers.sap_aicore import SlideBriefGenerationError
from slidestein.briefing.service import SlideIntentService
from slidestein.domain.models import CommunicationJob, SlideFunction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_brief(**kwargs) -> ConsultingSlideBrief:
    defaults = dict(
        original_request="Show the workstream roadmap over 12 weeks",
        key_message="Five workstreams delivered over 12 weeks with milestones.",
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SHOW_TIMELINE,
    )
    defaults.update(kwargs)
    return ConsultingSlideBrief(**defaults)


def _make_service(brief: ConsultingSlideBrief | None = None) -> SlideIntentService:
    mock_generator = MagicMock()
    mock_generator.generate.return_value = brief or _make_brief()
    return SlideIntentService(generator=mock_generator), mock_generator


# ---------------------------------------------------------------------------
# understand()
# ---------------------------------------------------------------------------

class TestUnderstand:
    def test_blank_request_raises_before_provider_called(self):
        svc, mock_gen = _make_service()
        with pytest.raises(SlideBriefGenerationError):
            svc.understand("   ")
        mock_gen.generate.assert_not_called()

    def test_empty_request_raises_before_provider_called(self):
        svc, mock_gen = _make_service()
        with pytest.raises(SlideBriefGenerationError):
            svc.understand("")
        mock_gen.generate.assert_not_called()

    def test_provider_called_exactly_once_for_valid_request(self):
        svc, mock_gen = _make_service()
        svc.understand("Show me a roadmap slide.")
        mock_gen.generate.assert_called_once_with("Show me a roadmap slide.")

    def test_valid_brief_returned_unchanged(self):
        brief = _make_brief()
        svc, _ = _make_service(brief)
        result = svc.understand("Show the workstream roadmap over 12 weeks")
        assert result is brief

    def test_provider_exception_propagates(self):
        svc, mock_gen = _make_service()
        mock_gen.generate.side_effect = SlideBriefGenerationError("provider error")
        with pytest.raises(SlideBriefGenerationError, match="provider error"):
            svc.understand("Show me a slide.")


# ---------------------------------------------------------------------------
# to_retrieval_request()
# ---------------------------------------------------------------------------

class TestToRetrievalRequest:
    def test_to_retrieval_request_does_not_call_provider(self):
        brief = _make_brief()
        svc, mock_gen = _make_service(brief)
        svc.to_retrieval_request(brief)
        mock_gen.generate.assert_not_called()

    def test_query_text_equals_original_request(self):
        brief = _make_brief()
        svc, _ = _make_service(brief)
        rr = svc.to_retrieval_request(brief)
        assert rr.query_text == brief.original_request

    def test_top_k_parameter_respected(self):
        brief = _make_brief()
        svc, _ = _make_service(brief)
        rr = svc.to_retrieval_request(brief, top_k=8)
        assert rr.top_k == 8
