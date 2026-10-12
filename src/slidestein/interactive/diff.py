"""SlideStateDiffService — detect changes between two slide state snapshots."""

from __future__ import annotations

from slidestein.interactive.models import (
    ShapeDelta,
    ShapeState,
    SlideState,
    SlideStateDiff,
)
from slidestein.interactive.versions import INTERACTIVE_STATE_SCHEMA_VERSION

_GEOMETRY_FIELDS = {"x", "y", "width", "height", "rotation"}
_TRACKED_FIELDS = {"text", "x", "y", "width", "height", "rotation", "formatting_fingerprint"}


class SlideStateDiffService:
    """Computes field-level diffs between two SlideState snapshots."""

    def diff(self, base: SlideState, current: SlideState) -> SlideStateDiff:
        base_index = {s.shape_path: s for s in base.shapes}
        current_index = {s.shape_path: s for s in current.shapes}

        base_paths = set(base_index)
        current_paths = set(current_index)

        added_shapes: list[ShapeState] = [
            current_index[p] for p in sorted(current_paths - base_paths)
        ]
        deleted_shapes: list[ShapeState] = [
            base_index[p] for p in sorted(base_paths - current_paths)
        ]

        shape_deltas: list[ShapeDelta] = []
        for path in sorted(base_paths & current_paths):
            before = base_index[path]
            after = current_index[path]
            changed = _changed_fields(before, after)
            if changed:
                categories = _derive_categories(changed)
                shape_deltas.append(
                    ShapeDelta(
                        shape_path=path,
                        shape_id=before.shape_id,
                        changed_fields=sorted(changed),
                        delta_categories=categories,
                        before=before,
                        after=after,
                    )
                )

        has_changes = bool(shape_deltas or added_shapes or deleted_shapes)

        return SlideStateDiff(
            schema_version=INTERACTIVE_STATE_SCHEMA_VERSION,
            base_state_hash=base.state_hash,
            current_state_hash=current.state_hash,
            shape_deltas=shape_deltas,
            added_shapes=added_shapes,
            deleted_shapes=deleted_shapes,
            has_changes=has_changes,
        )


def _changed_fields(before: ShapeState, after: ShapeState) -> list[str]:
    changed = []
    for field in sorted(_TRACKED_FIELDS):
        if getattr(before, field) != getattr(after, field):
            changed.append(field)
    return changed


def _derive_categories(changed_fields: list[str]) -> list[str]:
    cats: list[str] = []
    if "text" in changed_fields:
        cats.append("text_changed")
    if _GEOMETRY_FIELDS & set(changed_fields):
        cats.append("geometry_changed")
    if "formatting_fingerprint" in changed_fields:
        cats.append("formatting_changed")
    return cats
