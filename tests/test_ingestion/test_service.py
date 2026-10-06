"""Tests for IngestionService.

All tests in this module use a mock adapter so they run without a rendering
backend installed.  The integration test (marked @pytest.mark.integration)
requires PowerPoint or LibreOffice and must be opted into explicitly.
"""

from __future__ import annotations

import uuid
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
