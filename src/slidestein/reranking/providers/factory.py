"""Factory for VisionReranker providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.reranking.reranker import VisionReranker

if TYPE_CHECKING:
    from slidestein.config import Settings


def create_vision_reranker(settings: "Settings") -> VisionReranker:
    """Construct a VisionReranker from application settings.

    Raises
    ------
    ValueError
        For unknown provider names.
    """
    provider = (settings.vision_rerank_provider or "sap_ai_core").strip().lower()

    if provider == "sap_ai_core":
        return _build_sap_reranker(settings)

    raise ValueError(
        f"Unknown vision_rerank_provider {provider!r}. "
        "Supported providers: 'sap_ai_core'."
    )


def _build_sap_reranker(settings: "Settings") -> "VisionReranker":
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
            f"SAP AI Core vision reranker requires: {', '.join(missing)}. "
            "Set these in .env or environment variables."
        )

    from ai_core_sdk.ai_core_v2_client import AICoreV2Client  # noqa: PLC0415

    from slidestein.reranking.providers.sap_aicore import SAPAICoreVisionReranker  # noqa: PLC0415

    ai_core_client = AICoreV2Client(
        base_url=settings.aicore_base_url,
        auth_url=settings.aicore_auth_url,
        client_id=settings.aicore_client_id,
        client_secret=settings.aicore_client_secret,
        resource_group=settings.aicore_resource_group,
    )
    return SAPAICoreVisionReranker(
        ai_core_client=ai_core_client,
        model=settings.sap_ai_core_model,
    )
