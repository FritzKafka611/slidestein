"""SAPAICoreStructuralTemplateSelector — Vision-based structural template selection.

One Vision call maximum per M10 recovery cycle.
No retry.
Direct Anthropic: FORBIDDEN.

Provider-boundary contract:
  preflight()        — deterministic prompt + content assembly.  Zero external calls.
  select_prepared()  — single Vision call.  Provider counter incremented before this.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from slidestein.structural.selector import (
    StructuralSelectionPreflight,
    _SYSTEM_PROMPT,
    build_structural_selection_prompt,
)

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief
    from slidestein.qa.models import VisualQAIssue
    from slidestein.structural.models import (
        StructuralCandidateInfo,
        StructuralSelectionOutput,
    )
    from slidestein.structural.selector import StructuralSelectionPreflight

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE)
_FENCE_END_RE = re.compile(r"\n?```\s*$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    text = _FENCE_RE.sub("", text)
    text = _FENCE_END_RE.sub("", text)
    return text.strip()


class StructuralSelectorGenerationError(RuntimeError):
    """Raised when the SAP AI Core provider fails structural template selection."""


class SAPAICoreStructuralTemplateSelector:
    """One-shot structural template selection via SAP AI Core Vision."""

    def __init__(self, ai_core_client: object, model: str, max_tokens: int = 1024) -> None:
        self._ai_core_client = ai_core_client
        self._model = model
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # preflight — deterministic, zero external calls
    # ------------------------------------------------------------------

    def preflight(
        self,
        brief: "ConsultingSlideBrief",
        structural_issues: "list[VisualQAIssue]",
        candidates: "list[StructuralCandidateInfo]",
        current_slide_id: str,
        rendered_images: "dict[str, Path]",
        current_template_image: "Optional[Path]",
    ) -> StructuralSelectionPreflight:
        """Assemble prompt text and multimodal content parts — no external call."""
        prompt_text = build_structural_selection_prompt(
            brief=brief,
            structural_issues=structural_issues,
            candidates=candidates,
            current_slide_id=current_slide_id,
        )
        content_parts = self._build_content(
            prompt_text=prompt_text,
            candidates=candidates,
            rendered_images=rendered_images,
            current_template_image=current_template_image,
        )
        return StructuralSelectionPreflight(
            prompt_text=prompt_text,
            content_parts=content_parts,
        )

    # ------------------------------------------------------------------
    # select_prepared — single external Vision call
    # ------------------------------------------------------------------

    def select_prepared(
        self,
        preflight: "StructuralSelectionPreflight",
        valid_keys: "set[str]",
    ) -> "StructuralSelectionOutput":
        """Execute one Vision call with the pre-assembled content.

        Raises StructuralSelectorGenerationError on provider failure or
        invalid/unrecognised selected_candidate_key.
        """
        from slidestein.structural.models import StructuralSelectionOutput  # noqa: PLC0415

        raw = self._run_orchestration(preflight.content_parts)
        json_text = _strip_fences(raw)

        try:
            from pydantic import BaseModel, ConfigDict  # noqa: PLC0415

            class _SelOut(BaseModel):
                model_config = ConfigDict(extra="forbid")
                selected_candidate_key: str
                rationale: str

            parsed = _SelOut.model_validate_json(json_text)
        except Exception as exc:
            raise StructuralSelectorGenerationError(
                f"Failed to parse structural selector response: {type(exc).__name__}. "
                f"Raw response (first 200 chars): {raw[:200]!r}"
            ) from exc

        if not parsed.selected_candidate_key.strip():
            raise StructuralSelectorGenerationError(
                "Structural selector returned empty selected_candidate_key."
            )

        if parsed.selected_candidate_key not in valid_keys:
            raise StructuralSelectorGenerationError(
                f"Structural selector returned unknown key "
                f"{parsed.selected_candidate_key!r}. "
                f"Valid keys: {sorted(valid_keys)}"
            )

        return StructuralSelectionOutput(
            selected_candidate_key=parsed.selected_candidate_key,
            rationale=parsed.rationale,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_content(
        self,
        prompt_text: str,
        candidates: "list[StructuralCandidateInfo]",
        rendered_images: "dict[str, Path]",
        current_template_image: "Optional[Path]",
    ) -> list:
        """Build the multimodal content list — no external call."""
        from gen_ai_hub.orchestration_v2 import ImageItem, TextPart  # noqa: PLC0415

        parts: list = [TextPart(text=prompt_text)]

        if current_template_image and current_template_image.exists():
            parts.append(TextPart(text="\n\n--- Current failed template (reference) ---\n"))
            parts.append(ImageItem.from_file(str(current_template_image), mime_type="image/png"))

        parts.append(TextPart(text="\n\n--- Candidate slides ---\n"))
        for cand in candidates:
            img_path = rendered_images.get(cand.candidate_key)
            if img_path and img_path.exists():
                parts.append(TextPart(text=f"\nCandidate {cand.candidate_key}:\n"))
                parts.append(ImageItem.from_file(str(img_path), mime_type="image/png"))

        return parts

    def _run_orchestration(self, content: list) -> str:
        """Execute one Orchestration V2 call and return the raw text response."""
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
        try:
            response = service.run()
        except Exception as exc:
            raise StructuralSelectorGenerationError(
                f"Orchestration V2 call failed: {type(exc).__name__}"
            ) from exc
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
        raise StructuralSelectorGenerationError(
            "No running Orchestration V2 deployment found in resource group "
            f"'{self._ai_core_client.rest_client.resource_group}'. "  # type: ignore[union-attr]
            "Ensure an orchestration deployment is running in SAP AI Core."
        )
