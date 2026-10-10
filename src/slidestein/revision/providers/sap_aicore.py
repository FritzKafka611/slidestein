"""SAP AI Core Orchestration V2 implementation of ContentReviser (v1.1)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from slidestein.revision.models import ContentRevisionModelOutput

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.drafting.models import SlideContentDraft


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class ContentRevisionGenerationError(RuntimeError):
    """Raised when content revision generation fails or returns invalid output."""


# ---------------------------------------------------------------------------
# Fence stripping (same pattern as other providers)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_END_RE = re.compile(r"\n?```\s*$")


def _strip_fences(text: str) -> str:
    cleaned = _FENCE_RE.sub("", text)
    cleaned = _FENCE_END_RE.sub("", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# SAPAICoreContentReviser
# ---------------------------------------------------------------------------


class SAPAICoreContentReviser:
    """ContentRevisionModelOutput generator using SAP AI Core Orchestration V2.

    Makes exactly ONE text-only API call per revise() request.
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

    def revise(
        self,
        brief: "ConsultingSlideBrief",
        source_material: Optional[str],
        slot_specs: list[dict],
        target_keys: list[str],
        current_draft: "SlideContentDraft",
        revision_feedback: list[dict],
    ) -> ContentRevisionModelOutput:
        """Revise target slots.  Exactly one SAP AI Core call."""
        from slidestein.revision.prompt import (  # noqa: PLC0415
            _SYSTEM_PROMPT,
            build_revision_prompt,
        )

        prompt_text = build_revision_prompt(
            brief=brief,
            source_material=source_material,
            slot_specs=slot_specs,
            target_keys=target_keys,
            revision_feedback=revision_feedback,
        )

        try:
            raw_text = self._run_orchestration(prompt_text, _SYSTEM_PROMPT)
        except ContentRevisionGenerationError:
            raise
        except Exception as exc:
            raise ContentRevisionGenerationError(
                f"SAP AI Core content revision error ({self._model}): "
                f"{type(exc).__name__}"
            ) from exc

        json_text = _strip_fences(raw_text)

        try:
            output = ContentRevisionModelOutput.model_validate_json(json_text)
        except Exception as exc:
            raise ContentRevisionGenerationError(
                f"Content revision response parse error: {type(exc).__name__}. "
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
        raise ContentRevisionGenerationError(
            "No running Orchestration V2 deployment found in resource group. "
            "Ensure an orchestration deployment is running in SAP AI Core."
        )
