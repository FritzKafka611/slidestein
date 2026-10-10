"""Fresh-interpreter regression test for VisualQARequest forward references.

Verifies that VisualQARequest can be constructed in a clean Python process
without any caller-side model_rebuild() call.  Uses subprocess so no prior
import state from the test suite can accidentally resolve the annotations.
"""

from __future__ import annotations

import subprocess
import sys


_FRESH_PROCESS_SCRIPT = r"""
# Fresh Python process — no prior slidestein imports, no model_rebuild().
from slidestein.qa.models import VisualQARequest
from slidestein.drafting.models import SlideContentDraft, SlotDraftAction, SlotDraftAssignment
from slidestein.slots.models import TemplateSlotMap, TemplateSlot, SlotCapacity
from slidestein.slots.roles import SlotRole
from pathlib import Path

# Build minimal valid supporting objects
slot = TemplateSlot(
    slot_id="s1", shape_id=21, shape_path="21",
    slot_role=SlotRole.TITLE, semantic_label="Title",
    editable=True, confidence=0.9, current_text="",
    geometry={
        "x_ratio": 0.04, "y_ratio": 0.07,
        "width_ratio": 0.88, "height_ratio": 0.09,
        "x": 487807, "y": 480060,
        "width": 10731754, "height": 617220,
    },
    capacity=SlotCapacity(
        max_characters_estimate=100, max_lines_estimate=2,
        current_character_count=0, current_line_count=0,
        relative_capacity="medium",
    ),
)
slot_map = TemplateSlotMap(
    slide_id="s-001", deck_id="d-001", slide_number=2,
    slide_width=12195175, slide_height=6858000,
    slots=[slot], non_editable_elements=[], unsupported_elements=[],
    groups=[], analysis_summary="Test.", slot_analysis_input_fingerprint="fp",
)
assignment = SlotDraftAssignment(
    slot_id="s1", shape_id=21, shape_path="21",
    slot_role=SlotRole.TITLE, semantic_label="Title",
    action=SlotDraftAction.REPLACE, text="Test title.",
    capacity_characters=100, capacity_utilization=0.1, max_lines_estimate=2,
)
draft = SlideContentDraft(
    slide_id="s-001", deck_id="d-001", slide_number=2,
    brief_key_message="Test message.",
    assignments=[assignment],
    drafting_summary="Test.", is_complete=True,
)

# --- Direct constructor (no model_rebuild) ---
req = VisualQARequest(
    template_pptx=Path("t.pptx"),
    generated_pptx=Path("g.pptx"),
    draft=draft,
    slot_map=slot_map,
)
assert req.template_pptx == Path("t.pptx")
assert req.draft.slide_id == "s-001"
assert req.slot_map.slide_id == "s-001"

# --- model_validate (no model_rebuild) ---
req2 = VisualQARequest.model_validate({
    "template_pptx": "t2.pptx",
    "generated_pptx": "g2.pptx",
    "draft": draft.model_dump(),
    "slot_map": slot_map.model_dump(),
})
assert req2.template_pptx == Path("t2.pptx")

# --- Verify annotations are concrete types, not strings ---
import slidestein.drafting.models as dm
import slidestein.slots.models as sm
fields = VisualQARequest.model_fields
assert fields["draft"].annotation is dm.SlideContentDraft, (
    f"draft annotation should be SlideContentDraft, got {fields['draft'].annotation}"
)
assert fields["slot_map"].annotation is sm.TemplateSlotMap, (
    f"slot_map annotation should be TemplateSlotMap, got {fields['slot_map'].annotation}"
)

print("OK")
"""


def test_visual_qa_request_no_model_rebuild_needed():
    """VisualQARequest constructs in a fresh process without model_rebuild()."""
    result = subprocess.run(
        [sys.executable, "-c", _FRESH_PROCESS_SCRIPT],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Fresh-process VisualQARequest construction failed.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_visual_qa_request_field_annotations_are_concrete_types():
    """VisualQARequest fields have concrete types, not string forward references."""
    from slidestein.qa.models import VisualQARequest
    import slidestein.drafting.models as dm
    import slidestein.slots.models as sm

    fields = VisualQARequest.model_fields
    assert fields["draft"].annotation is dm.SlideContentDraft
    assert fields["slot_map"].annotation is sm.TemplateSlotMap
