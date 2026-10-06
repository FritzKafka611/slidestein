"""Classification prompt construction and image encoding.

This module has zero Anthropic SDK imports.  All exceptions raised here are
standard Python exceptions (ValueError, FileNotFoundError, OSError).
AnthropicSlideClassifier wraps them as SlideClassificationError at the service
boundary.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from slidestein.domain.models import SlideClassificationInput

# ---------------------------------------------------------------------------
# Image encoding
# ---------------------------------------------------------------------------

#: Supported preview extensions and their Anthropic API media_type strings.
SUPPORTED_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def encode_image(preview_path: Path) -> tuple[str, str]:
    """Return *(media_type, base64_data)* for a PNG or JPEG preview.

    Raises
    ------
    ValueError
        Extension is not a supported image type.
    FileNotFoundError
        The file does not exist at *preview_path*.
    OSError
        The file exists but cannot be read.
    """
    suffix = preview_path.suffix.lower()
    media_type = SUPPORTED_MEDIA_TYPES.get(suffix)
    if media_type is None:
        supported = ", ".join(sorted(SUPPORTED_MEDIA_TYPES))
        raise ValueError(
            f"Unsupported preview image type {suffix!r}. "
            f"Supported extensions: {supported}"
        )
    if not preview_path.exists():
        raise FileNotFoundError(f"Preview image not found: {preview_path}")
    try:
        raw = preview_path.read_bytes()
    except OSError as exc:
        raise OSError(f"Cannot read preview image {preview_path}: {exc}") from exc

    return media_type, base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

_COMMUNICATION_JOBS = """\
  explain          — Clarify how something works or what something means.
  summarise        — Condense a broader set of findings or information.
  compare          — Contrast two or more alternatives, entities or states.
  diagnose         — Explain causes, problems or underlying issues.
  prioritise       — Rank or select topics based on importance or criteria.
  recommend        — Advocate a preferred course of action.
  show_change      — Show movement from one state to another over time.
  show_process     — Explain a sequence of activities or operating steps.
  show_timeline    — Show events or actions over time.
  show_hierarchy   — Show levels, reporting relationships or nested structure.
  show_performance — Show KPIs, outcomes or performance versus benchmarks.
  show_drivers     — Explain factors contributing to an outcome.
  show_options     — Present alternative choices without recommending one.
  show_relationship — Explain connections, dependencies or interactions."""

_STORYLINE_ROLES = """\
  context        — Sets up the situation; provides necessary background.
  diagnosis      — Identifies and explains what is wrong or why performance is off.
  insight        — Delivers the key so-what; a non-obvious observation.
  implication    — Explains what the insight means for the audience.
  recommendation — Advocates a specific course of action.
  decision       — Frames a choice that must be made.
  plan           — Describes the path forward; milestones or workstreams.
  evidence       — Provides supporting data, research or examples.
  summary        — Wraps up and re-states the key messages."""

_VISUAL_ARCHETYPES = """\
  title            — Title-only or cover slide structure.
  key_message      — Single prominent headline with minimal supporting content.
  text_heavy       — Predominantly text: bullet lists, paragraphs, narrative.
  metric_row       — KPI callout boxes arranged in a row or grid.
  comparison       — Side-by-side structure contrasting two or more alternatives.
  before_after     — Explicit current-state / future-state or before / after.
  funnel           — Progressive narrowing or filtering structure.
  pyramid          — Hierarchical argument or MECE structure shown as a pyramid.
  matrix           — Information organised across two explicit dimensions.
  timeline         — Events or milestones organised chronologically.
  roadmap          — Forward-looking sequence of initiatives or stages.
  process          — Sequential operating or process steps with numbered stages.
  flow             — Nodes connected through directional relationships.
  hierarchy        — Nested or layered information structure.
  org_chart        — People or units displayed through reporting hierarchy.
  portfolio        — Set of initiatives or entities shown as a managed collection.
  status_dashboard — Multiple KPIs or status indicators presented together.
  bar_chart        — Bar-based quantitative exhibit (grouped or stacked bars).
  line_chart       — Trend-based quantitative exhibit with one or more series.
  waterfall        — Bridge from starting value to ending value showing contributions.
  pie_chart        — Part-to-whole circular exhibit.
  table            — Tabular row/column exhibit.
  mixed_exhibit    — Multiple materially different exhibit types; no dominant archetype."""

_PROMPT_TEMPLATE = """\
You are an expert strategy-consulting slide librarian and information-design classifier.

Your task: classify the consulting slide below into a reusable semantic profile.
Focus on the slide's COMMUNICATION FUNCTION and INFORMATION-DESIGN STRUCTURE.
Do NOT describe the specific business content of this particular client engagement.

Your classification must describe a TEMPLATE FOR A CLASS OF COMMUNICATION SITUATIONS.
It must remain useful even if this slide's company names and numbers are replaced.

