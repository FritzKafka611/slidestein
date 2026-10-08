"""Unit tests for classification provider factory and SAPAICoreClassifier.

All SAP SDK and Anthropic SDK boundaries are mocked.
No real API calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.classification.classifier import SlideClassificationError
from slidestein.classification.providers.factory import create_slide_classifier
from slidestein.domain.models import (
    SlideClassificationInput,
    SlideFunction,
    SlideSemanticProfileV2,
    CommunicationJob,
    VisualArchetype,
    DensityLevel,
    StorylineRole,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(provider: str = "anthropic", **extra):
    s = MagicMock()
    s.classification_provider = provider
    s.classification_model = "claude-opus-4-5"
    s.aicore_auth_url = "https://auth.example.com"
    s.aicore_client_id = "client-id"
    s.aicore_client_secret = "client-secret"
    s.aicore_base_url = "https://api.example.com"
    s.aicore_resource_group = "default"
    s.sap_ai_core_model = "claude-3.5-sonnet"
    for k, v in extra.items():
        setattr(s, k, v)
    return s


def _minimal_profile(slide_id: str) -> SlideSemanticProfileV2:
    return SlideSemanticProfileV2(
        slide_id=slide_id,
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.EXPLAIN,
        secondary_communication_jobs=[],
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.STRUCTURED_ONE_PAGER,
        structural_pattern="Five-section one-pager with labeled rows.",
        density=DensityLevel.MEDIUM,
        description="A context-setting workstream charter.",
        best_for=["introducing a new workstream"],
        not_for=["executive summary"],
    )


def _minimal_input(slide_id: str = "test-slide", preview_path: Path | None = None) -> SlideClassificationInput:
    return SlideClassificationInput(
        slide_id=slide_id,
        extracted_text="Test slide content",
        structural_metadata={"slide_number": 1, "shape_count": 2},
        preview_path=preview_path,
    )


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

class TestFactory:
    def test_factory_returns_anthropic_classifier(self):
        from slidestein.classification.classifier import AnthropicSlideClassifier
        clf = create_slide_classifier(_settings("anthropic"))
        assert isinstance(clf, AnthropicSlideClassifier)

    def test_factory_returns_sap_classifier(self):
        from slidestein.classification.providers.sap_aicore import SAPAICoreClassifier
        with patch("ai_core_sdk.ai_core_v2_client.AICoreV2Client") as mock_client:
            mock_client.return_value = MagicMock()
            clf = create_slide_classifier(_settings("sap_ai_core"))
        assert isinstance(clf, SAPAICoreClassifier)

    def test_factory_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown classification_provider"):
            create_slide_classifier(_settings("bad_provider"))

    def test_factory_case_insensitive(self):
        from slidestein.classification.classifier import AnthropicSlideClassifier
        clf = create_slide_classifier(_settings("ANTHROPIC"))
        assert isinstance(clf, AnthropicSlideClassifier)

    def test_factory_sap_missing_credentials_raises(self):
        s = _settings("sap_ai_core")
        s.aicore_client_secret = None
        with pytest.raises(ValueError, match="aicore_client_secret"):
            create_slide_classifier(s)

    def test_factory_sap_missing_url_raises(self):
        s = _settings("sap_ai_core")
        s.aicore_base_url = None
        with pytest.raises(ValueError, match="aicore_base_url"):
            create_slide_classifier(s)


# ---------------------------------------------------------------------------
# SAPAICoreClassifier unit tests
# ---------------------------------------------------------------------------

class TestSAPAICoreClassifier:
    def _make_classifier(self):
        from slidestein.classification.providers.sap_aicore import SAPAICoreClassifier
        ai_core_client = MagicMock()
        return SAPAICoreClassifier(ai_core_client=ai_core_client, model="claude-3.5-sonnet")

    def _make_mock_response(self, profile: SlideSemanticProfileV2) -> str:
        return profile.model_dump_json()

    def test_valid_response_returns_profile(self, tmp_path):
        slide_id = "slide-abc-123"
        profile = _minimal_profile(slide_id)
        json_text = self._make_mock_response(profile)

        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", return_value=json_text):
            result = clf.classify(_minimal_input(slide_id))

        assert result.slide_id == slide_id
        assert result.primary_communication_job == CommunicationJob.EXPLAIN
        assert isinstance(result, SlideSemanticProfileV2)

    def test_fenced_json_is_accepted(self, tmp_path):
        slide_id = "slide-fenced"
        profile = _minimal_profile(slide_id)
        fenced = f"```json\n{profile.model_dump_json()}\n```"

        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", return_value=fenced):
            result = clf.classify(_minimal_input(slide_id))

        assert result.slide_id == slide_id

    def test_malformed_json_raises_classification_error(self):
        slide_id = "slide-bad"
        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", return_value="not-json{{{"):
            with pytest.raises(SlideClassificationError, match="invalid JSON"):
                clf.classify(_minimal_input(slide_id))

    def test_wrong_slide_id_in_response_raises(self):
        slide_id = "slide-correct"
        profile = _minimal_profile("slide-wrong-id")
        json_text = self._make_mock_response(profile)

        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", return_value=json_text):
            with pytest.raises(SlideClassificationError, match="slide_id"):
                clf.classify(_minimal_input(slide_id))

    def test_missing_preview_raises_before_api_call(self, tmp_path):
        slide_id = "slide-no-preview"
        missing = tmp_path / "nonexistent.png"
        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration") as mock_run:
            with pytest.raises(SlideClassificationError, match="not found"):
                clf.classify(_minimal_input(slide_id, preview_path=missing))
            mock_run.assert_not_called()

    def test_orchestration_error_raises_classification_error(self):
        slide_id = "slide-sdk-error"
        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", side_effect=RuntimeError("timeout")):
            with pytest.raises(SlideClassificationError, match="SAP AI Core error"):
                clf.classify(_minimal_input(slide_id))

    def test_model_stored_correctly(self):
        from slidestein.classification.providers.sap_aicore import SAPAICoreClassifier
        clf = SAPAICoreClassifier(ai_core_client=MagicMock(), model="claude-3.5-sonnet")
        assert clf._model == "claude-3.5-sonnet"

    def test_non_content_profile_null_job(self):
        """Non-content profiles (section_divider) with null job are accepted."""
        slide_id = "slide-nav-001"
        nav_profile = SlideSemanticProfileV2(
            slide_id=slide_id,
            slide_function=SlideFunction.SECTION_DIVIDER,
            primary_communication_job=None,
            secondary_communication_jobs=[],
            storyline_roles=[StorylineRole.CONTEXT],
            visual_archetype=VisualArchetype.TITLE,
            structural_pattern="Section divider with title.",
            density=DensityLevel.LOW,
            description="Section divider.",
            best_for=["structuring decks"],
            not_for=["detailed content"],
        )
        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", return_value=nav_profile.model_dump_json()):
            result = clf.classify(_minimal_input(slide_id))
        assert result.primary_communication_job is None
        assert result.slide_function == SlideFunction.SECTION_DIVIDER

    def test_structured_one_pager_archetype_accepted(self):
        slide_id = "slide-sop-001"
        profile = _minimal_profile(slide_id)  # already uses STRUCTURED_ONE_PAGER
        clf = self._make_classifier()
        with patch.object(clf, "_run_orchestration", return_value=profile.model_dump_json()):
            result = clf.classify(_minimal_input(slide_id))
        assert result.visual_archetype == VisualArchetype.STRUCTURED_ONE_PAGER


# ---------------------------------------------------------------------------
# Service-layer independence test
# ---------------------------------------------------------------------------

class TestServiceProviderIndependence:
    """The service layer must work identically with Anthropic or SAP classifier."""

    def test_service_accepts_sap_classifier(self, tmp_path):
        """SlideClassificationService must not inspect classifier type."""
        from slidestein.classification.providers.sap_aicore import SAPAICoreClassifier
        from slidestein.classification.service import SlideClassificationService
        from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

        slide_id = "test-independence"
        profile = _minimal_profile(slide_id)

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = profile

        service = SlideClassificationService(
            classifier=mock_classifier,
            renderer=PythonPptxAdapter(),
        )

        from pptx import Presentation
        pptx_path = tmp_path / "test.pptx"
        prs = Presentation()
        prs.slides.add_slide(prs.slide_layouts[0])
        prs.save(str(pptx_path))

        preview = tmp_path / "preview.png"
        preview.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        result = service.classify_slide(
            pptx_path=pptx_path,
            slide_number=1,
            slide_id=slide_id,
            existing_preview_path=preview,
        )

        assert result.slide_id == slide_id
        assert isinstance(result, SlideSemanticProfileV2)
        mock_classifier.classify.assert_called_once()
