"""Tests for IngestionService.

All tests in this module use a mock adapter so they run without a rendering
backend installed.  The integration test (marked @pytest.mark.integration)
requires PowerPoint or LibreOffice and must be opted into explicitly.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slidestein.domain.models import SlideRecord
from slidestein.identity.slide_identity import compute_deck_fingerprint
from slidestein.ingestion.service import IngestionService
from slidestein.library.store import SlideLibrary
from slidestein.pptx.adapter import PPTMasterAdapter


# ---------------------------------------------------------------------------
# Helpers / shared infrastructure
# ---------------------------------------------------------------------------


class _NoPreviewAdapter(PPTMasterAdapter):
    """Adapter that skips rendering — used for tests that don't care about previews."""

    def introspect_template(self, template_path: Path) -> MagicMock:  # type: ignore[override]
        return MagicMock()

    def fill_and_export(self, template_path, slots, output_path):
        return output_path

    def render_preview(self, pptx_path, slide_number, output_path):
        raise NotImplementedError("rendering disabled in test adapter")


class _WritingAdapter(PPTMasterAdapter):
    """Adapter whose render_preview creates a minimal PNG-like stub file."""

    def introspect_template(self, template_path: Path) -> MagicMock:  # type: ignore[override]
        return MagicMock()

    def fill_and_export(self, template_path, slots, output_path):
        return output_path

    def render_preview(self, pptx_path, slide_number, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)  # minimal PNG header
        return output_path


def _make_service(
    settings,
    adapter: PPTMasterAdapter | None = None,
) -> tuple[SlideLibrary, IngestionService]:
    library = SlideLibrary(settings.db_path, settings.lancedb_uri)
    library.init()
    svc = IngestionService(
        library=library,
        adapter=adapter or _NoPreviewAdapter(),
        previews_dir=settings.previews_dir,
    )
    return library, svc


# ---------------------------------------------------------------------------
# Core ingestion behaviour
# ---------------------------------------------------------------------------


