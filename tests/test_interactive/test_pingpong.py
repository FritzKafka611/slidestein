"""M11 ping-pong acceptance tests: human edits survive SlideStein patches.

Test sequences:
  V1 → human edits → V2 → SlideStein patch → V3   (single-cycle)
  V1 → human → V2 → patch → V3 → human → V4 → patch → V5  (two-cycle, Req 16)
  Real format edit: bold changed on human-owned shape (Req 14)
"""

from __future__ import annotations

from slidestein.interactive.adapters.python_pptx import PythonPptxPowerPointHostAdapter
from slidestein.interactive.diff import SlideStateDiffService
from slidestein.interactive.models import SlidePatchOperation, SlidePatchPlan
from slidestein.interactive.patch import SlidePatchService
from slidestein.interactive.session import SlideSessionService
from tests.test_interactive.conftest import (
    _GROUP_ID,
    _GROUP_X,
    _SHAPES,
    make_pingpong_pptx,
    simulate_human_format_edit,
    simulate_human_geometry_edit,
    simulate_human_group_move,
    simulate_human_text_edit,
    simulate_human_title_edit,
)

_ADAPTER = PythonPptxPowerPointHostAdapter()
_SESSION_SVC = SlideSessionService()
_PATCH_SVC = SlidePatchService()
_DIFF_SVC = SlideStateDiffService()


def test_pingpong_human_edits_survive_slidestein_patch(tmp_path):
    pptx_path, paths = make_pingpong_pptx(tmp_path)

    # ── V1: capture initial state ──────────────────────────────────────────
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)
    assert session.version == 0

    # ── Human edits ────────────────────────────────────────────────────────
    simulate_human_title_edit(pptx_path, "Human edited title")
    simulate_human_geometry_edit(pptx_path, shape_id=_SHAPES["left_content"][0], new_x=500000)
    simulate_human_text_edit(pptx_path, shape_id=_SHAPES["unrelated"][0], new_text="Human unrelated")
    simulate_human_group_move(pptx_path, group_id=_GROUP_ID, new_x=_GROUP_X + 600000)

    # ── V2: capture human-edited state ────────────────────────────────────
    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, diff_v1_v2 = _SESSION_SVC.advance_after_human_edit(session, v2)

    # Verify expected human edits were detected
    changed_categories = {d.shape_path: set(d.delta_categories) for d in diff_v1_v2.shape_deltas}

    assert "text_changed" in changed_categories.get(paths["title"], set()), \
        "Title text change not detected"
    assert "geometry_changed" in changed_categories.get(paths["left_content"], set()), \
        "Left-content geometry change not detected"
    assert "text_changed" in changed_categories.get(paths["unrelated"], set()), \
        "Unrelated text change not detected"
    assert "geometry_changed" in changed_categories.get(paths["grouped_child"], set()), \
        "Grouped child slide-space geometry change not detected after parent group move"

    # Verify protected fields accumulated
    assert f"{paths['title']}.text" in session.protected_fields
    assert f"{paths['left_content']}.x" in session.protected_fields
    assert f"{paths['unrelated']}.text" in session.protected_fields
    assert f"{paths['grouped_child']}.x" in session.protected_fields

    # ── SlideStein patches ONLY bullets 1-3 ───────────────────────────────
    bullet1_path = paths["bullet_1"]
    bullet2_path = paths["bullet_2"]
    bullet3_path = paths["bullet_3"]

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=bullet1_path,
                field="text",
                value="Updated bullet 1",
            ),
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_2"][0],
                shape_path=bullet2_path,
                field="text",
                value="Updated bullet 2",
            ),
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_3"][0],
                shape_path=bullet3_path,
                field="text",
                value="Updated bullet 3",
            ),
        ],
        explicitly_authorized_fields=[],
    )

    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "applied", f"Patch rejected: {result.rejection_reason}"
    assert result.verification_passed, f"Verification failed: {result.unexpected_changed_fields}"

    session = _SESSION_SVC.advance_after_slidestein_patch(session, patch, result)
    assert session.version == 1
    assert session.last_patch is patch

    # ── V3 assertions ─────────────────────────────────────────────────────
    v3 = result.after_state
    assert v3 is not None

    v3_map = {s.shape_path: s for s in v3.shapes}

    # Bullets updated
    assert v3_map[bullet1_path].text == "Updated bullet 1"
    assert v3_map[bullet2_path].text == "Updated bullet 2"
    assert v3_map[bullet3_path].text == "Updated bullet 3"

    # Human title preserved
    assert v3_map[paths["title"]].text == "Human edited title", "Human title edit was overwritten!"

    # Human geometry preserved
    assert v3_map[paths["left_content"]].x == 500000, "Human geometry edit was overwritten!"

    # Human unrelated text preserved
    assert v3_map[paths["unrelated"]].text == "Human unrelated", "Human unrelated text was overwritten!"

    # Human group move preserved (slide-space x of child)
    assert v3_map[paths["grouped_child"]].x == _GROUP_X + 600000, \
        "Human group move was overwritten!"

    # Diff V2→V3: only bullets should have changed
    diff_v2_v3 = _DIFF_SVC.diff(v2, v3)
    changed_paths = {d.shape_path for d in diff_v2_v3.shape_deltas}

    assert bullet1_path in changed_paths
    assert bullet2_path in changed_paths
    assert bullet3_path in changed_paths
    assert paths["title"] not in changed_paths, "V2→V3 diff shows title changed — human edit lost!"
    assert paths["left_content"] not in changed_paths, "V2→V3 diff shows geometry changed!"
    assert paths["unrelated"] not in changed_paths, "V2→V3 diff shows unrelated text changed!"
    assert paths["grouped_child"] not in changed_paths, "V2→V3 diff shows group child changed!"


