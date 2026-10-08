"""Factory that creates the correct SlideClassifier from Settings.

Supported providers
-------------------
anthropic   — AnthropicSlideClassifier (direct Anthropic SDK)
sap_ai_core — SAPAICoreClassifier (SAP Generative AI Hub Orchestration V2)

Unknown provider values raise ValueError immediately so misconfiguration
surfaces at startup rather than at classification time.
"""

from __future__ import annotations

from slidestein.classification.classifier import AnthropicSlideClassifier, SlideClassifier


def create_slide_classifier(settings) -> SlideClassifier:
    """Return a SlideClassifier configured according to *settings*.

    Parameters
    ----------
    settings:
        A ``Settings`` instance (or any object with the same attributes).

    Raises
    ------
    ValueError
        If ``settings.classification_provider`` is not a recognised value.
    """
    provider = (settings.classification_provider or "anthropic").strip().lower()

    if provider == "anthropic":
        return AnthropicSlideClassifier(model=settings.classification_model)

    if provider == "sap_ai_core":
        return _build_sap_classifier(settings)

    raise ValueError(
        f"Unknown classification_provider {provider!r}. "
        "Supported values: 'anthropic', 'sap_ai_core'."
    )


def _build_sap_classifier(settings) -> "SAPAICoreClassifier":  # noqa: F821
    """Construct a SAPAICoreClassifier from credential settings.

    Raises
    ------
    ValueError
        If any required SAP credential is missing from settings.
    """
    missing = [
        name
        for name, val in [
            ("aicore_auth_url", settings.aicore_auth_url),
            ("aicore_client_id", settings.aicore_client_id),
            ("aicore_client_secret", settings.aicore_client_secret),
            ("aicore_base_url", settings.aicore_base_url),
        ]
        if not val
    ]
    if missing:
        raise ValueError(
            f"SAP AI Core provider requires these settings to be set: "
            f"{', '.join(missing)}.  "
            "Add them to .env or the environment."
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client
    from slidestein.classification.providers.sap_aicore import SAPAICoreClassifier

    ai_core_client = AICoreV2Client(
        base_url=settings.aicore_base_url,
        auth_url=settings.aicore_auth_url,
        client_id=settings.aicore_client_id,
        client_secret=settings.aicore_client_secret,
        resource_group=settings.aicore_resource_group,
    )

    return SAPAICoreClassifier(
        ai_core_client=ai_core_client,
        model=settings.sap_ai_core_model,
    )
