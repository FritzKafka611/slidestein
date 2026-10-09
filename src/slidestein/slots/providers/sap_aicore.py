"""SAP AI Core Orchestration V2 implementation of SlotSemanticAnalyzer (M5.2).

Makes exactly ONE Vision call per slide.  The pattern follows M4.3
(SAPAICoreVisionReranker) exactly: ImageItem.from_file() + UserMessage with
interleaved TextPart and ImageItem content.

Direct Anthropic API must NOT be used — all calls go through SAP AI Core
Orchestration V2.
"""

from __future__ import annotations

import re

from slidestein.slots.analysis_models import SlotAnalysisModelOutput
from slidestein.slots.models import NativeShapeDescriptor
from slidestein.slots.prompt import _SYSTEM_PROMPT, build_slot_analysis_prompt


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class SlotAnalysisError(RuntimeError):
    """Raised when slot analysis fails (SDK, parse, or validation error)."""


# ---------------------------------------------------------------------------
# Fence stripping
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)
_FENCE_END_RE = re.compile(r"\n?```\s*$")


def _strip_fences(text: str) -> str:
    cleaned = _FENCE_RE.sub("", text)
    cleaned = _FENCE_END_RE.sub("", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# SAPAICoreSlotSemanticAnalyzer
# ---------------------------------------------------------------------------


class SAPAICoreSlotSemanticAnalyzer:
    """Slot semantic analyzer using SAP AI Core Orchestration V2 (Vision).

    Makes exactly ONE multimodal API call per analyze() invocation.
    """

    DEFAULT_MAX_TOKENS = 16384

    def __init__(
        self,
        ai_core_client: object,
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._ai_core_client = ai_core_client
        self._model = model
        self._max_tokens = max_tokens

    def analyze(
        self,
        preview_path: str,
        candidates: dict[str, NativeShapeDescriptor],
    ) -> SlotAnalysisModelOutput:
        """Run Vision analysis for one slide.  Exactly one SDK call."""
        try:
            content = self._build_content(preview_path, candidates)
        except Exception as exc:
            raise SlotAnalysisError(
                f"Failed to build slot analysis content: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            raw_text = self._run_orchestration(content)
        except SlotAnalysisError:
            raise
        except Exception as exc:
            raise SlotAnalysisError(
                f"SAP AI Core slot analysis error ({self._model}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        json_text = _strip_fences(raw_text)
        try:
            output = SlotAnalysisModelOutput.model_validate_json(json_text)
        except Exception as exc:
            raise SlotAnalysisError(
                f"Slot analysis response parse error: {type(exc).__name__}: {exc}. "
                f"Raw response (first 500 chars): {raw_text[:500]!r}"
            ) from exc

        # Validate: model must not invent candidate keys or drop supplied ones
        supplied_keys = set(candidates.keys())
        returned_keys = {a.candidate_key for a in output.assessments}
        unknown = returned_keys - supplied_keys
        missing = supplied_keys - returned_keys
        if unknown or missing:
            parts = []
            if unknown:
                parts.append(f"unknown keys not in supplied set: {sorted(unknown)}")
            if missing:
                parts.append(f"missing keys from supplied set: {sorted(missing)}")
            raise SlotAnalysisError(
                f"Vision candidate coverage violation — " + "; ".join(parts)
            )

        return output

    def _build_content(
        self,
        preview_path: str,
        candidates: dict[str, NativeShapeDescriptor],
    ) -> list:
        """Build [TextPart(intro), ImageItem(preview), TextPart(prompt+schema)]."""
        from pathlib import Path  # noqa: PLC0415

        from gen_ai_hub.orchestration_v2 import ImageItem, TextPart  # noqa: PLC0415

        preview = Path(preview_path)
        if not preview.exists():
            raise FileNotFoundError(f"Preview image not found: {preview}")

        prompt_text = build_slot_analysis_prompt(candidates)
        return [
            TextPart(text="Analyse the following consulting slide as a reusable template:"),
            ImageItem.from_file(str(preview), mime_type="image/png"),
            TextPart(text=prompt_text),
        ]

    def _run_orchestration(self, content: list) -> str:
        """Execute the Orchestration V2 call and return raw response text."""
        from gen_ai_hub.orchestration_v2 import (  # noqa: PLC0415
            ModuleConfig,
            OrchestrationConfig,
            OrchestrationService,
            PromptTemplatingModuleConfig,
            SystemMessage,
            Template,
            UserMessage,
        )
        from gen_ai_hub.orchestration_v2.models.llm_model_details import LLMModelDetails  # noqa: PLC0415
        from gen_ai_hub.proxy.gen_ai_hub_proxy.client import GenAIHubProxyClient  # noqa: PLC0415

        proxy_client = GenAIHubProxyClient(ai_core_client=self._ai_core_client)
        deployment_id = self._get_orchestration_deployment_id()
        api_url = (
            f"{self._ai_core_client.base_url.rstrip('/')}"  # type: ignore[union-attr]
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
        if hasattr(self, "_deployment_id_cache"):
            return self._deployment_id_cache  # type: ignore[attr-defined]
        from ai_api_client_sdk.models.status import Status  # noqa: PLC0415

        deployments = self._ai_core_client.deployment.query(status=Status.RUNNING)  # type: ignore[union-attr]
        for d in deployments.resources:
            if getattr(d, "scenario_id", "") == "orchestration":
                self._deployment_id_cache: str = d.id
                return d.id
        raise SlotAnalysisError(
            "No running Orchestration V2 deployment found in resource group "
            f"'{self._ai_core_client.rest_client.resource_group}'.  "  # type: ignore[union-attr]
            "Ensure an orchestration deployment is running in SAP AI Core."
        )