═══ CANONICAL COMMUNICATION JOBS ═══
Pick ONE primary job and optionally one or more secondary jobs.
Most slides have a single dominant job — avoid over-tagging.

{communication_jobs}

═══ CANONICAL STORYLINE ROLES ═══
List all roles that genuinely apply to this slide's narrative function.
Most slides serve 1–2 roles. Assign a role only when the slide clearly fulfils it.

{storyline_roles}

═══ CANONICAL VISUAL ARCHETYPES ═══
Pick the SINGLE most dominant information-design archetype.
Classify based on the slide's primary structure, not minor decorative elements.
If no single archetype dominates, use: mixed_exhibit

{visual_archetypes}

═══ STRUCTURAL PATTERN ═══
Describe the REUSABLE LAYOUT GRAMMAR of this slide in 1–2 sentences.
Focus on information-design structure — NOT on business content.

Good layout pattern:  "Answer-first title above a two-column comparison with three stacked evidence blocks per side."
Good layout pattern:  "Headline above full-width bar chart with narrow right-hand implication callout."
Bad (business content): "Slide comparing SAP and Oracle across five criteria."

═══ DESCRIPTION ═══
Write a concise description of what this slide communicates and how.
Make it useful for retrieval.
Example: "Compares two operating-model alternatives across five criteria and highlights the preferred option."

═══ BEST FOR / NOT FOR ═══
best_for: list 2–4 reusable consulting applications this slide PATTERN suits well.
not_for:  list 1–3 applications this slide pattern is poorly suited to.
Keep entries general — describe template capability, not this slide's specific topic.

Good best_for entry: "comparing two strategic alternatives across common criteria"
Bad best_for entry (too specific): "comparing SAP and Oracle ERP systems"

═══════════════════════════════════════
SLIDE TO CLASSIFY

SLIDE ID: {slide_id}

EXTRACTED TEXT:
{extracted_text}

STRUCTURAL METADATA:
{structural_metadata_json}

VISUAL PREVIEW AVAILABLE: {preview_available}
═══════════════════════════════════════

Classify the slide above. Respond with ONLY a JSON object — no markdown fences,
no prose, no explanation. Required fields (slide_id must be exactly "{slide_id}"):

{{
  "slide_id": "{slide_id}",
  "schema_version": "1.0",
  "primary_communication_job": "<one value from the canonical jobs list above>",
  "secondary_communication_jobs": [],
  "storyline_roles": ["<one or more values from the canonical roles list above>"],
  "visual_archetype": "<one value from the canonical archetypes list above>",
  "structural_pattern": "<1-2 sentences describing the reusable layout grammar>",
  "density": "<low | medium | high>",
  "description": "<concise retrieval-oriented description>",
  "best_for": ["<2-4 general consulting applications>"],
  "not_for": ["<1-3 applications this pattern suits poorly>"]
}}
"""


def build_classification_prompt(classification_input: SlideClassificationInput) -> str:
    """Build the full textual classification prompt from *classification_input*.

    The prompt includes semantic guidance for every canonical taxonomy, slide
    evidence (ID, extracted text, structural metadata), and an explicit indicator
    of whether a visual preview is available.  Keys in structural_metadata are
    sorted for deterministic output.
    """
    has_preview = classification_input.preview_path is not None
    meta_json = json.dumps(
        classification_input.structural_metadata,
        indent=2,
        sort_keys=True,
        default=str,
    )
    extracted = classification_input.extracted_text.strip() or "(no extracted text)"

    return _PROMPT_TEMPLATE.format(
        communication_jobs=_COMMUNICATION_JOBS,
        storyline_roles=_STORYLINE_ROLES,
        visual_archetypes=_VISUAL_ARCHETYPES,
        slide_id=classification_input.slide_id,
        extracted_text=extracted,
        structural_metadata_json=meta_json,
        preview_available="yes" if has_preview else "no",
    )


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------


def build_messages(
    classification_input: SlideClassificationInput,
) -> list[dict]:
    """Build the Anthropic ``messages`` list for a classification request.

    If *preview_path* is set, an image content block is placed first, before
    the textual classification prompt.  If no preview is available, the prompt
    alone is sent — this is a supported degraded path that classifies from
    extracted text and structural metadata only.

    Raises
    ------
    ValueError
        Propagated from encode_image for unsupported file extensions.
    FileNotFoundError
        Propagated from encode_image when the preview file is missing.
    OSError
        Propagated from encode_image when the file cannot be read.
    """
    prompt_text = build_classification_prompt(classification_input)
    content: list[dict] = []

    if classification_input.preview_path is not None:
        media_type, b64_data = encode_image(classification_input.preview_path)
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                },
            }
        )

    content.append({"type": "text", "text": prompt_text})

    return [{"role": "user", "content": content}]
