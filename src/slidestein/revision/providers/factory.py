"""Factory for ContentReviser providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.revision.reviser import ContentReviser

if TYPE_CHECKING:
    from slidestein.config import Settings


def create_content_reviser(settings: "Settings") -> ContentReviser:
    """Construct a ContentReviser from application settings.

    Raises
    ------
    ValueError
        For unknown provider names or missing credentials.
    """
    provider = (
        getattr(settings, "content_revision_provider", None) or "sap_ai_core"
    ).strip().lower()

    if provider == "sap_ai_core":
        return _build_sap_reviser(settings)

    raise ValueError(
        f"Unknown content_revision_provider {provider!r}. "
        "Supported providers: 'sap_ai_core'."
    )


def _build_sap_reviser(settings: "Settings") -> "SAPAICoreContentReviser":  # type: ignore[name-defined]  # noqa: F821
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
            f"SAP AI Core content reviser requires: {', '.join(missing)}. "
            "Set these in .env or environment variables."
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # noqa: PLC0415

    from slidestein.revision.providers.sap_aicore import (  # noqa: PLC0415
        SAPAICoreContentReviser,
    )

    ai_core_client = AICoreV2Client(
        base_url=settings.aicore_base_url,
        auth_url=settings.aicore_auth_url,
        client_id=settings.aicore_client_id,
        client_secret=settings.aicore_client_secret,
        resource_group=settings.aicore_resource_group,
    )
    return SAPAICoreContentReviser(
        ai_core_client=ai_core_client,
        model=settings.sap_ai_core_model,
    )
