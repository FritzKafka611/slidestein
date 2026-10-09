"""Factory for ContentDraftGenerator providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.drafting.generator import ContentDraftGenerator

if TYPE_CHECKING:
    from slidestein.config import Settings


def create_content_draft_generator(settings: "Settings") -> ContentDraftGenerator:
    """Construct a ContentDraftGenerator from application settings.

    Raises
    ------
    ValueError
        For unknown provider names or missing credentials.
    """
    provider = (settings.content_draft_provider or "sap_ai_core").strip().lower()

    if provider == "sap_ai_core":
        return _build_sap_generator(settings)

    raise ValueError(
        f"Unknown content_draft_provider {provider!r}. "
        "Supported providers: 'sap_ai_core'."
    )


def _build_sap_generator(settings: "Settings") -> "SAPAICoreContentDraftGenerator":  # type: ignore[name-defined]  # noqa: F821
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
            f"SAP AI Core content draft generator requires: {', '.join(missing)}. "
            "Set these in .env or environment variables."
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # noqa: PLC0415

    from slidestein.drafting.providers.sap_aicore import (  # noqa: PLC0415
        SAPAICoreContentDraftGenerator,
    )

    ai_core_client = AICoreV2Client(
        base_url=settings.aicore_base_url,
        auth_url=settings.aicore_auth_url,
        client_id=settings.aicore_client_id,
        client_secret=settings.aicore_client_secret,
        resource_group=settings.aicore_resource_group,
    )
    return SAPAICoreContentDraftGenerator(
        ai_core_client=ai_core_client,
        model=settings.sap_ai_core_model,
    )
