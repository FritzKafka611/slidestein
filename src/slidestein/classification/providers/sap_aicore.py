"""SAPAICoreClassifier — slide classification via SAP Generative AI Hub Orchestration V2.

Uses gen_ai_hub.orchestration_v2 (sap-ai-sdk-gen).  All SAP-SDK objects are
contained here; nothing SAP-specific leaks into the service or domain layers.

The classifier reuses:
- classification.prompt.build_classification_prompt  (textual prompt, unchanged)
- classification.classifier._strip_markdown_fences   (response sanitiser)
- domain.models.SlideSemanticProfile                 (Pydantic validation)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from slidestein.domain.models import SlideClassificationInput, SlideSemanticProfileV2

if TYPE_CHECKING:
    from ai_core_sdk.ai_core_v2_client import AICoreV2Client

_SYSTEM_PROMPT = (
    "You are a slide classification assistant. "
    "Respond with ONLY valid JSON matching the requested schema. "
    "Do not use markdown code fences or backticks. "
    "Do not add any explanation or commentary. "
    "The response must start with { and end with }."
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_END_RE = re.compile(r"\n?```\s*$")


def _strip_fences(text: str) -> str:
    cleaned = _FENCE_RE.sub("", text)
    cleaned = _FENCE_END_RE.sub("", cleaned)
    return cleaned.strip()


class SAPAICoreClassifier:
    """Classifies slides via SAP Generative AI Hub Orchestration Service V2.

    Parameters
    ----------
    ai_core_client:
        Authenticated ``AICoreV2Client`` instance.
    model:
        Model name as registered in Generative AI Hub (e.g. ``"claude-3.5-sonnet"``).
    max_tokens:
        Maximum tokens for the classification response.
    resource_group:
        SAP AI Core resource group.  Must match the one used in the client.
    """

    DEFAULT_MAX_TOKENS = 2048

    def __init__(
        self,
        ai_core_client: "AICoreV2Client",
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._ai_core_client = ai_core_client
        self._model = model
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # SlideClassifier protocol
    # ------------------------------------------------------------------

    def classify(
        self,
        classification_input: SlideClassificationInput,
    ) -> SlideSemanticProfileV2:
        """Classify *classification_input* via SAP AI Core and return a validated profile.

        Raises
        ------
        SlideClassificationError
            Wraps all failures, including missing preview, SDK errors, and
            JSON that does not validate as SlideSemanticProfile.
        """
        from slidestein.classification.classifier import SlideClassificationError
        from slidestein.classification.prompt import build_classification_prompt

        # Build the textual prompt (unchanged from Anthropic path).
        try:
            prompt_text = build_classification_prompt(classification_input)
        except Exception as exc:
            raise SlideClassificationError(str(exc)) from exc

        # Build message content: optional image + text prompt.
        try:
            content = self._build_content(classification_input, prompt_text)
        except (ValueError, FileNotFoundError, OSError) as exc:
            raise SlideClassificationError(str(exc)) from exc

        # Run through Orchestration V2.
        try:
            raw_text = self._run_orchestration(content)
        except Exception as exc:
            raise SlideClassificationError(
                f"SAP AI Core error classifying slide "
                f"{classification_input.slide_id!r}: {type(exc).__name__}: {exc}"
            ) from exc

        json_text = _strip_fences(raw_text)

        try:
            profile = SlideSemanticProfileV2.model_validate_json(json_text)
        except Exception as exc:
            raise SlideClassificationError(
                f"SAP AI Core returned invalid JSON for slide "
                f"{classification_input.slide_id!r}: {exc}\n"
                f"Raw response (first 500 chars): {raw_text[:500]}"
            ) from exc

        if profile.slide_id != classification_input.slide_id:
            raise SlideClassificationError(
                f"Classifier returned slide_id {profile.slide_id!r} but input "
                f"was {classification_input.slide_id!r}."
            )

        return profile

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_content(
        self,
        classification_input: SlideClassificationInput,
        prompt_text: str,
    ) -> list:
        """Return the content list for a UserMessage."""
        from gen_ai_hub.orchestration_v2 import ImageItem, TextPart

        parts: list = []
        if classification_input.preview_path is not None:
            preview = Path(classification_input.preview_path)
            if not preview.exists():
                raise FileNotFoundError(
                    f"Preview image not found: {preview}"
                )
            parts.append(
                ImageItem.from_file(str(preview), mime_type="image/png")
            )
        parts.append(TextPart(text=prompt_text))
        return parts

    def _run_orchestration(self, content: list) -> str:
        """Send one request to Orchestration V2 and return the response text."""
        from gen_ai_hub.orchestration_v2 import (
            OrchestrationConfig,
            OrchestrationService,
            ModuleConfig,
            PromptTemplatingModuleConfig,
            SystemMessage,
            Template,
            UserMessage,
        )
        from gen_ai_hub.orchestration_v2.models.llm_model_details import LLMModelDetails
        from gen_ai_hub.proxy.gen_ai_hub_proxy.client import GenAIHubProxyClient

        proxy_client = GenAIHubProxyClient(ai_core_client=self._ai_core_client)

        # Build orchestration URL from running deployment — bypasses env-var
        # discovery path in get_orchestration_api_url (which requires separate
        # env credentials that are already in the AICoreV2Client).
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
                            SystemMessage(content=_SYSTEM_PROMPT),
                            UserMessage(content=content),
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
        """Return the ID of the running Orchestration V2 deployment.

        Queries running deployments and returns the first with
        scenario_id == 'orchestration'.  Result is cached per instance.
        """
        if hasattr(self, "_deployment_id_cache"):
            return self._deployment_id_cache
        from ai_api_client_sdk.models.status import Status
        deployments = self._ai_core_client.deployment.query(status=Status.RUNNING)
        for d in deployments.resources:
            if getattr(d, "scenario_id", "") == "orchestration":
                self._deployment_id_cache = d.id
                return d.id
        raise RuntimeError(
            "No running Orchestration V2 deployment found in resource group "
            f"'{self._ai_core_client.rest_client.resource_group}'. "
            "Create one via SAP AI Launchpad before running classifications."
        )
