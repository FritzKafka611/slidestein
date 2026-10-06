"""Tests for slidestein.identity.slide_identity."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Pt

from slidestein.identity.slide_identity import (
    compute_content_fingerprint,
    compute_deck_fingerprint,
    compute_input_fingerprint,
    compute_structure_fingerprint,
    extract_slide_identities,
    make_stable_slide_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pptx(path: Path, n_slides: int = 3, add_text: bool = True) -> Path:
    prs = Presentation()
    layout = prs.slide_layouts[0]
    for i in range(1, n_slides + 1):
        slide = prs.slides.add_slide(layout)
        if add_text:
            for ph in slide.placeholders:
                if ph.placeholder_format.idx == 0:
                    ph.text = f"Slide {i} Title"
                elif ph.placeholder_format.idx == 1:
                    ph.text = f"Subtitle {i}"
    prs.save(str(path))
    return path


# ---------------------------------------------------------------------------
# extract_slide_identities
# ---------------------------------------------------------------------------


class TestExtractSlideIdentities:
    def test_count_matches_slide_count(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        assert len(ids) == 3

    def test_native_ids_are_positive_integers(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        for si in ids:
            assert isinstance(si.native_slide_id, int)
            assert si.native_slide_id > 0

    def test_native_ids_are_unique(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        native_ids = [si.native_slide_id for si in ids]
        assert len(native_ids) == len(set(native_ids))

    def test_slide_numbers_are_one_indexed(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        numbers = [si.slide_number for si in ids]
        assert numbers == [1, 2, 3]

    def test_slide_part_is_relative_path(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        for si in ids:
            assert si.slide_part.startswith("slides/")
            assert si.slide_part.endswith(".xml")

    def test_deterministic(self, three_slide_pptx):
        ids1 = extract_slide_identities(three_slide_pptx)
        ids2 = extract_slide_identities(three_slide_pptx)
        assert [(si.slide_number, si.native_slide_id) for si in ids1] == [
            (si.slide_number, si.native_slide_id) for si in ids2
        ]


class TestSlideIdStability:
    def test_stable_after_text_change(self, three_slide_pptx, tmp_path):
        """Native slide IDs survive a text-only edit."""
        ids_before = extract_slide_identities(three_slide_pptx)

        edited = tmp_path / "edited.pptx"
        shutil.copy(three_slide_pptx, edited)
        prs = Presentation(str(edited))
        for ph in prs.slides[0].placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text = "Completely Different Title"
        prs.save(str(edited))

        ids_after = extract_slide_identities(edited)
        # Same native IDs for each slide position
        assert [si.native_slide_id for si in ids_before] == [
            si.native_slide_id for si in ids_after
        ]

    def test_different_slides_have_different_native_ids(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        native_ids = {si.native_slide_id for si in ids}
        assert len(native_ids) == 3


# ---------------------------------------------------------------------------
# make_stable_slide_id
# ---------------------------------------------------------------------------


class TestMakeStableSlideId:
    def test_is_valid_uuid(self):
        sid = make_stable_slide_id("deck-abc", 256)
        parsed = uuid.UUID(sid)
        assert parsed.version == 5

    def test_deterministic_for_same_inputs(self):
        a = make_stable_slide_id("deck-xyz", 300)
        b = make_stable_slide_id("deck-xyz", 300)
        assert a == b

    def test_different_for_different_native_ids(self):
        a = make_stable_slide_id("same-deck", 100)
        b = make_stable_slide_id("same-deck", 200)
        assert a != b

    def test_different_for_different_deck_ids(self):
        a = make_stable_slide_id("deck-A", 100)
        b = make_stable_slide_id("deck-B", 100)
        assert a != b


# ---------------------------------------------------------------------------
# compute_content_fingerprint
# ---------------------------------------------------------------------------


class TestContentFingerprint:
    def test_stable_for_same_file(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        fp1 = compute_content_fingerprint(three_slide_pptx, ids[0].slide_part)
        fp2 = compute_content_fingerprint(three_slide_pptx, ids[0].slide_part)
        assert fp1 == fp2

    def test_different_slides_have_different_fingerprints(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        fps = [compute_content_fingerprint(three_slide_pptx, si.slide_part) for si in ids]
        assert len(fps) == len(set(fps))

    def test_changes_after_text_edit(self, three_slide_pptx, tmp_path):
        ids = extract_slide_identities(three_slide_pptx)
        fp_before = compute_content_fingerprint(three_slide_pptx, ids[0].slide_part)

        edited = tmp_path / "edited.pptx"
        shutil.copy(three_slide_pptx, edited)
        prs = Presentation(str(edited))
        for ph in prs.slides[0].placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text = "Changed Title XYZ"
        prs.save(str(edited))

        ids_after = extract_slide_identities(edited)
        fp_after = compute_content_fingerprint(edited, ids_after[0].slide_part)
        assert fp_before != fp_after

    def test_returns_64_char_hex(self, three_slide_pptx):
        ids = extract_slide_identities(three_slide_pptx)
        fp = compute_content_fingerprint(three_slide_pptx, ids[0].slide_part)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------------------
# compute_structure_fingerprint
# ---------------------------------------------------------------------------


class TestStructureFingerprint:
    def test_stable_for_same_file(self, three_slide_pptx):
        fp1 = compute_structure_fingerprint(three_slide_pptx, 1)
        fp2 = compute_structure_fingerprint(three_slide_pptx, 1)
        assert fp1 == fp2

    def test_unchanged_after_text_edit(self, three_slide_pptx, tmp_path):
        fp_before = compute_structure_fingerprint(three_slide_pptx, 1)

        edited = tmp_path / "edited.pptx"
        shutil.copy(three_slide_pptx, edited)
        prs = Presentation(str(edited))
        for ph in prs.slides[0].placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text = "New Text That Changes Content"
        prs.save(str(edited))

        fp_after = compute_structure_fingerprint(edited, 1)
        assert fp_before == fp_after

    def test_returns_64_char_hex(self, three_slide_pptx):
        fp = compute_structure_fingerprint(three_slide_pptx, 1)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------------------
# compute_deck_fingerprint
# ---------------------------------------------------------------------------


class TestDeckFingerprint:
    def test_returns_64_char_hex(self, three_slide_pptx):
        fp = compute_deck_fingerprint(three_slide_pptx)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_different_files_have_different_fingerprints(self, tmp_path):
        p1 = _make_pptx(tmp_path / "a.pptx", n_slides=1)
        p2 = _make_pptx(tmp_path / "b.pptx", n_slides=2)
        assert compute_deck_fingerprint(p1) != compute_deck_fingerprint(p2)

    def test_deterministic(self, three_slide_pptx):
        assert compute_deck_fingerprint(three_slide_pptx) == compute_deck_fingerprint(
            three_slide_pptx
        )


# ---------------------------------------------------------------------------
# compute_input_fingerprint
# ---------------------------------------------------------------------------


class TestInputFingerprint:
    def test_deterministic(self):
        fp1 = compute_input_fingerprint("slide-abc", "cfp", "sfp", "1.0", "1.0")
        fp2 = compute_input_fingerprint("slide-abc", "cfp", "sfp", "1.0", "1.0")
        assert fp1 == fp2

    def test_changes_with_content_fingerprint(self):
        a = compute_input_fingerprint("slide-abc", "cfp1", "sfp", "1.0", "1.0")
        b = compute_input_fingerprint("slide-abc", "cfp2", "sfp", "1.0", "1.0")
        assert a != b

    def test_changes_with_classification_version(self):
        a = compute_input_fingerprint("slide-abc", "cfp", "sfp", "1.0", "1.0")
        b = compute_input_fingerprint("slide-abc", "cfp", "sfp", "2.0", "1.0")
        assert a != b

    def test_returns_64_char_hex(self):
        fp = compute_input_fingerprint("slide", "c", "s", "1.0", "1.0")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)
