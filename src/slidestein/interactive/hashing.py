"""Canonical SHA-256 state hash for SlideState."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slidestein.interactive.models import ShapeState


def compute_slide_state_hash(
    shapes: list[ShapeState],
    slide_width: int,
    slide_height: int,
) -> str:
    """Compute a deterministic SHA-256 hash over slide geometry and content.

    Excluded from hash (intentional, M11.1 Req 17):
      - captured_at, deck_id, slide_id, schema_version: metadata, not content
      - z_order: derived from shape iteration order; unreliable across group nesting
      - editable_text: derived flag (True iff shape has text_frame and is not a group)
      - parent_group_path: derivable from shape_path by string split
    Shapes sorted by shape_path (lexicographic) for stability.
    """
    sorted_shapes = sorted(shapes, key=lambda s: s.shape_path)

    shape_dicts = [
        {
            "shape_path": s.shape_path,
            "shape_id": s.shape_id,
            "name": s.name,
            "shape_type": s.shape_type,
            "text": s.text,
            "x": s.x,
            "y": s.y,
            "width": s.width,
            "height": s.height,
            "rotation": s.rotation,
            "formatting_fingerprint": s.formatting_fingerprint,
        }
        for s in sorted_shapes
    ]

    payload = {
        "slide_width": slide_width,
        "slide_height": slide_height,
        "shapes": shape_dicts,
    }

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