def test_stale_base_state_rejected(tmp_path):
    pptx_path, _ = make_pingpong_pptx(tmp_path)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash="0" * 64,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=12, shape_path="12", field="text", value="x"
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "stale_base_state"


def test_protected_field_unauthorized_rejected(tmp_path):
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)

    simulate_human_title_edit(pptx_path, "Human title")
    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, _ = _SESSION_SVC.advance_after_human_edit(session, v2)

    assert f"{paths['title']}.text" in session.protected_fields

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["title"][0],
                shape_path=paths["title"],
                field="text",
                value="SlideStein overwrite",
            )
        ],
        explicitly_authorized_fields=[],
    )
    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "rejected"
    assert result.rejection_reason == "protected_user_edit"


def test_protected_field_authorized_applies(tmp_path):
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)

    simulate_human_title_edit(pptx_path, "Human title")
    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, _ = _SESSION_SVC.advance_after_human_edit(session, v2)

    title_field_key = f"{paths['title']}.text"
    assert title_field_key in session.protected_fields

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["title"][0],
                shape_path=paths["title"],
                field="text",
                value="Authorized override",
            )
        ],
        explicitly_authorized_fields=[title_field_key],
    )
    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "applied"
    v3_map = {s.shape_path: s for s in result.after_state.shapes}
    assert v3_map[paths["title"]].text == "Authorized override"


def test_missing_shape_rejected(tmp_path):
    pptx_path, _ = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text", shape_id=999, shape_path="999", field="text", value="x"
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "missing_target_shape"


def test_precondition_failed(tmp_path):
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    state = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=state.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                expected_before="THIS IS NOT THE ACTUAL TEXT",
                value="new",
            )
        ],
    )
    result = _ADAPTER.apply_patch(pptx_path, patch)
    assert result.status == "rejected"
    assert result.rejection_reason == "precondition_failed"


def test_format_preservation_non_target(tmp_path):
    """Non-target shape formatting_fingerprint must be identical in V3 vs V1."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)

    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v1.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                value="Changed",
            )
        ],
    )
    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "applied"

    v3_map = {s.shape_path: s for s in result.after_state.shapes}
    v1_map = {s.shape_path: s for s in v1.shapes}

    for name, (sid, *_) in _SHAPES.items():
        if name == "bullet_1":
            continue
        path = str(sid)
        if path in v1_map and path in v3_map:
            assert v1_map[path].formatting_fingerprint == v3_map[path].formatting_fingerprint, \
                f"Non-target shape {name} ({path}) fingerprint changed in V3"


def test_real_human_format_edit_protected_and_preserved(tmp_path):
    """Req 14: Real bold change → fingerprint protected → preserved after SlideStein patch."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)
    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)

    unrelated_path = paths["unrelated"]
    fp_v1 = next(s.formatting_fingerprint for s in v1.shapes if s.shape_path == unrelated_path)

    # Human sets bold on unrelated shape
    simulate_human_format_edit(pptx_path, shape_id=_SHAPES["unrelated"][0], bold=True)

    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    fp_v2 = next(s.formatting_fingerprint for s in v2.shapes if s.shape_path == unrelated_path)

    assert fp_v1 != fp_v2, "Bold change should change formatting_fingerprint"

    session, diff_v1_v2 = _SESSION_SVC.advance_after_human_edit(session, v2)

    # formatting_fingerprint for unrelated must be protected
    assert f"{unrelated_path}.formatting_fingerprint" in session.protected_fields

    # SlideStein patches bullet_1 only
    patch = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                value="Patched",
            )
        ],
    )
    result = _PATCH_SVC.validate_and_apply(session, patch, _ADAPTER, pptx_path)
    assert result.status == "applied"

    v3_map = {s.shape_path: s for s in result.after_state.shapes}
    fp_v3 = v3_map[unrelated_path].formatting_fingerprint

    assert fp_v3 == fp_v2, "Human bold change (fingerprint) was not preserved after SlideStein patch"
    assert v3_map[paths["bullet_1"]].text == "Patched"


