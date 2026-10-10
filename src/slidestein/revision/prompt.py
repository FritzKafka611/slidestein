"""Prompt construction for M9 content revision (v1.1).

The revision prompt is grounded in three factual sources ONLY:
  - brief.original_request
  - brief.key_message
  - source_material (if provided)

Review scores and review comments are presented as ADVISORY feedback only —
they are NOT factual evidence and must not override the source material.
Template current_text is NEVER included as a factual source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from slidestein.briefing.brief import ConsultingSlideBrief

_SYSTEM_PROMPT = """\
You are a McKinsey/BCG-caliber content editor revising a consulting slide draft.
Your role is to tighten and improve specific text slots — not to rewrite the entire slide.

FACTUAL GROUNDING RULE:
  - Base ALL content on: (1) the slide brief, (2) the source material provided.
  - Do NOT invent facts, statistics, or claims not present in the source material.
  - Do NOT use slide template text as factual input.
  - Reviewer feedback is ADVISORY — it highlights potential issues but is NOT factual evidence.
    Do not treat reviewer comments as ground truth about what is or is not factually correct.

REVISION CONSTRAINTS:
  - Only revise the TARGET SLOTS listed in the prompt.
  - Unmentioned slots must NOT be changed.
  - Never clear (empty) a slot — only provide replacement text.
  - Revised text must fit within the capacity limits provided.
  - Prefer shorter, tighter phrasing over long explanations.
  - Preserve the original message intent — do not change facts or conclusions.
  - If you cannot produce a valid revision within the constraints, set status="blocked"
    and explain why in blocked_reason.

Respond with ONLY valid JSON matching the requested schema.
Do not use markdown code fences or backticks.
Do not add any explanation or commentary.
The response must start with { and end with }.
"""


def build_revision_prompt(
    brief: "ConsultingSlideBrief",
    source_material: Optional[str],
    slot_specs: list[dict],
    target_keys: list[str],
    revision_feedback: Optional[list[dict]] = None,
) -> str:
    """Build the user message for a content revision call.

    slot_specs: list of dicts with keys: key, role, label, action, text,
                capacity_characters, capacity_utilization, max_lines_estimate.
    target_keys: K-keys to revise (subset of slot_specs keys).
    revision_feedback: optional list of feedback dicts from M7/M8, presented
                       as ADVISORY input only (not factual evidence).
    """
    if revision_feedback is None:
        revision_feedback = []

    lines: list[str] = []

    # --- SLIDE BRIEF ---------------------------------------------------------
    lines.append("=== SLIDE BRIEF ===")
    lines.append(f"Original request: {brief.original_request}")
    lines.append(f"Key message: {brief.key_message}")
    if brief.slide_function:
        lines.append(f"Slide function: {brief.slide_function.value}")
    if brief.primary_communication_job:
        lines.append(f"Communication job: {brief.primary_communication_job.value}")
    if brief.required_content_elements:
        lines.append("Required content elements:")
        for elem in brief.required_content_elements:
            lines.append(f"  - {elem}")

    # --- FACTUAL SOURCE MATERIAL --------------------------------------------
    lines.append("")
    lines.append("=== FACTUAL SOURCE MATERIAL ===")
    if source_material and source_material.strip():
        lines.append(source_material.strip())
    else:
        lines.append("(none provided)")

    # --- CURRENT DRAFT CONTENT ----------------------------------------------
    lines.append("")
    lines.append("=== CURRENT DRAFT CONTENT (all slots) ===")
    for spec in slot_specs:
        key = spec["key"]
        marker = " <-- REVISE THIS SLOT" if key in target_keys else ""
        action = spec.get("action", "replace")
        if action == "replace":
            text = spec.get("text") or ""
            cap_chars = spec.get("capacity_characters", 0)
            util_pct = int(spec.get("capacity_utilization", 0.0) * 100)
            max_lines = spec.get("max_lines_estimate", 0)
            lines.append(
                f"{key} [{spec.get('role', '')}] {spec.get('label', '')}{marker}"
            )
            lines.append(f"  Text: {text!r}")
            lines.append(
                f"  Capacity: {cap_chars} chars / {max_lines} lines "
                f"(current usage: {util_pct}%)"
            )
        elif action == "clear":
            lines.append(f"{key} [{spec.get('role', '')}] {spec.get('label', '')} [CLEARED]")
        else:
            lines.append(f"{key} [{spec.get('role', '')}] {spec.get('label', '')} [NEEDS_INPUT]")

    # --- REVISION FEEDBACK (ADVISORY) ----------------------------------------
    if revision_feedback:
        lines.append("")
        lines.append("=== REVISION FEEDBACK (ADVISORY — not factual evidence) ===")
        lines.append(
            "The following feedback is from automated quality reviewers. "
            "It is ADVICE to guide your revision — it is NOT factual evidence. "
            "Do not treat reviewer comments as ground truth. "
            "Base all content only on the brief and source material above."
        )
        for item in revision_feedback:
            source = item.get("source", "reviewer")
            severity = item.get("severity", "")
            category = item.get("category", "")
            slot_keys = item.get("slot_keys", [])
            issue = item.get("issue", "")
            recommendation = item.get("recommendation", "")
            parts = [f"[{source}]"]
            if severity:
                parts.append(f"{severity.upper()}")
            if category:
                parts.append(f"{category}")
            if slot_keys:
                parts.append(f"({', '.join(slot_keys)})")
            if issue:
                parts.append(f"Issue: {issue}")
            if recommendation:
                parts.append(f"Advice: {recommendation}")
            lines.append("  " + " | ".join(parts))

    # --- REVISION TASK -------------------------------------------------------
    lines.append("")
    lines.append("=== REVISION TASK ===")
    lines.append(
        f"Revise ONLY the following slot(s): {', '.join(target_keys)}"
    )
    lines.append(
        "For each target slot, provide shorter, tighter text that "
        "fits within the capacity limits."
    )
    lines.append(
        "Do NOT change any other slots. Do NOT clear any slot. "
        "Do NOT add facts not present in the source material."
    )

    # --- OUTPUT SCHEMA -------------------------------------------------------
    lines.append("")
    lines.append("=== OUTPUT SCHEMA ===")
    lines.append(
        'Respond with JSON exactly matching this schema (no extra fields):'
    )
    lines.append("{")
    lines.append('  "status": "revised",')
    lines.append('  "changes": [')
    lines.append(
        '    {"key": "<K-key>", "action": "replace", "text": "<revised text for that slot>"}'
    )
    lines.append("  ],")
    lines.append('  "change_summary": "<one sentence explaining changes>",')
    lines.append('  "blocked_reason": null')
    lines.append("}")
    lines.append(
        'Include one entry in "changes" per target slot. '
        'Set status="blocked" and blocked_reason="<reason>" if you cannot produce '
        "a valid revision within the given constraints."
    )

    return "\n".join(lines)
