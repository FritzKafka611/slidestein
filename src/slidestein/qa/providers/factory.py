"""Factory for VisualQAReviewer providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.qa.reviewer import VisualQAReviewer

if TYPE_CHECKING:
    from slidestein.config import Settings


def create_visual_qa_reviewer(settings: "Settings") -> VisualQAReviewer:
    """Construct a VisualQAReviewer from application settings.

    Raises
    ------
    ValueError
        For unknown provider names or missing credentials.
    """
    provider = (settings.visual_qa_provider or "sap_ai_core").strip().lower()

    if provider == "sap_ai_core":
        return _build_sap_reviewer(settings)

    raise ValueError(
        f"Unknown visual_qa_provider {provider!r}. "
        "Supported providers: 'sap_ai_core'."
    )


def _build_sap_reviewer(settings: "Settings") -> "VisualQAReviewer":
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
            f"SAP AI Core visual QA reviewer requires: {', '.join(missing)}. "
            "Set these in .env or environment variables."
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # noqa: PLC0415

    from slidestein.qa.providers.sap_aicore import SAPAICoreVisualQAReviewer  # noqa: PLC0415

    ai_core_client = AICoreV2Client(
        base_url=settings.aicore_base_url,
        auth_url=settings.aicore_auth_url,
        client_id=settings.aicore_client_id,
        client_secret=settings.aicore_client_secret,
        resource_group=settings.aicore_resource_group,
    )
    return SAPAICoreVisualQAReviewer(
        ai_core_client=ai_core_client,
        model=settings.sap_ai_core_model,
    )
