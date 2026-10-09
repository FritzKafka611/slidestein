"""Factory for SlotSemanticAnalyzer (M5.2).

Only sap_ai_core is supported.  Reads settings.slot_analysis_provider.
"""

from __future__ import annotations

from slidestein.slots.analyzer import SlotSemanticAnalyzer


def create_slot_semantic_analyzer(settings: object) -> SlotSemanticAnalyzer:
    """Construct and return a SlotSemanticAnalyzer for the configured provider."""
    provider = getattr(settings, "slot_analysis_provider", "sap_ai_core")
    if provider != "sap_ai_core":
        raise ValueError(
            f"Unsupported slot_analysis_provider: {provider!r}. "
            "Only 'sap_ai_core' is supported."
        )

    aicore_url = getattr(settings, "aicore_base_url", None)
    client_id = getattr(settings, "aicore_client_id", None)
    client_secret = getattr(settings, "aicore_client_secret", None)
    auth_url = getattr(settings, "aicore_auth_url", None)
    resource_group = getattr(settings, "aicore_resource_group", None) or "default"
    model = (
        getattr(settings, "sap_ai_core_model", None)
        or getattr(settings, "sap_ai_core_vision_model", None)
    )

    missing = [
        name
        for name, val in [
            ("aicore_base_url", aicore_url),
            ("aicore_client_id", client_id),
            ("aicore_client_secret", client_secret),
            ("aicore_auth_url", auth_url),
        ]
        if not val
    ]
    if missing:
        raise ValueError(
            f"SAP AI Core slot analyzer missing settings: {', '.join(missing)}"
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # noqa: PLC0415

    ai_core_client = AICoreV2Client(
        base_url=aicore_url,
        auth_url=auth_url,
        client_id=client_id,
        client_secret=client_secret,
        resource_group=resource_group,
    )

    from slidestein.slots.providers.sap_aicore import SAPAICoreSlotSemanticAnalyzer  # noqa: PLC0415

    return SAPAICoreSlotSemanticAnalyzer(
        ai_core_client=ai_core_client,
        model=model,
    )