class TestIngestionService:
    def test_ingest_deck_creates_one_record_per_slide(
        self, three_slide_pptx, settings
    ):
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            assert len(records) == 3
            assert library.count_records() == 3
        finally:
            library.close()

    def test_slide_numbers_are_one_indexed(self, three_slide_pptx, settings):
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            slide_numbers = [r.slide_number for r in records]
            assert slide_numbers == [1, 2, 3]
        finally:
            library.close()

    def test_slide_ids_are_deterministic(self, three_slide_pptx, settings):
        """Same file ingested twice must produce identical slide IDs."""
        library, svc = _make_service(settings)
        first_run = svc.ingest_deck(three_slide_pptx, render_previews=False)
        second_run = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            assert [r.slide_id for r in first_run] == [r.slide_id for r in second_run]
        finally:
            library.close()

    def test_slide_id_format(self, three_slide_pptx, settings):
        """slide_id must be a valid UUID5 string (M3.4 stable identity)."""
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for record in records:
                # Must be a valid UUID
                parsed = uuid.UUID(record.slide_id)
                assert parsed.version == 5
        finally:
            library.close()

    def test_native_slide_id_is_populated(self, three_slide_pptx, settings):
        """native_slide_id must be a positive integer after M3.4."""
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for r in records:
                assert r.native_slide_id is not None
                assert r.native_slide_id > 0
        finally:
            library.close()

    def test_deck_id_is_populated(self, three_slide_pptx, settings):
        """deck_id must be a valid UUID4 after M3.4."""
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            assert records[0].deck_id is not None
            parsed = uuid.UUID(records[0].deck_id)
            assert parsed.version == 4
            # All slides in the same deck have the same deck_id
            assert len({r.deck_id for r in records}) == 1
        finally:
            library.close()

    def test_stable_slide_id_survives_reindex(self, three_slide_pptx, settings):
        """Re-indexing the same file must produce identical UUID5 slide IDs."""
        library, svc = _make_service(settings)
        first_run = svc.ingest_deck(three_slide_pptx, render_previews=False)
        second_run = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            first_ids = [r.slide_id for r in first_run]
            second_ids = [r.slide_id for r in second_run]
            assert first_ids == second_ids
        finally:
            library.close()

    def test_ingest_is_idempotent(self, three_slide_pptx, settings):
        """Indexing the same deck twice must not create duplicate records."""
        library, svc = _make_service(settings)
        svc.ingest_deck(three_slide_pptx, render_previews=False)
        svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            assert library.count_records() == 3
        finally:
            library.close()

    def test_metadata_persisted_correctly(self, three_slide_pptx, settings):
        """SlideRecord fields survive a round-trip through SQLite."""
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for original in records:
                loaded = library.get_record(original.slide_id)
                assert loaded is not None
                assert loaded.slide_id == original.slide_id
                assert loaded.deck_fingerprint == original.deck_fingerprint
                assert loaded.slide_number == original.slide_number
                assert loaded.source_deck_path == original.source_deck_path
                assert loaded.slide_width_emu > 0
                assert loaded.slide_height_emu > 0
        finally:
            library.close()

    def test_extracted_text_is_non_empty(self, three_slide_pptx, settings):
        """The fixture PPTX has text on every slide; extracted_text must reflect that."""
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for r in records:
                assert r.extracted_text.strip(), (
                    f"Slide {r.slide_number} has empty extracted_text"
                )
                assert f"Slide {r.slide_number}" in r.extracted_text
        finally:
            library.close()

    def test_shape_count_is_non_zero(self, three_slide_pptx, settings):
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for r in records:
                assert r.shape_count > 0, f"Slide {r.slide_number} reports zero shapes"
        finally:
            library.close()

    def test_consulting_semantics_are_null(self, three_slide_pptx, settings):
        """Archetype, communication_jobs, etc. must be null at ingestion time."""
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for r in records:
                assert r.archetype is None
                assert r.communication_jobs is None
                assert r.storyline_role is None
                assert r.description is None
        finally:
            library.close()

    def test_deck_fingerprint_is_sha256_hex(self, three_slide_pptx, settings):
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            fp = records[0].deck_fingerprint
            assert len(fp) == 64  # SHA-256 → 64 hex chars
            assert all(c in "0123456789abcdef" for c in fp)
        finally:
            library.close()

    def test_source_deck_path_is_absolute(self, three_slide_pptx, settings):
        library, svc = _make_service(settings)
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for r in records:
                assert r.source_deck_path.is_absolute()
        finally:
            library.close()

    def test_list_records_returns_all_slides(self, three_slide_pptx, settings):
        library, svc = _make_service(settings)
        svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            all_records = library.list_records()
            assert len(all_records) == 3
            slide_numbers = [r.slide_number for r in all_records]
            assert slide_numbers == sorted(slide_numbers)
        finally:
            library.close()

    def test_list_decks_returns_one_row_per_deck(self, three_slide_pptx, settings):
        library, svc = _make_service(settings)
        svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            decks = library.list_decks()
            assert len(decks) == 1
            assert decks[0]["slide_count"] == 3
        finally:
            library.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestIngestionErrors:
    def test_missing_pptx_raises_file_not_found(self, tmp_path, settings):
        library, svc = _make_service(settings)
        try:
            with pytest.raises(FileNotFoundError, match="PPTX file not found"):
                svc.ingest_deck(tmp_path / "nonexistent.pptx", render_previews=False)
        finally:
            library.close()

    def test_corrupt_pptx_raises_value_error(self, tmp_path, settings):
        bad = tmp_path / "bad.pptx"
        bad.write_bytes(b"this is not a zip file")
        library, svc = _make_service(settings)
        try:
            with pytest.raises(ValueError, match="Cannot open PPTX"):
                svc.ingest_deck(bad, render_previews=False)
        finally:
            library.close()

    def test_non_pptx_extension_raises_value_error(self, tmp_path, settings):
        fake = tmp_path / "deck.pdf"
        fake.write_bytes(b"%%PDF")
        library, svc = _make_service(settings)
        try:
            with pytest.raises(ValueError, match=r"Expected a \.pptx file"):
                svc.ingest_deck(fake, render_previews=False)
        finally:
            library.close()

    def test_adapter_failure_propagates(self, three_slide_pptx, settings):
        """Unexpected adapter errors must not be swallowed."""

        class _FailingAdapter(PPTMasterAdapter):
            def introspect_template(self, p):  # type: ignore[override]
                return MagicMock()

            def fill_and_export(self, p, s, o):
                return o

            def render_preview(self, p, n, o):
                raise OSError("simulated disk full")

        library, svc = _make_service(settings, adapter=_FailingAdapter())
        try:
            with pytest.raises(OSError, match="simulated disk full"):
                svc.ingest_deck(three_slide_pptx, render_previews=True)
        finally:
            library.close()


# ---------------------------------------------------------------------------
# Preview handling
# ---------------------------------------------------------------------------


