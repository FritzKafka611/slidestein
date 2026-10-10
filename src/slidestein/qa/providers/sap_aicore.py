"""SAP AI Core Orchestration V2 implementation of VisualQAReviewer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from slidestein.qa.models import VisualQAModelOutput

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class VisualQAGenerationError(RuntimeError):
    """Raised when visual QA generation fails or returns invalid output."""


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
# SAPAICoreVisualQAReviewer
# ---------------------------------------------------------------------------


class SAPAICoreVisualQAReviewer:
    """VisualQAModelOutput reviewer using SAP AI Core Orchestration V2.

    Makes exactly ONE multimodal API call (three images + text) per review.
    No retry.  No fallback provider.  Direct Anthropic is forbidden.
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

    def review(
        self,
        generated_image: Path,
        template_image: Path,
        overlay_image: Path,
        slot_specs: list[dict],
        native_checks: list[dict],
    ) -> VisualQAModelOutput:
        """Review the rendered slide and return VisualQAModelOutput.

        Exactly one SAP AI Core call is made.  Malformed output raises
        VisualQAGenerationError — no automatic retry.
        """
        from slidestein.qa.prompt import (  # noqa: PLC0415
            _SYSTEM_PROMPT,
            build_visual_qa_prompt,
        )

        prompt_text = build_visual_qa_prompt(
            slot_specs=slot_specs,
            native_checks=native_checks,
        )

        try:
            content = self._build_content(
                generated_image=generated_image,
                template_image=template_image,
                overlay_image=overlay_image,
                prompt_text=prompt_text,
            )
        except Exception as exc:
            raise VisualQAGenerationError(
                f"Failed to build visual QA content: {type(exc).__name__}"
            ) from exc

        try:
            raw_text = self._run_orchestration(content, _SYSTEM_PROMPT)
        except VisualQAGenerationError:
            raise
        except Exception as exc:
            raise VisualQAGenerationError(
                f"SAP AI Core visual QA failed ({self._model}): {type(exc).__name__}"
            ) from exc

        json_text = _strip_fences(raw_text)
        try:
            output = VisualQAModelOutput.model_validate_json(json_text)
        except Exception as exc:
            raise VisualQAGenerationError(
                f"Visual QA response parse error: {type(exc).__name__}. "
                f"Raw response (first 500 chars): {raw_text[:500]!r}"
            ) from exc

        return output

    def _build_content(
        self,
        generated_image: Path,
        template_image: Path,
        overlay_image: Path,
        prompt_text: str,
    ) -> list:
        """Build the SDK content list: text + three images."""
        from gen_ai_hub.orchestration_v2 import ImageItem, TextPart  # noqa: PLC0415

        for img_path in (generated_image, template_image, overlay_image):
            if not img_path.exists():
                raise FileNotFoundError(f"Image not found: {img_path}")

        parts: list = [
            TextPart(text=prompt_text),
            TextPart(text="=== IMAGE 1: GENERATED SLIDE (actual output — primary review subject) ==="),
            ImageItem.from_file(str(generated_image), mime_type="image/png"),
            TextPart(text=(
                "=== IMAGE 2: TEMPLATE REFERENCE (visual style only) ===\n"
                "IMPORTANT: All text visible in this image is historical example content.\n"
                "Do NOT cite, reproduce, or fact-check any text here.\n"
                "Use only for visual design language: hierarchy, spacing, typography, alignment."
            )),
            ImageItem.from_file(str(template_image), mime_type="image/png"),
            TextPart(text=(
                "=== IMAGE 3: K-KEY OVERLAY (slot locator — for referencing specific slots) ===\n"
                "Red bounding boxes and K-key labels show where each semantic slot is located.\n"
                "Use to identify which K-key corresponds to a visual issue."
            )),
            ImageItem.from_file(str(overlay_image), mime_type="image/png"),
        ]
        return parts

    def _run_orchestration(self, content: list, system_prompt: str) -> str:
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
                            SystemMessage(content=system_prompt),
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
        """Discover and cache the running Orchestration V2 deployment ID."""
        if hasattr(self, "_deployment_id_cache"):
            return self._deployment_id_cache  # type: ignore[attr-defined]
        from ai_api_client_sdk.models.status import Status  # noqa: PLC0415

        deployments = self._ai_core_client.deployment.query(status=Status.RUNNING)  # type: ignore[union-attr]
        for d in deployments.resources:
            if getattr(d, "scenario_id", "") == "orchestration":
                self._deployment_id_cache: str = d.id
                return d.id
        raise VisualQAGenerationError(
            "No running Orchestration V2 deployment found in resource group "
            f"'{self._ai_core_client.rest_client.resource_group}'. "  # type: ignore[union-attr]
            "Ensure an orchestration deployment is running in SAP AI Core."
        )
