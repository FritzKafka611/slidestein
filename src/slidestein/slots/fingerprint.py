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


def build_candidate_fingerprint_list(descriptors: list) -> list[dict]:
    """Build the sorted candidate entry list used by compute_slot_analysis_input_fingerprint.

    Filters to editable descriptors, sorts by (y, x), assigns S1..Sn keys.
    Accepts NativeShapeDescriptor instances or any objects with the required attributes.

    This is the canonical implementation — used by both M5.2 analysis and M6 source-
    currentness checking to ensure fingerprints are computed identically.
    """
    editable = [d for d in descriptors if d.can_edit_text]
    editable_sorted = sorted(editable, key=lambda d: (d.y, d.x))
    pairs: list[tuple[str, dict]] = []
    for i, d in enumerate(editable_sorted):
        key = f"S{i + 1}"
        pairs.append((
            key,
            {
                "key": key,
                "shape_path": d.shape_path,
                "shape_type": d.shape_type,
                "x": d.x,
                "y": d.y,
                "width": d.width,
                "height": d.height,
                "can_edit_text": d.can_edit_text,
                "text": d.text,
            },
        ))
    # Sort by key lexicographically to match M5.2 service.py (sorted(candidates.items())).
    # Lexicographic order matters for slides with ≥10 candidates: S1, S10, S11, ..., S2, ...
    return [entry for _, entry in sorted(pairs, key=lambda p: p[0])]


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
