"""Factory for SlideBriefGenerator providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.briefing.generator import SlideBriefGenerator

if TYPE_CHECKING:
    from slidestein.config import Settings


def create_slide_brief_generator(settings: "Settings") -> SlideBriefGenerator:
    """Construct a SlideBriefGenerator from application settings.

    Raises
    ------
    ValueError
        For unknown provider names or missing credentials.
    """
    provider = (settings.slide_brief_provider or "sap_ai_core").strip().lower()

    if provider == "sap_ai_core":
        return _build_sap_generator(settings)

    raise ValueError(
        f"Unknown slide_brief_provider {provider!r}. "
        "Supported providers: 'sap_ai_core'."
    )


def _build_sap_generator(settings: "Settings") -> "SAPAICoreSlideBriefGenerator":  # type: ignore[name-defined]  # noqa: F821
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
            f"SAP AI Core slide brief generator requires: {', '.join(missing)}. "
            "Set these in .env or environment variables."
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # noqa: PLC0415

    from slidestein.briefing.providers.sap_aicore import (  # noqa: PLC0415
        SAPAICoreSlideBriefGenerator,
    )

    ai_core_client = AICoreV2Client(
        base_url=settings.aicore_base_url,
        auth_url=settings.aicore_auth_url,
        client_id=settings.aicore_client_id,
        client_secret=settings.aicore_client_secret,
        resource_group=settings.aicore_resource_group,
    )
    return SAPAICoreSlideBriefGenerator(
        ai_core_client=ai_core_client,
        model=settings.sap_ai_core_model,
    )
