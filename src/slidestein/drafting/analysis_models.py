"""Compact LLM parse targets for M5.3 content drafting.

Claude returns only slot keys and text — application-owned metadata (slot_id,
shape_id, shape_path, geometry, capacity) is never in the model response.
extra="forbid" ensures the model cannot inject unexpected fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class SlotReplacement(BaseModel):
    """A single slot the model has drafted text for."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str   # K1..Kn
    text: str       # drafted content


class SlotContentGap(BaseModel):
    """A slot the model cannot draft without inventing unsupported facts."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str              # K1..Kn
    missing_information: str   # what factual input is required


class ContentDraftModelOutput(BaseModel):
    """Top-level LLM response model for content drafting.

    Validates that no slot_key appears more than once across the three
    categories and that no category contains internal duplicates.
    Completeness against supplied_keys is validated by the service AFTER
    parsing (service knows the supplied set; this model does not).
    """

    model_config = ConfigDict(extra="forbid")

    replacements: list[SlotReplacement] = []
    clear_slots: list[str] = []
    needs_input: list[SlotContentGap] = []
    open_questions: list[str] = []
    drafting_summary: str

    @model_validator(mode="after")
    def _no_duplicate_or_overlapping_slot_keys(self) -> "ContentDraftModelOutput":
        seen_rep: set[str] = set()
        for r in self.replacements:
            if r.slot_key in seen_rep:
                raise ValueError(
                    f"Duplicate slot_key in replacements: {r.slot_key!r}"
                )
            seen_rep.add(r.slot_key)

        seen_clear: set[str] = set()
        for k in self.clear_slots:
            if k in seen_clear:
                raise ValueError(
                    f"Duplicate slot_key in clear_slots: {k!r}"
                )
            seen_clear.add(k)

        seen_ni: set[str] = set()
        for n in self.needs_input:
            if n.slot_key in seen_ni:
                raise ValueError(
                    f"Duplicate slot_key in needs_input: {n.slot_key!r}"
                )
            seen_ni.add(n.slot_key)

        overlap = (seen_rep & seen_clear) | (seen_rep & seen_ni) | (seen_clear & seen_ni)
        if overlap:
            raise ValueError(
                f"Same slot key(s) appear in multiple categories: {sorted(overlap)}"
            )

        return self
