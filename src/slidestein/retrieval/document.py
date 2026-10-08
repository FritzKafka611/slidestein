"""Deterministic retrieval document builder for SlideSemanticProfileV2.

The document captures WHAT COMMUNICATION JOB the slide template can perform
and WHAT STRUCTURE it provides — not client-specific content.

Excluded intentionally:
- slide_id, deck_id, slide_number, fingerprints, timestamps
- raw extracted slide text (topic leakage)
- not_for (negative phrases reduce retrieval accuracy)
- provider/model metadata
"""

from __future__ import annotations

from slidestein.domain.models import SlideSemanticProfileV2


def build_retrieval_document(profile: SlideSemanticProfileV2) -> str:
    """Convert a V2 profile into a retrieval-optimised text document.

    Output is deterministic: identical profiles produce identical documents.
    """
    lines: list[str] = []

    lines.append(f"Slide function: {profile.slide_function.value}")

    if profile.primary_communication_job is not None:
        lines.append(f"Communication job: {profile.primary_communication_job.value}")
    else:
        lines.append("Communication job: none")

    if profile.secondary_communication_jobs:
        jobs_str = ", ".join(j.value for j in profile.secondary_communication_jobs)
        lines.append(f"Secondary communication jobs: {jobs_str}")
    else:
        lines.append("Secondary communication jobs: none")

    roles_str = ", ".join(r.value for r in profile.storyline_roles)
    lines.append(f"Storyline roles: {roles_str}")

    lines.append(f"Visual archetype: {profile.visual_archetype.value}")
    lines.append(f"Density: {profile.density.value}")
    lines.append("")
    lines.append("Description:")
    lines.append(profile.description.strip())
    lines.append("")
    lines.append("Structural pattern:")
    lines.append(profile.structural_pattern.strip())

    if profile.best_for:
        lines.append("")
        lines.append("Best for:")
        for item in profile.best_for:
            lines.append(f"- {item}")

    return "\n".join(lines)
