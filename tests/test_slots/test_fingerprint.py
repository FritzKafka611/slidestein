"""Tests for slot_id and fingerprint utilities."""

from __future__ import annotations

import pytest

from slidestein.slots.fingerprint import (
    compute_slot_analysis_input_fingerprint,
    compute_slot_id,
)


class TestComputeSlotId:
    def test_same_inputs_same_id(self):
        id1 = compute_slot_id("slide-abc", "7")
        id2 = compute_slot_id("slide-abc", "7")
        assert id1 == id2

    def test_different_shape_path_different_id(self):
        id1 = compute_slot_id("slide-abc", "7")
        id2 = compute_slot_id("slide-abc", "8")
        assert id1 != id2

    def test_different_slide_id_different_slot_id(self):
        id1 = compute_slot_id("slide-abc", "7")
        id2 = compute_slot_id("slide-xyz", "7")
        assert id1 != id2

    def test_returns_uuid_string(self):
        import uuid
        slot_id = compute_slot_id("slide-abc", "7")
        # Should be parseable as a UUID
        parsed = uuid.UUID(slot_id)
        assert parsed.version == 5

    def test_group_child_path_stable(self):
        id1 = compute_slot_id("slide-abc", "10/8")
        id2 = compute_slot_id("slide-abc", "10/8")
        assert id1 == id2

    def test_not_random_uuid4(self):
        # UUID5 is deterministic; calling twice gives the same result
        a = compute_slot_id("slide-x", "5")
        b = compute_slot_id("slide-x", "5")
        assert a == b
        assert a != compute_slot_id("slide-x", "6")


class TestComputeSlotAnalysisInputFingerprint:
    def _candidates(self):
        return [
            {"key": "S1", "shape_path": "7", "x": 100, "y": 200,
             "width": 5000, "height": 600, "shape_type": "AUTO_SHAPE",
             "can_edit_text": True, "text": "Title"},
            {"key": "S2", "shape_path": "8", "x": 100, "y": 900,
             "width": 5000, "height": 600, "shape_type": "AUTO_SHAPE",
             "can_edit_text": True, "text": "Body"},
        ]

    def test_same_inputs_same_fingerprint(self):
        c = self._candidates()
        fp1 = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "1.0")
        fp2 = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "1.0")
        assert fp1 == fp2

    def test_different_slide_id_different_fingerprint(self):
        c = self._candidates()
        fp1 = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "1.0")
        fp2 = compute_slot_analysis_input_fingerprint("slide-2", c, "1.0", "1.0")
        assert fp1 != fp2

    def test_different_candidates_different_fingerprint(self):
        c1 = self._candidates()
        c2 = [dict(c1[0], text="Modified Title"), c1[1]]
        fp1 = compute_slot_analysis_input_fingerprint("slide-1", c1, "1.0", "1.0")
        fp2 = compute_slot_analysis_input_fingerprint("slide-1", c2, "1.0", "1.0")
        assert fp1 != fp2

    def test_different_schema_version_different_fingerprint(self):
        c = self._candidates()
        fp1 = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "1.0")
        fp2 = compute_slot_analysis_input_fingerprint("slide-1", c, "2.0", "1.0")
        assert fp1 != fp2

    def test_different_prompt_version_different_fingerprint(self):
        c = self._candidates()
        fp1 = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "1.0")
        fp2 = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "2.0")
        assert fp1 != fp2

    def test_returns_64_char_hex_string(self):
        c = self._candidates()
        fp = compute_slot_analysis_input_fingerprint("slide-1", c, "1.0", "1.0")
        assert len(fp) == 64
        assert all(ch in "0123456789abcdef" for ch in fp)
