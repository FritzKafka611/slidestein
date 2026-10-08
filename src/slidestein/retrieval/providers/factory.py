"""Factory for creating EmbeddingProvider instances from Settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.retrieval.provider import EmbeddingProvider

if TYPE_CHECKING:
    from slidestein.config import Settings


def create_embedding_provider(settings: "Settings") -> EmbeddingProvider:
    """Return an EmbeddingProvider configured from *settings*.

    Raises
    ------
    ValueError
        If embedding_provider is unknown or required credentials are missing.
    """
    provider = settings.embedding_provider.lower()

    if provider == "sap_ai_core":
        _validate_sap_credentials(settings)
        from ai_core_sdk.ai_core_v2_client import AICoreV2Client
        from slidestein.retrieval.providers.sap_aicore import SAPAICoreEmbeddingProvider

        client = AICoreV2Client(
            base_url=settings.aicore_base_url,
            auth_url=settings.aicore_auth_url,
            client_id=settings.aicore_client_id,
            client_secret=settings.aicore_client_secret,
            resource_group=settings.aicore_resource_group,
        )
        return SAPAICoreEmbeddingProvider(
            ai_core_client=client,
            model=settings.sap_ai_core_embedding_model,
        )

    raise ValueError(
        f"Unknown embedding_provider {settings.embedding_provider!r}. "
        "Supported: 'sap_ai_core'."
    )


def _validate_sap_credentials(settings: "Settings") -> None:
    required = {
        "aicore_auth_url": settings.aicore_auth_url,
        "aicore_client_id": settings.aicore_client_id,
        "aicore_client_secret": settings.aicore_client_secret,
        "aicore_base_url": settings.aicore_base_url,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(
            f"Missing SAP AI Core credentials for embedding: {', '.join(missing)}"
        )