class TestPreviewHandling:
    def test_preview_paths_are_set_when_rendering_enabled(
        self, three_slide_pptx, settings
    ):
        library, svc = _make_service(settings, adapter=_WritingAdapter())
        records = svc.ingest_deck(three_slide_pptx, render_previews=True)
        try:
            for r in records:
                assert r.preview_path is not None, (
                    f"Slide {r.slide_number} has no preview_path"
                )
                assert r.preview_path.exists()
        finally:
            library.close()

    def test_preview_paths_are_null_when_rendering_disabled(
        self, three_slide_pptx, settings
    ):
        library, svc = _make_service(settings, adapter=_WritingAdapter())
        records = svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            for r in records:
                assert r.preview_path is None
        finally:
            library.close()

    def test_preview_path_follows_naming_convention(
        self, three_slide_pptx, settings
    ):
        """preview_path = {previews_dir}/{fingerprint[:12]}/{slide_number:03d}.png"""
        library, svc = _make_service(settings, adapter=_WritingAdapter())
        records = svc.ingest_deck(three_slide_pptx, render_previews=True)
        try:
            fp = records[0].deck_fingerprint
            for r in records:
                expected = (
                    settings.previews_dir / fp[:12] / f"{r.slide_number:03d}.png"
                )
                assert r.preview_path == expected
        finally:
            library.close()

    def test_preview_paths_persisted_in_library(
        self, three_slide_pptx, settings
    ):
        library, svc = _make_service(settings, adapter=_WritingAdapter())
        records = svc.ingest_deck(three_slide_pptx, render_previews=True)
        try:
            for original in records:
                loaded = library.get_record(original.slide_id)
                assert loaded is not None
                assert loaded.preview_path == original.preview_path
        finally:
            library.close()

    def test_count_records_with_preview(self, three_slide_pptx, settings):
        library, svc = _make_service(settings, adapter=_WritingAdapter())
        svc.ingest_deck(three_slide_pptx, render_previews=True)
        try:
            assert library.count_records_with_preview() == 3
        finally:
            library.close()

    def test_count_previews_zero_when_rendering_disabled(
        self, three_slide_pptx, settings
    ):
        library, svc = _make_service(settings, adapter=_NoPreviewAdapter())
        svc.ingest_deck(three_slide_pptx, render_previews=False)
        try:
            assert library.count_records_with_preview() == 0
        finally:
            library.close()


# ---------------------------------------------------------------------------
# Integration (opt-in — requires PowerPoint or LibreOffice)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_render_preview_end_to_end(three_slide_pptx, settings):
    """Full ingestion with a real rendering backend."""
    from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

    library = SlideLibrary(settings.db_path, settings.lancedb_uri)
    library.init()
    svc = IngestionService(
        library=library,
        adapter=PythonPptxAdapter(),
        previews_dir=settings.previews_dir,
    )
    try:
        records = svc.ingest_deck(three_slide_pptx, render_previews=True)
        assert len(records) == 3
        for r in records:
            assert r.preview_path is not None
            assert r.preview_path.exists()
            assert r.preview_path.stat().st_size > 0
    finally:
        library.close()


# ---------------------------------------------------------------------------
# Helpers for PPTX manipulation (used by M3.4.1 regression tests)
# ---------------------------------------------------------------------------


def _create_n_slide_pptx(path: "Path", n: int) -> None:
    """Save a fresh PPTX with n slides to path."""
    from pptx import Presentation as _Prs
    prs = _Prs()
    layout = prs.slide_layouts[0]
    for i in range(1, n + 1):
        slide = prs.slides.add_slide(layout)
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text = f"Slide {i}"
            elif ph.placeholder_format.idx == 1:
                ph.text = f"Body {i}"
    prs.save(str(path))


