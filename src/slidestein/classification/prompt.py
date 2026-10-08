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

_SLIDE_FUNCTIONS = """\
  content         — A slide that delivers substantive consulting content.
                    Requires a non-null primary_communication_job.
  cover           — Opening or title slide for the deck or a major section.
                    primary_communication_job must be null.
  section_divider — Structural divider that marks the start of a new section.
                    Often shows just a word or phrase (e.g. "Timeline",
                    "Appendix", "Workstreams"). Visual structure is minimal.
                    primary_communication_job must be null.
  closing         — Final slide of the deck (thank-you, Q&A, contact page).
                    primary_communication_job must be null."""

_COMMUNICATION_JOBS = """\
  explain          — Clarify how something works or what something means.
  summarise        — Condense a broader set of findings or information.
  compare          — Contrast two or more alternatives, entities or states.
  diagnose         — Explain causes, problems or underlying issues.
  prioritise       — Rank or select topics based on importance or criteria.
  recommend        — Advocate a preferred course of action.
  show_change      — Show movement from one state to another over time.
  show_process     — Explain a sequence of activities.
                     REQUIRES an explicit visual or conceptual sequence,
                     flow, or ordered set of stages.
                     Positive signals: arrows between steps, numbered
                     sequential steps, left-to-right progression, lifecycle,
                     input → transformation → output.
                     NOT applicable to: project charters, workstream
                     summaries, lists of deliverables, or activities listed
                     without a visual sequence.
  show_timeline    — Show events or actions over TIME.
                     REQUIRES that time is visually encoded on the slide:
                     a calendar axis, dates arranged spatially, weeks/months/
                     quarters, milestones positioned along time, or activity
                     bars across a time axis.
                     A section-divider slide whose title is "Timeline" does
                     NOT show a timeline — use slide_function=section_divider.
  show_hierarchy   — Show layered levels of authority, governance levels,
                     prioritisation tiers, or nested structures.
                     Use for governance models, accountability levels,
                     escalation paths, and conceptual hierarchies where
                     REPORTING RELATIONSHIPS between people/teams are NOT
                     the primary organising principle.
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
  text_heavy       — Predominantly text: bullet lists, paragraphs, narrative
                     without a dominant reusable form structure.
  structured_one_pager — A single-page profile composed of multiple LABELED
                     sections or rows, summarising one initiative, workstream,
                     entity, project, or similar object.
                     Typical pattern: labeled rows (Team, Objective,
                     Deliverables, Dependencies, Success Measures) each with
                     a content block to the right.
                     Use this INSTEAD of text_heavy when the slide has a
                     clear form-like information architecture with labeled
                     categories, even if it contains substantial text.
                     Do NOT use text_heavy for this pattern.
  metric_row       — KPI callout boxes arranged in a row or grid.
  comparison       — Side-by-side structure contrasting two or more alternatives.
  before_after     — Explicit current-state / future-state or before / after.
  funnel           — Progressive narrowing or filtering structure.
  pyramid          — Hierarchical argument or MECE structure shown as a pyramid.
  matrix           — Information organised across two explicit dimensions.
  timeline         — Events or milestones organised chronologically.
  roadmap          — Forward-looking sequence of initiatives or stages across
                     a time axis with multiple workstreams or tracks.
  process          — Sequential operating or process steps with numbered stages.
  flow             — Nodes connected through directional relationships.
  hierarchy        — Nested or layered information structure showing authority
                     levels, governance tiers, or conceptual levels.
                     Use when the primary organising logic is layered levels
                     rather than reporting relationships between people/teams.
  org_chart        — People, roles, or units displayed through REPORTING
                     relationships (who reports to whom).
                     Use ONLY when explicit organisational reporting lines
                     between named people, roles, or teams dominate the slide.
                     Do NOT use for governance models or layered authority
                     structures — use hierarchy instead.
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

CRITICAL RULE: VISUAL STRUCTURE MUST TAKE PRECEDENCE OVER TOPIC WORDS.
Do NOT infer slide_function or communication_job from words such as "Timeline",
"Workstreams", "Process", "Governance", "Roadmap", or "Organization" appearing
in a title or headline. Classify based on what the slide VISUALLY DOES.

═══ CLASSIFICATION ORDER OF REASONING ═══

Follow these steps in order:

STEP 1 — SLIDE FUNCTION
Examine the overall visual structure.
Is this a cover slide, section divider, closing slide, or a content slide?
A section divider typically has minimal content: a single word or phrase and
a decorative element. It does not show data, process, hierarchy, or a timeline.

STEP 2 — VISUAL ARCHETYPE
Examine the layout geometry and information-design structure.
Select the single best archetype based on what you see, not what the topic is.

STEP 3 — COMMUNICATION JOB (only for content slides)
If slide_function == "content", determine what communication work this slide does.
If slide_function is cover / section_divider / closing:
  Set primary_communication_job to null.
  Set secondary_communication_jobs to [].
  Do not assign a communication job to a navigational slide.

STEP 4 — STORYLINE ROLES
Assign 1–2 roles that genuinely apply. Navigational slides typically get
["context"] or ["summary"].

STEP 5 — STRUCTURAL PATTERN
Describe the REUSABLE LAYOUT GRAMMAR of this slide in 1–2 sentences.
Focus on visual structure, not business content.

STEP 6 — DESCRIPTION / BEST FOR / NOT FOR
Write for retrieval. Describe the template capability, not the specific
client situation.

═══ SLIDE FUNCTIONS ═══

{slide_functions}

═══ CANONICAL COMMUNICATION JOBS ═══
Pick ONE primary job and optionally one or more secondary jobs (content slides only).
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

═══ STRUCTURED ONE-PAGER RECOGNITION ═══
A structured_one_pager has labeled rows or sections (e.g. Team, Objective,
Deliverables, Dependencies, Measures of Success) each with a corresponding
content block. The defining characteristic is: ONE OBJECT described across
MULTIPLE STANDARDIZED LABELED FIELDS on a SINGLE PAGE.
Use structured_one_pager instead of text_heavy for this pattern.

═══ STRUCTURAL PATTERN ═══
Describe the REUSABLE LAYOUT GRAMMAR of this slide in 1–2 sentences.
Focus on information-design structure — NOT on business content.

Good: "Answer-first title above a two-column comparison with three stacked evidence blocks per side."
Good: "Headline above full-width bar chart with narrow right-hand implication callout."
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

For a CONTENT slide:
{{
  "slide_id": "{slide_id}",
  "schema_version": "2.0",
  "slide_function": "content",
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

For a NON-CONTENT slide (cover, section_divider, closing):
{{
  "slide_id": "{slide_id}",
  "schema_version": "2.0",
  "slide_function": "<cover | section_divider | closing>",
  "primary_communication_job": null,
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
        slide_functions=_SLIDE_FUNCTIONS,
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
