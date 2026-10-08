"""SAPAICoreEmbeddingProvider — embeddings via SAP Generative AI Hub Orchestration V2.

Uses OrchestrationService.embed() with:
- EmbeddingsInputType.DOCUMENT for retrieval documents
- EmbeddingsInputType.QUERY for search queries
- EmbeddingsEncodingFormat.FLOAT
- normalize=True (where model supports it)

All SAP SDK objects are contained here; nothing SAP-specific leaks upstream.
Reuses the same AICoreV2Client credential pattern as SAPAICoreClassifier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidestein.retrieval.provider import EmbeddingBatch

if TYPE_CHECKING:
    from ai_core_sdk.ai_core_v2_client import AICoreV2Client


class EmbeddingError(Exception):
    """Raised when an embedding call fails."""


class SAPAICoreEmbeddingProvider:
    """Embeds texts via SAP Generative AI Hub Orchestration V2 embeddings endpoint.

    Parameters
    ----------
    ai_core_client:
        Authenticated AICoreV2Client instance.
    model:
        Embedding model name as registered in Generative AI Hub.
    normalize:
        Request normalized vectors when True.  Set to None to omit the
        parameter entirely (use for models that don't support it).
    batch_size:
        Maximum number of texts per API call.
    """

    def __init__(
        self,
        ai_core_client: "AICoreV2Client",
        model: str,
        normalize: bool | None = True,
        batch_size: int = 32,
    ) -> None:
        self._ai_core_client = ai_core_client
        self._model = model
        self._normalize = normalize
        self._batch_size = batch_size
        self._deployment_id_cache: str | None = None

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------------
    # EmbeddingProvider protocol
    # ------------------------------------------------------------------

    def embed_documents(self, texts: list[str]) -> EmbeddingBatch:
        """Embed retrieval documents in batches using DOCUMENT input type."""
        if not texts:
            raise EmbeddingError("texts must be non-empty")
        return self._embed_batched(texts, input_type="document")

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query using QUERY input type."""
        if not text.strip():
            raise EmbeddingError("query text must be non-blank")
        batch = self._embed_batched([text], input_type="query")
        return batch.vectors[0]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _embed_batched(self, texts: list[str], input_type: str) -> EmbeddingBatch:
        """Split into batches, embed each, reassemble in order."""
        all_vectors: list[list[float]] = []
        model_name = ""

        for start in range(0, len(texts), self._batch_size):
            chunk = texts[start : start + self._batch_size]
            result = self._call_api(chunk, input_type=input_type)
            model_name = result.model
            if len(result.vectors) != len(chunk):
                raise EmbeddingError(
                    f"SAP AI Core returned {len(result.vectors)} vectors "
                    f"for {len(chunk)} input texts — mapping would be corrupted."
                )
            all_vectors.extend(result.vectors)

        # Validate all vectors have the same dimension.
        dim = len(all_vectors[0])
        for i, vec in enumerate(all_vectors):
            if len(vec) != dim:
                raise EmbeddingError(
                    f"Vector {i} has dimension {len(vec)}, expected {dim}."
                )

        return EmbeddingBatch(vectors=all_vectors, model=model_name, dimension=dim)

    def _call_api(self, texts: list[str], input_type: str) -> "_ApiResult":
        """Make one embedding API call and return structured result."""
        from gen_ai_hub.orchestration_v2 import (
            EmbeddingsEncodingFormat,
            EmbeddingsInput,
            EmbeddingsInputType,
            EmbeddingsModelConfig,
            EmbeddingsModelDetails,
            EmbeddingsModelParams,
            EmbeddingsModuleConfigs,
            EmbeddingsOrchestrationConfig,
            OrchestrationService,
        )
        from gen_ai_hub.proxy.gen_ai_hub_proxy.client import GenAIHubProxyClient

        proxy_client = GenAIHubProxyClient(ai_core_client=self._ai_core_client)
        deployment_id = self._get_deployment_id()
        api_url = (
            f"{self._ai_core_client.base_url.rstrip('/')}"
            f"/inference/deployments/{deployment_id}"
        )

        params = EmbeddingsModelParams(
            encoding_format=EmbeddingsEncodingFormat.FLOAT,
            normalize=self._normalize,
        )

        config = EmbeddingsOrchestrationConfig(
            modules=EmbeddingsModuleConfigs(
                embeddings=EmbeddingsModelConfig(
                    model=EmbeddingsModelDetails(
                        name=self._model,
                        params=params,
                    )
                )
            )
        )

        # Map input_type string to SDK enum.
        type_map = {
            "document": EmbeddingsInputType.DOCUMENT,
            "query": EmbeddingsInputType.QUERY,
            "text": EmbeddingsInputType.TEXT,
        }
        sdk_type = type_map.get(input_type)

        embedding_input = EmbeddingsInput(
            text=texts if len(texts) > 1 else texts[0],
            type=sdk_type,
        )

        service = OrchestrationService(
            api_url=api_url,
            proxy_client=proxy_client,
        )

        try:
            response = service.embed(config=config, input=embedding_input)
        except Exception as exc:
            raise EmbeddingError(
                f"SAP AI Core embedding error ({self._model}): {type(exc).__name__}: {exc}"
            ) from exc

        result = response.final_result
        vectors = [item.embedding for item in result.data]
        return _ApiResult(vectors=vectors, model=result.model)

    def _get_deployment_id(self) -> str:
        """Return the running Orchestration V2 deployment ID (cached)."""
        if self._deployment_id_cache is not None:
            return self._deployment_id_cache
        from ai_api_client_sdk.models.status import Status

        deployments = self._ai_core_client.deployment.query(status=Status.RUNNING)
        for d in deployments.resources:
            if getattr(d, "scenario_id", "") == "orchestration":
                self._deployment_id_cache = d.id
                return d.id
        raise EmbeddingError(
            "No running Orchestration V2 deployment found. "
            "Create one via SAP AI Launchpad before running embeddings."
        )


class _ApiResult:
    """Internal result container — not exposed outside this module."""

    __slots__ = ("vectors", "model")

    def __init__(self, vectors: list[list[float]], model: str) -> None:
        self.vectors = vectors
        self.model = model