def _remove_last_slide_in_place(pptx_path: "Path") -> None:
    """Remove the last slide from a PPTX ZIP in-place (lxml-based).

    Deletes the <p:sldId> entry from ppt/presentation.xml, removes its
    Relationship from ppt/_rels/presentation.xml.rels, and strips the
    slide XML + its rels sidecar from the archive.
    """
    from lxml import etree

    _NS_P  = "http://schemas.openxmlformats.org/presentationml/2006/main"
    _NS_R  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    _NS_RL = "http://schemas.openxmlformats.org/package/2006/relationships"

    with zipfile.ZipFile(pptx_path, "r") as z:
        entries = {name: z.read(name) for name in z.namelist()}

    prs_root  = etree.fromstring(entries["ppt/presentation.xml"])
    rels_root = etree.fromstring(entries["ppt/_rels/presentation.xml.rels"])

    sld_id_lst = prs_root.find(f"{{{_NS_P}}}sldIdLst")
    last = sld_id_lst[-1]
    r_id = last.get(f"{{{_NS_R}}}id")

    slide_target: str | None = None
    for rel in list(rels_root):
        if rel.get("Id") == r_id:
            slide_target = rel.get("Target")  # e.g. "slides/slide3.xml"
            rels_root.remove(rel)
            break

    sld_id_lst.remove(last)

    entries["ppt/presentation.xml"] = etree.tostring(
        prs_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    entries["ppt/_rels/presentation.xml.rels"] = etree.tostring(
        rels_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    if slide_target:
        slide_zip = f"ppt/{slide_target}"
        # slide_target is "slides/slideN.xml" — rels sidecar is slides/_rels/slideN.xml.rels
        fname = slide_target.rsplit("/", 1)[-1]
        rels_zip = f"ppt/slides/_rels/{fname}.rels"
        entries.pop(slide_zip, None)
        entries.pop(rels_zip, None)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    pptx_path.write_bytes(buf.getvalue())


def _reorder_first_slide_to_last(src_path: "Path", dest_path: "Path") -> None:
    """Copy src_path to dest_path with the first slide moved to the last position.

    Moves the <p:sldId> element at index 0 to the end of <p:sldIdLst>.
    The native_slide_id (id= attribute) is unchanged — only the list position
    (== slide_number) changes.  This is a direct proof that identity != ordinal.
    """
    from lxml import etree

    _NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"

    with zipfile.ZipFile(src_path, "r") as z:
        entries = {name: z.read(name) for name in z.namelist()}

    prs_root  = etree.fromstring(entries["ppt/presentation.xml"])
    sld_id_lst = prs_root.find(f"{{{_NS_P}}}sldIdLst")

    if len(sld_id_lst) > 1:
        first = sld_id_lst[0]
        sld_id_lst.remove(first)
        sld_id_lst.append(first)

    entries["ppt/presentation.xml"] = etree.tostring(
        prs_root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    dest_path.write_bytes(buf.getvalue())


# ---------------------------------------------------------------------------
# M3.4.1 Fix 1 regression — deleted-slide / reindex
# ---------------------------------------------------------------------------


class TestDeletedSlideRegression:
    """Verify that a slide removed between two index runs becomes inactive,
    while remaining slides keep their stable slide_ids and deck_id."""

    def test_removed_slide_becomes_inactive_on_reindex(self, tmp_path, settings):
        pptx_path = tmp_path / "deck.pptx"
        _create_n_slide_pptx(pptx_path, n=3)

        library, svc = _make_service(settings)

        # First ingest — 3 slides.
        records1 = svc.ingest_deck(pptx_path, render_previews=False)
        deck_id = records1[0].deck_id
        id_by_native = {r.native_slide_id: r.slide_id for r in records1}
        removed_native = records1[2].native_slide_id  # last slide's native ID
        removed_slide_id = records1[2].slide_id

        # Remove slide 3 from the PPTX at the same path.
        _remove_last_slide_in_place(pptx_path)

        # Re-ingest — should retire old slides and insert 2 fresh active ones.
        records2 = svc.ingest_deck(pptx_path, render_previews=False)

        try:
            # deck_id preserved (same path, different fingerprint → rule B).
            assert records2[0].deck_id == deck_id, "deck_id must survive edit"

            # Remaining slides keep their stable slide_ids.
            for r2 in records2:
                assert r2.slide_id == id_by_native[r2.native_slide_id], (
                    f"slide_id changed for native_slide_id={r2.native_slide_id}"
                )

            # Active count is 2.
            active = library.list_active_slides()
            assert len(active) == 2, f"expected 2 active, got {len(active)}"

            # Removed slide is still in the DB but marked inactive.
            removed = library.get_record(removed_slide_id)
            assert removed is not None, "removed slide must be retained historically"
            assert not removed.is_active, "removed slide must be inactive"
        finally:
            library.close()

    def test_deck_id_unchanged_after_content_edit(self, tmp_path, settings):
        """Editing file content preserves deck_id (lineage rule B)."""
        pptx_path = tmp_path / "deck.pptx"
        _create_n_slide_pptx(pptx_path, n=2)

        library, svc = _make_service(settings)
        records1 = svc.ingest_deck(pptx_path, render_previews=False)
        original_deck_id = records1[0].deck_id

        # Overwrite with different content (different fingerprint, same path).
        _create_n_slide_pptx(pptx_path, n=2)
        # Save a slightly different version by adding one more character.
        from pptx import Presentation as _Prs
        prs = _Prs(str(pptx_path))
        prs.slides[0].placeholders[0].text = "Modified Title"
        prs.save(str(pptx_path))

        records2 = svc.ingest_deck(pptx_path, render_previews=False)
        try:
            assert records2[0].deck_id == original_deck_id
        finally:
            library.close()


# ---------------------------------------------------------------------------
# M3.4.1 Fix 4 regression — slide reorder preserves identity
# ---------------------------------------------------------------------------


class TestReorderRegression:
    """Prove that slide identity != slide ordinal position.

    After moving slide A from position 1 to the last position within the SAME
    deck path (rule B: same path, different fingerprint → same deck_id):
      - native_slide_id unchanged
      - slide_id unchanged
      - slide_number changed
    """

    def test_slide_id_stable_after_reorder(self, tmp_path, settings):
        pptx_path = tmp_path / "deck.pptx"
        _create_n_slide_pptx(pptx_path, n=3)

        library, svc = _make_service(settings)

        # Ingest original.
        records_before = svc.ingest_deck(pptx_path, render_previews=False)
        first_before = records_before[0]

        # Reorder: move first slide to last, save BACK to the same path.
        # _reorder_first_slide_to_last reads all entries before writing, so
        # src == dest is safe.
        _reorder_first_slide_to_last(pptx_path, pptx_path)

        # Re-ingest the same path (now reordered).
        records_after = svc.ingest_deck(pptx_path, render_previews=False)

        try:
            first_native = first_before.native_slide_id
            moved = next(r for r in records_after if r.native_slide_id == first_native)

            assert moved.slide_id == first_before.slide_id, (
                "slide_id must be stable across reorder"
            )
            assert moved.slide_number != first_before.slide_number, (
                "slide_number must have changed after reorder"
            )
            assert moved.slide_number == len(records_after), (
                "moved slide must be last after reorder"
            )
        finally:
            library.close()

    def test_all_other_slide_ids_stable_after_reorder(self, tmp_path, settings):
        """Non-moved slides also keep their slide_ids after a reorder."""
        pptx_path = tmp_path / "deck.pptx"
        _create_n_slide_pptx(pptx_path, n=3)

        library, svc = _make_service(settings)
        records_before = svc.ingest_deck(pptx_path, render_previews=False)
        id_by_native   = {r.native_slide_id: r.slide_id for r in records_before}

        _reorder_first_slide_to_last(pptx_path, pptx_path)
        records_after = svc.ingest_deck(pptx_path, render_previews=False)

        try:
            for r in records_after:
                assert r.slide_id == id_by_native[r.native_slide_id], (
                    f"slide_id changed for native_slide_id={r.native_slide_id}"
                )
        finally:
            library.close()


# ---------------------------------------------------------------------------
# M3.4.1 Fix 5 regression — slide insertion preserves existing identities
# ---------------------------------------------------------------------------


class TestInsertionRegression:
    """Inserting a new slide into the same deck must not alter any pre-existing
    native_slide_ids or slide_ids."""

    def test_existing_ids_unchanged_after_insertion(self, tmp_path, settings):
        from pptx import Presentation as _Prs

        pptx_path = tmp_path / "deck.pptx"
        _create_n_slide_pptx(pptx_path, n=2)

        library, svc = _make_service(settings)
        records_before = svc.ingest_deck(pptx_path, render_previews=False)
        id_by_native   = {r.native_slide_id: r.slide_id for r in records_before}

        # Append a new slide and save BACK to the same path (rule B: same path,
        # new fingerprint → same deck_id).
        prs = _Prs(str(pptx_path))
        new_slide = prs.slides.add_slide(prs.slide_layouts[0])
        new_slide.placeholders[0].text = "Inserted Slide"
        prs.save(str(pptx_path))

        records_after = svc.ingest_deck(pptx_path, render_previews=False)

        try:
            assert len(records_after) == 3, "should have 3 slides after insertion"

            # Pre-existing slides keep their stable slide_ids.
            for r in records_after:
                if r.native_slide_id in id_by_native:
                    assert r.slide_id == id_by_native[r.native_slide_id], (
                        f"slide_id changed for pre-existing native_slide_id={r.native_slide_id}"
                    )

            # Inserted slide has a distinct native ID and slide_id.
            original_natives = set(id_by_native.keys())
            new_records = [r for r in records_after if r.native_slide_id not in original_natives]
            assert len(new_records) == 1, "exactly one new slide expected"
            new_r = new_records[0]
            assert new_r.slide_id not in id_by_native.values(), (
                "inserted slide must have a new slide_id"
            )
        finally:
            library.close()
