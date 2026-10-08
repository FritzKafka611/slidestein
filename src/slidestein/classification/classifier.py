"""AnthropicSlideClassifier — production slide classification via Claude Vision.

Architecture:
  domain models (zero Anthropic dependency)
      ↑
  classification.prompt (zero Anthropic dependency)
      ↑
  AnthropicSlideClassifier (this module — uses Anthropic SDK)

The Anthropic client is injected so unit tests can operate without network calls.
The classifier uses client.messages.create with a system prompt that instructs
Claude to return raw JSON.  Markdown code fences are stripped as a safety net
before Pydantic validation.  All errors surface as SlideClassificationError
(fail-closed contract).
"""

from __future__ import annotations

import re
from typing import Protocol

from slidestein.config import get_settings
from slidestein.domain.models import SlideClassificationInput, SlideSemanticProfileV2

_SYSTEM_PROMPT = (
    "You are a slide classification assistant. "
    "Respond with ONLY valid JSON matching the requested schema. "
    "Do not use markdown code fences or backticks. "
    "Do not add any explanation or commentary. "
    "The response must start with { and end with }."
)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from a JSON string if present."""
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


class SlideClassificationError(RuntimeError):
    """Raised when slide classification fails for any reason.

    Never silently return a default profile.
    Never fabricate fallback taxonomy values.
    Callers must handle this exception explicitly.
    """


class SlideClassifier(Protocol):
    """Minimal protocol for any slide classifier implementation.

    Allows callers to depend on the abstraction rather than the Anthropic
    implementation, enabling alternative classifiers and easy test doubles.
    """

    def classify(
        self,
        classification_input: SlideClassificationInput,
    ) -> SlideSemanticProfileV2:
        """Classify a slide and return its V2 semantic profile.

        Raises SlideClassificationError on any failure.
        """
        ...


class AnthropicSlideClassifier:
    """Classifies consulting slides via Claude Vision.

    Uses ``client.messages.create`` with a system prompt that instructs Claude
    to return raw JSON.  Markdown code fences in the response are stripped before
    Pydantic validation.

    Parameters
    ----------
    client:
        Anthropic client instance.  If None, a standard ``Anthropic()`` client
        is constructed using the ``ANTHROPIC_API_KEY`` environment variable.
    model:
        Claude model identifier.  Defaults to ``Settings.classification_model``
        when not supplied explicitly.  Pass a value to override for testing or
        cost optimisation.
    max_tokens:
        Maximum tokens for the classification response.
    """

    DEFAULT_MAX_TOKENS = 1024

    def __init__(
        self,
        client: object = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if client is None:
            from anthropic import Anthropic

            self._client = Anthropic()
        else:
            self._client = client
        self._model = model if model is not None else get_settings().classification_model
        self._max_tokens = max_tokens

    def classify(
        self,
        classification_input: SlideClassificationInput,
    ) -> SlideSemanticProfileV2:
        """Classify *classification_input* and return a validated V2 profile.

        Raises
        ------
        SlideClassificationError
            Wraps all failures:
            - missing / unreadable / unsupported-type preview image
            - Anthropic API errors
            - no text content in the response
            - JSON that does not validate as SlideSemanticProfileV2
            - ``slide_id`` in the returned profile does not match the input
        """
        from .prompt import build_messages

        # Build messages — local errors raised before any network call.
        try:
            messages = build_messages(classification_input)
        except (ValueError, FileNotFoundError, OSError) as exc:
            raise SlideClassificationError(str(exc)) from exc

        # Call the Anthropic API.
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                messages=messages,
            )
        except Exception as exc:
            raise SlideClassificationError(
                f"Anthropic API error classifying slide "
                f"{classification_input.slide_id!r}: {exc}"
            ) from exc

        # Extract text content from the response.
        text_blocks = [b for b in response.content if b.type == "text"]
        if not text_blocks:
            raise SlideClassificationError(
                f"Classifier returned no structured output for slide "
                f"{classification_input.slide_id!r}"
            )

        raw_text = text_blocks[0].text.strip()
        json_text = _strip_markdown_fences(raw_text)

        # Parse and validate as SlideSemanticProfileV2.
        try:
            profile = SlideSemanticProfileV2.model_validate_json(json_text)
        except Exception as exc:
            raise SlideClassificationError(
                f"Anthropic API error classifying slide "
                f"{classification_input.slide_id!r}: {exc}"
            ) from exc

        # Provenance check: slide_id must round-trip unchanged.
        if profile.slide_id != classification_input.slide_id:
            raise SlideClassificationError(
                f"Classifier returned slide_id {profile.slide_id!r} but input "
                f"was {classification_input.slide_id!r}. "
                "Structured output does not match the requested slide."
            )

        return profile
