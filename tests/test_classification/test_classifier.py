"""Tests for AnthropicSlideClassifier.

No real Anthropic API calls are made.  All tests inject a MagicMock client.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slidestein.classification.classifier import (
    AnthropicSlideClassifier,
    SlideClassificationError,
    SlideClassifier,
)
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideClassificationInput,
    SlideFunction,
    SlideSemanticProfile,
    SlideSemanticProfileV2,
    StorylineRole,
    VisualArchetype,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _valid_profile(slide_id: str = "test-001") -> SlideSemanticProfileV2:
    return SlideSemanticProfileV2(
        slide_id=slide_id,
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.EXPLAIN,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.BAR_CHART,
        structural_pattern="Full-width bar chart with insight callout.",
        density=DensityLevel.MEDIUM,
        description="Quarterly revenue exhibit.",
    )


def _mock_create_response(profile: SlideSemanticProfileV2) -> MagicMock:
    response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = profile.model_dump_json()
    response.content = [block]
    return response


def _make_input(slide_id: str = "test-001") -> SlideClassificationInput:
    return SlideClassificationInput(
        slide_id=slide_id,
        extracted_text="Revenue declined 15% QoQ.",
        structural_metadata={"shape_count": 3},
    )


def _make_classifier(
    client: MagicMock | None = None,
    model: str = "test-model",
) -> AnthropicSlideClassifier:
    return AnthropicSlideClassifier(
        client=client or MagicMock(),
        model=model,
    )


# ---------------------------------------------------------------------------
# Image-path error propagation (spec items 9–10 — tested via classify)
# ---------------------------------------------------------------------------


class TestImageErrorPropagation:
    def test_unsupported_preview_type_raises_classification_error(
        self, tmp_path: Path
    ) -> None:
        bad = tmp_path / "slide.gif"
        bad.write_bytes(b"GIF89a")
        inp = SlideClassificationInput(
            slide_id="test-001",
            extracted_text="text",
            structural_metadata={},
            preview_path=bad,
        )
        classifier = _make_classifier()
        with pytest.raises(SlideClassificationError, match="Unsupported"):
            classifier.classify(inp)

    def test_missing_preview_file_raises_classification_error(
        self, tmp_path: Path
    ) -> None:
        inp = SlideClassificationInput(
            slide_id="test-001",
            extracted_text="text",
            structural_metadata={},
            preview_path=tmp_path / "nonexistent.png",
        )
        classifier = _make_classifier()
        with pytest.raises(SlideClassificationError, match="not found"):
            classifier.classify(inp)


# ---------------------------------------------------------------------------
# Classifier unit tests (spec items 12–20)
# ---------------------------------------------------------------------------


class TestAnthropicSlideClassifier:
    # 12. Valid JSON response returns SlideSemanticProfile
    def test_valid_json_response_returns_semantic_profile(self) -> None:
        mock_client = MagicMock()
        profile = _valid_profile("test-001")
        mock_client.messages.create.return_value = _mock_create_response(profile)

        result = _make_classifier(mock_client).classify(_make_input("test-001"))

        assert isinstance(result, SlideSemanticProfileV2)
        assert result.slide_id == "test-001"

    # 13. Classifier sends a system message requesting raw JSON
    def test_system_message_requests_raw_json(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_create_response(
            _valid_profile("test-001")
        )

        _make_classifier(mock_client).classify(_make_input("test-001"))

        kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" in kwargs
        assert "json" in kwargs["system"].lower()

    # 14. Configured model is forwarded to the Anthropic client
    def test_configured_model_passed_to_anthropic(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_create_response(
            _valid_profile("test-001")
        )

        AnthropicSlideClassifier(
            client=mock_client, model="claude-specific-v99"
        ).classify(_make_input("test-001"))

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-specific-v99"

    # 15. Input with no preview still works
    def test_no_preview_still_works(self) -> None:
        mock_client = MagicMock()
        profile = _valid_profile("no-preview-001")
        mock_client.messages.create.return_value = _mock_create_response(profile)

        inp = SlideClassificationInput(
            slide_id="no-preview-001",
            extracted_text="Cost reduction.",
            structural_metadata={"shape_count": 2},
            # preview_path intentionally omitted
        )
        result = _make_classifier(mock_client).classify(inp)
        assert result.slide_id == "no-preview-001"

    # 16. No text blocks in response raises SlideClassificationError
    def test_no_text_blocks_raises_classification_error(self) -> None:
        mock_client = MagicMock()
        empty_response = MagicMock()
        empty_response.content = []
        mock_client.messages.create.return_value = empty_response

        with pytest.raises(SlideClassificationError, match="no structured output"):
            _make_classifier(mock_client).classify(_make_input())

    # 17. Anthropic API exception becomes SlideClassificationError
    def test_anthropic_api_exception_becomes_classification_error(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("Simulated API failure")

        with pytest.raises(SlideClassificationError, match="Simulated API failure"):
            _make_classifier(mock_client).classify(_make_input())

    # 18. Mismatching returned slide_id raises SlideClassificationError
    def test_mismatching_slide_id_raises_classification_error(self) -> None:
        mock_client = MagicMock()
        wrong_profile = _valid_profile(slide_id="wrong-id-999")
        mock_client.messages.create.return_value = _mock_create_response(wrong_profile)

        with pytest.raises(SlideClassificationError, match="wrong-id-999"):
            _make_classifier(mock_client).classify(_make_input("test-001"))

    # 19. Invalid JSON (fails Pydantic validation) fails closed
    def test_invalid_semantic_result_fails_closed(self) -> None:
        mock_client = MagicMock()
        # Valid JSON but empty storyline_roles violates min_length=1 constraint.
        invalid_json = (
            '{"slide_id": "test-001", "primary_communication_job": "explain",'
            ' "storyline_roles": [], "visual_archetype": "bar_chart",'
            ' "structural_pattern": "test", "density": "medium", "description": "test"}'
        )
        bad_response = MagicMock()
        bad_block = MagicMock()
        bad_block.type = "text"
        bad_block.text = invalid_json
        bad_response.content = [bad_block]
        mock_client.messages.create.return_value = bad_response

        with pytest.raises(SlideClassificationError):
            _make_classifier(mock_client).classify(_make_input())

    # 20. Injected client is used — no real Anthropic() construction
    def test_injected_client_is_used_no_real_api_call(self) -> None:
        mock_client = MagicMock()
        profile = _valid_profile("inject-001")
        mock_client.messages.create.return_value = _mock_create_response(profile)

        classifier = AnthropicSlideClassifier(client=mock_client, model="test-model")
        result = classifier.classify(_make_input("inject-001"))

        mock_client.messages.create.assert_called_once()
        assert result.slide_id == "inject-001"

    # 21. Markdown-fenced JSON is stripped and parsed successfully
    def test_markdown_fences_stripped_before_parsing(self) -> None:
        mock_client = MagicMock()
        profile = _valid_profile("test-001")
        markdown_response = MagicMock()
        markdown_block = MagicMock()
        markdown_block.type = "text"
        markdown_block.text = f"```json\n{profile.model_dump_json()}\n```"
        markdown_response.content = [markdown_block]
        mock_client.messages.create.return_value = markdown_response

        result = _make_classifier(mock_client).classify(_make_input("test-001"))

        assert isinstance(result, SlideSemanticProfileV2)
        assert result.slide_id == "test-001"


# ---------------------------------------------------------------------------
# Protocol conformance check
# ---------------------------------------------------------------------------


class TestSlideClassifierProtocol:
    def test_anthropic_classifier_satisfies_protocol(self) -> None:
        # Structural subtype check: isinstance does not work with Protocol,
        # but we can verify the method signature is present.
        assert hasattr(AnthropicSlideClassifier, "classify")
        assert callable(AnthropicSlideClassifier.classify)

    def test_protocol_classify_method_exists(self) -> None:
        assert hasattr(SlideClassifier, "classify")


# ---------------------------------------------------------------------------
# M3.2.1 — Configuration ownership tests
# ---------------------------------------------------------------------------


class TestConfigurationOwnership:
    def test_explicit_model_forwarded_unchanged(self) -> None:
        """Explicitly supplied model must win over any settings value."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_create_response(_valid_profile("t-001"))

        AnthropicSlideClassifier(
            client=mock_client, model="explicit-override-model"
        ).classify(_make_input("t-001"))

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "explicit-override-model"

    def test_no_explicit_model_uses_settings_classification_model(self) -> None:
        """When model is omitted, Settings.classification_model is the source."""
        from unittest.mock import patch

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_create_response(_valid_profile("t-001"))

        fake_settings = MagicMock()
        fake_settings.classification_model = "settings-defined-model-xyz"

        with patch(
            "slidestein.classification.classifier.get_settings",
            return_value=fake_settings,
        ):
            AnthropicSlideClassifier(client=mock_client).classify(_make_input("t-001"))

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "settings-defined-model-xyz"

    def test_no_duplicate_model_constant_in_classifier(self) -> None:
        """classifier.py must not define its own production-model default."""
        assert not hasattr(AnthropicSlideClassifier, "DEFAULT_MODEL"), (
            "AnthropicSlideClassifier must not carry a DEFAULT_MODEL constant; "
            "the single source of truth is Settings.classification_model"
        )
