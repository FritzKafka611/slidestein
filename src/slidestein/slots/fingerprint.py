"""Fingerprint and stable-ID utilities for slot analysis (M5.2).

compute_slot_id: deterministic UUID5 from (slide_id, shape_path).
compute_slot_analysis_input_fingerprint: SHA-256 of candidates + versions.
"""

from __future__ import annotations

import hashlib
import json
import uuid

# Fixed namespace for slot-id generation.  Must never change once in production.
_SLOT_ID_NAMESPACE = uuid.UUID("1b4b5c6d-7e8f-5a0b-c1d2-e3f4a5b6c7d8")


def compute_slot_id(slide_id: str, shape_path: str) -> str:
    """Return a stable UUID5 string identifying one slot within a slide.

    Deterministic: same (slide_id, shape_path) always produces the same UUID.
    """
    key = f"{slide_id}:{shape_path}"
    return str(uuid.uuid5(_SLOT_ID_NAMESPACE, key))


def compute_slot_analysis_input_fingerprint(
    slide_id: str,
    candidates: list[dict],  # ordered list of compact candidate dicts
    slot_map_schema_version: str,
    prompt_version: str,
) -> str:
    """Return a SHA-256 hex digest committing to the analysis inputs.

    A fingerprint mismatch means the slide structure, schema, or prompt has
    changed since the last analysis — the cached result is stale.

    ``candidates`` must be sorted by candidate key before hashing to ensure
    determinism; callers are responsible for ordering.
    """
    payload = json.dumps(
        {
            "slide_id": slide_id,
            "candidates": candidates,
            "slot_map_schema_version": slot_map_schema_version,
            "prompt_version": prompt_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
