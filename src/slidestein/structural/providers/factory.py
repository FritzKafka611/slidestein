"""Factory for creating a StructuralTemplateSelector from application settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.structural.selector import StructuralTemplateSelector

if TYPE_CHECKING:
    pass


def create_structural_template_selector(settings: object) -> StructuralTemplateSelector:
    """Instantiate a StructuralTemplateSelector from application settings.

    Only SAP AI Core is supported in M10.
    Direct Anthropic: FORBIDDEN.
    """
    provider = getattr(settings, "structural_recovery_provider", "sap_ai_core")
    if provider != "sap_ai_core":
        raise ValueError(
            f"Unsupported structural recovery provider: {provider!r}. "
            "Only 'sap_ai_core' is supported."
        )

    for attr in ("aicore_auth_url", "aicore_client_id", "aicore_base_url"):
        if not getattr(settings, attr, None):
            raise ValueError(
                f"SAP AI Core credential {attr!r} is missing or empty. "
                "Check your .env configuration."
            )
    if not getattr(settings, "aicore_client_secret", None):
        raise ValueError(
            "SAP AI Core credential 'aicore_client_secret' is missing. "
            "Check your .env configuration."
        )

    try:
        from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            f"ai_core_sdk is not installed or not importable: {exc}"
        ) from exc

    client = AICoreV2Client(
        base_url=settings.aicore_base_url,  # type: ignore[union-attr]
        auth_url=settings.aicore_auth_url,  # type: ignore[union-attr]
        client_id=settings.aicore_client_id,  # type: ignore[union-attr]
        client_secret=settings.aicore_client_secret,  # type: ignore[union-attr]
        resource_group=settings.aicore_resource_group,  # type: ignore[union-attr]
    )

    from slidestein.structural.providers.sap_aicore import SAPAICoreStructuralTemplateSelector

    model = getattr(settings, "sap_ai_core_model", "claude-3.5-sonnet")
    return SAPAICoreStructuralTemplateSelector(ai_core_client=client, model=model)