def test_two_cycle_pingpong(tmp_path):
    """Req 16: V1→human(V2)→patch(V3)→human(V4)→patch(V5). Both patches and both human edits survive."""
    pptx_path, paths = make_pingpong_pptx(tmp_path)

    v1 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session = _SESSION_SVC.create_session(None, None, v1)

    # ── Cycle 1: human edits ───────────────────────────────────────────────
    simulate_human_title_edit(pptx_path, "Cycle1 title")
    simulate_human_geometry_edit(pptx_path, _SHAPES["left_content"][0], 600000)
    v2 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, _ = _SESSION_SVC.advance_after_human_edit(session, v2)

    # ── Cycle 1: SlideStein patches bullet_1 ──────────────────────────────
    patch1 = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v2.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_1"][0],
                shape_path=paths["bullet_1"],
                field="text",
                value="Cycle1 bullet1",
            )
        ],
    )
    result1 = _PATCH_SVC.validate_and_apply(session, patch1, _ADAPTER, pptx_path)
    assert result1.status == "applied", f"Cycle1 patch rejected: {result1.rejection_reason}"

    session = _SESSION_SVC.advance_after_slidestein_patch(session, patch1, result1)
    assert session.version == 1
    assert session.last_patch is patch1

    v3 = result1.after_state
    v3_map = {s.shape_path: s for s in v3.shapes}
    assert v3_map[paths["bullet_1"]].text == "Cycle1 bullet1"
    assert v3_map[paths["title"]].text == "Cycle1 title"
    assert v3_map[paths["left_content"]].x == 600000

    # ── Cycle 2: human edits unrelated text ───────────────────────────────
    simulate_human_text_edit(pptx_path, _SHAPES["unrelated"][0], "Cycle2 unrelated")
    v4 = _ADAPTER.capture_slide_state(pptx_path, slide_number=1)
    session, _ = _SESSION_SVC.advance_after_human_edit(session, v4)

    # ── Cycle 2: SlideStein patches bullet_2 ──────────────────────────────
    patch2 = SlidePatchPlan(
        slide_number=1,
        base_state_hash=v4.state_hash,
        operations=[
            SlidePatchOperation(
                operation="replace_text",
                shape_id=_SHAPES["bullet_2"][0],
                shape_path=paths["bullet_2"],
                field="text",
                value="Cycle2 bullet2",
            )
        ],
    )
    result2 = _PATCH_SVC.validate_and_apply(session, patch2, _ADAPTER, pptx_path)
    assert result2.status == "applied", f"Cycle2 patch rejected: {result2.rejection_reason}"

    session = _SESSION_SVC.advance_after_slidestein_patch(session, patch2, result2)
    assert session.version == 2
    assert session.last_patch is patch2

    # ── V5 final assertions ────────────────────────────────────────────────
    v5 = result2.after_state
    v5_map = {s.shape_path: s for s in v5.shapes}

    # Cycle 2 patch took effect
    assert v5_map[paths["bullet_2"]].text == "Cycle2 bullet2"

    # All prior work preserved
    assert v5_map[paths["bullet_1"]].text == "Cycle1 bullet1",   "Cycle1 SlideStein patch lost"
    assert v5_map[paths["title"]].text == "Cycle1 title",         "Cycle1 human title lost"
    assert v5_map[paths["left_content"]].x == 600000,             "Cycle1 human geometry lost"
    assert v5_map[paths["unrelated"]].text == "Cycle2 unrelated", "Cycle2 human text lost"

    # V4→V5 diff: only bullet_2 changed
    diff_v4_v5 = _DIFF_SVC.diff(v4, v5)
    changed_in_v5 = {d.shape_path for d in diff_v4_v5.shape_deltas}
    assert paths["bullet_2"] in changed_in_v5
    assert paths["bullet_1"] not in changed_in_v5, "Cycle1 bullet1 changed in V5"
    assert paths["title"] not in changed_in_v5,    "Cycle1 title changed in V5"
    assert paths["unrelated"] not in changed_in_v5, "Cycle2 unrelated changed in V5"
