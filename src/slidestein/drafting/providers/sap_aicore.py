"""SAP AI Core Orchestration V2 implementation of ContentDraftGenerator."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from slidestein.drafting.analysis_models import ContentDraftModelOutput

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class ContentDraftGenerationError(RuntimeError):
    """Raised when content draft generation fails or returns invalid output."""


# ---------------------------------------------------------------------------
# Fence stripping (same pattern as existing providers)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_END_RE = re.compile(r"\n?```\s*$")


def _strip_fences(text: str) -> str:
    cleaned = _FENCE_RE.sub("", text)
    cleaned = _FENCE_END_RE.sub("", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# SAPAICoreContentDraftGenerator
# ---------------------------------------------------------------------------


class SAPAICoreContentDraftGenerator:
    """ContentDraftModelOutput generator using SAP AI Core Orchestration V2.

    Makes exactly ONE text-only API call per generate() request.
    No images, no iterative loop, no automatic retry.
    """

    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        ai_core_client: object,
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._ai_core_client = ai_core_client
        self._model = model
        self._max_tokens = max_tokens

    def generate(
        self,
        brief: "ConsultingSlideBrief",
        source_material: str | None,
        slot_specs: list[dict],
        groups_context: list[dict],
    ) -> ContentDraftModelOutput:
        """Generate ContentDraftModelOutput for one slide.

        Exactly one SAP AI Core call is made.  Malformed output raises
        ContentDraftGenerationError for inspection — no automatic retry.
        """
        from slidestein.drafting.prompt import (  # noqa: PLC0415
            _SYSTEM_PROMPT,
            build_brief_summary,
            build_draft_prompt,
        )

        brief_summary = build_brief_summary(brief)
        prompt_text = build_draft_prompt(
            brief_summary=brief_summary,
            source_material=source_material,
            slot_specs=slot_specs,
            groups_context=groups_context,
        )

        try:
            raw_text = self._run_orchestration(prompt_text, _SYSTEM_PROMPT)
        except ContentDraftGenerationError:
            raise
        except Exception as exc:
            raise ContentDraftGenerationError(
                f"SAP AI Core content draft generation error ({self._model}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        json_text = _strip_fences(raw_text)

        try:
            output = ContentDraftModelOutput.model_validate_json(json_text)
        except Exception as exc:
            raise ContentDraftGenerationError(
                f"Content draft response parse error: {type(exc).__name__}: {exc}. "
                f"Raw response (first 500 chars): {raw_text[:500]!r}"
            ) from exc

        return output

    def _run_orchestration(self, prompt_text: str, system_prompt: str) -> str:
        """Execute the Orchestration V2 call and return raw response text."""
        from gen_ai_hub.orchestration_v2 import (  # noqa: PLC0415
            ModuleConfig,
            OrchestrationConfig,
            OrchestrationService,
            PromptTemplatingModuleConfig,
            SystemMessage,
            Template,
            TextPart,
            UserMessage,
        )
        from gen_ai_hub.orchestration_v2.models.llm_model_details import LLMModelDetails  # noqa: PLC0415
        from gen_ai_hub.proxy.gen_ai_hub_proxy.client import GenAIHubProxyClient  # noqa: PLC0415

        proxy_client = GenAIHubProxyClient(ai_core_client=self._ai_core_client)
        deployment_id = self._get_orchestration_deployment_id()
        api_url = (
            f"{self._ai_core_client.base_url.rstrip('/')}"
            f"/inference/deployments/{deployment_id}"
        )

        config = OrchestrationConfig(
            modules=ModuleConfig(
                prompt_templating=PromptTemplatingModuleConfig(
                    prompt=Template(
                        template=[
                            SystemMessage(content=system_prompt),
                            UserMessage(content=[TextPart(text=prompt_text)]),
                        ]
                    ),
                    model=LLMModelDetails(
                        name=self._model,
                        params={"max_tokens": self._max_tokens},
                    ),
                )
            )
        )

        service = OrchestrationService(
            api_url=api_url,
            proxy_client=proxy_client,
            config=config,
        )
        response = service.run()
        return response.final_result.choices[0].message.content

    def _get_orchestration_deployment_id(self) -> str:
        """Discover and cache the running Orchestration V2 deployment ID."""
        if hasattr(self, "_deployment_id_cache"):
            return self._deployment_id_cache
        from ai_api_client_sdk.models.status import Status  # noqa: PLC0415

        deployments = self._ai_core_client.deployment.query(status=Status.RUNNING)
        for d in deployments.resources:
            if getattr(d, "scenario_id", "") == "orchestration":
                self._deployment_id_cache: str = d.id
                return d.id
        raise ContentDraftGenerationError(
            "No running Orchestration V2 deployment found in resource group "
            f"'{self._ai_core_client.rest_client.resource_group}'. "
            "Ensure an orchestration deployment is running in SAP AI Core."
        )
