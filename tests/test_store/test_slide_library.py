"""Tests for SlideLibrary M3.4 features: migration, deck lineage, classification persistence."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from slidestein.classification.versions import CLASSIFICATION_VERSION
from slidestein.domain.models import (
    ClassificationRecord,
    CommunicationJob,
    DensityLevel,
    SlideRecord,
    SlideSemanticProfile,
    StorylineRole,
    VisualArchetype,
)
from slidestein.library.store import SlideLibrary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_library(tmp_path: Path) -> SlideLibrary:
    lib = SlideLibrary(tmp_path / "test.db", str(tmp_path / "lancedb"))
    lib.init()
    return lib


def _make_record(
    slide_id: str = "slide-001",
    deck_fingerprint: str = "abc123",
    slide_number: int = 1,
    deck_id: str | None = None,
    native_slide_id: int | None = None,
    content_fp: str | None = None,
    structure_fp: str | None = None,
    is_active: bool = True,
    source_deck_path: str = "/decks/foo.pptx",
) -> SlideRecord:
    return SlideRecord(
        slide_id=slide_id,
        deck_fingerprint=deck_fingerprint,
        source_deck_path=Path(source_deck_path),
        slide_number=slide_number,
        deck_id=deck_id,
        native_slide_id=native_slide_id,
        content_fingerprint=content_fp,
        structure_fingerprint=structure_fp,
        is_active=is_active,
    )


def _valid_profile(slide_id: str = "slide-001") -> SlideSemanticProfile:
    return SlideSemanticProfile(
        slide_id=slide_id,
        primary_communication_job=CommunicationJob.EXPLAIN,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.BAR_CHART,
        structural_pattern="Full-width bar chart.",
        density=DensityLevel.MEDIUM,
        description="A bar chart.",
    )


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestMigration:
    def test_migration_adds_new_columns_to_existing_db(self, tmp_path):
        """An old DB without M3.4 columns should gain them after init()."""
        db_path = tmp_path / "old.db"
        # Create a DB with the old schema (no is_active etc.)
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS slide_records (
                slide_id TEXT PRIMARY KEY,
                deck_fingerprint TEXT NOT NULL,
                source_deck_path TEXT NOT NULL,
                slide_number INTEGER NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                slide_width_emu INTEGER NOT NULL DEFAULT 0,
                slide_height_emu INTEGER NOT NULL DEFAULT 0,
                text_object_count INTEGER NOT NULL DEFAULT 0,
                image_count INTEGER NOT NULL DEFAULT 0,
                chart_count INTEGER NOT NULL DEFAULT 0,
                table_count INTEGER NOT NULL DEFAULT 0,
                shape_count INTEGER NOT NULL DEFAULT 0,
                preview_path TEXT,
                archetype TEXT,
                communication_jobs TEXT,
                storyline_role TEXT,
                description TEXT,
                record_json TEXT NOT NULL,
                indexed_at TEXT DEFAULT (datetime('now')),
                UNIQUE(deck_fingerprint, slide_number)
            );
        """)
        conn.close()

        lib = SlideLibrary(db_path, str(tmp_path / "lancedb"))
        lib.init()

        cols = {
            row[1]
            for row in lib._get_conn().execute("PRAGMA table_info(slide_records)")
        }
        lib.close()

        assert "deck_id" in cols
        assert "native_slide_id" in cols
        assert "content_fingerprint" in cols
        assert "structure_fingerprint" in cols
        assert "is_active" in cols

    def test_migration_is_idempotent(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.close()
        # Second init() must not raise
        lib2 = SlideLibrary(tmp_path / "test.db", str(tmp_path / "lancedb"))
        lib2.init()
        lib2.close()

    def test_existing_records_survive_migration(self, tmp_path):
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS slide_records (
                slide_id TEXT PRIMARY KEY,
                deck_fingerprint TEXT NOT NULL,
                source_deck_path TEXT NOT NULL,
                slide_number INTEGER NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                slide_width_emu INTEGER NOT NULL DEFAULT 0,
                slide_height_emu INTEGER NOT NULL DEFAULT 0,
                text_object_count INTEGER NOT NULL DEFAULT 0,
                image_count INTEGER NOT NULL DEFAULT 0,
                chart_count INTEGER NOT NULL DEFAULT 0,
                table_count INTEGER NOT NULL DEFAULT 0,
                shape_count INTEGER NOT NULL DEFAULT 0,
                preview_path TEXT,
                archetype TEXT,
                communication_jobs TEXT,
                storyline_role TEXT,
                description TEXT,
                record_json TEXT NOT NULL,
                indexed_at TEXT DEFAULT (datetime('now')),
                UNIQUE(deck_fingerprint, slide_number)
            );
        """)
        record = _make_record(slide_id="pre-migration-001")
        conn.execute(
            """
            INSERT INTO slide_records (
                slide_id, deck_fingerprint, source_deck_path, slide_number,
                record_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.slide_id,
                record.deck_fingerprint,
                str(record.source_deck_path),
                record.slide_number,
                record.model_dump_json(),
            ),
        )
        conn.commit()
        conn.close()

        lib = SlideLibrary(db_path, str(tmp_path / "lancedb"))
        lib.init()
        loaded = lib.get_record("pre-migration-001")
        lib.close()

        assert loaded is not None
        assert loaded.slide_id == "pre-migration-001"

    def test_new_columns_default_to_active(self, tmp_path):
        """Existing rows gain is_active=1 after migration."""
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS slide_records (
                slide_id TEXT PRIMARY KEY,
                deck_fingerprint TEXT NOT NULL,
                source_deck_path TEXT NOT NULL,
                slide_number INTEGER NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                slide_width_emu INTEGER NOT NULL DEFAULT 0,
                slide_height_emu INTEGER NOT NULL DEFAULT 0,
                text_object_count INTEGER NOT NULL DEFAULT 0,
                image_count INTEGER NOT NULL DEFAULT 0,
                chart_count INTEGER NOT NULL DEFAULT 0,
                table_count INTEGER NOT NULL DEFAULT 0,
                shape_count INTEGER NOT NULL DEFAULT 0,
                preview_path TEXT,
                archetype TEXT,
                communication_jobs TEXT,
                storyline_role TEXT,
                description TEXT,
                record_json TEXT NOT NULL,
                UNIQUE(deck_fingerprint, slide_number)
            );
        """)
        record = _make_record(slide_id="old-001")
        conn.execute(
            "INSERT INTO slide_records (slide_id, deck_fingerprint, source_deck_path, slide_number, record_json) VALUES (?, ?, ?, ?, ?)",
            (record.slide_id, record.deck_fingerprint, str(record.source_deck_path), record.slide_number, record.model_dump_json()),
        )
        conn.commit()
        conn.close()

        lib = SlideLibrary(db_path, str(tmp_path / "lancedb"))
        lib.init()
        row = lib._get_conn().execute(
            "SELECT is_active FROM slide_records WHERE slide_id = ?", ("old-001",)
        ).fetchone()
        lib.close()
        assert row[0] == 1


# ---------------------------------------------------------------------------
# Deck lineage tests
# ---------------------------------------------------------------------------


class TestDeckLineage:
    def test_new_deck_creates_deck_record(self, tmp_path):
        lib = _make_library(tmp_path)
        deck_id = str(uuid.uuid4())
        lib.create_deck(deck_id, "fp-abc", "/path/to/deck.pptx")
        found = lib.get_deck_by_path("/path/to/deck.pptx")
        lib.close()
        assert found is not None
        assert found["deck_id"] == deck_id

    def test_get_deck_by_fingerprint(self, tmp_path):
        lib = _make_library(tmp_path)
        deck_id = str(uuid.uuid4())
        lib.create_deck(deck_id, "unique-fp-xyz", "/some/path.pptx")
        found = lib.get_deck_by_fingerprint("unique-fp-xyz")
        lib.close()
        assert found is not None
        assert found["deck_id"] == deck_id

    def test_update_deck_fingerprint(self, tmp_path):
        lib = _make_library(tmp_path)
        deck_id = str(uuid.uuid4())
        lib.create_deck(deck_id, "old-fp", "/path.pptx")
        lib.update_deck_fingerprint(deck_id, "new-fp")
        found = lib.get_deck_by_fingerprint("new-fp")
        lib.close()
        assert found is not None
        assert found["deck_id"] == deck_id

    def test_update_deck_path(self, tmp_path):
        lib = _make_library(tmp_path)
        deck_id = str(uuid.uuid4())
        lib.create_deck(deck_id, "fp-abc", "/old/path.pptx")
        lib.update_deck_path(deck_id, "/new/path.pptx")
        found = lib.get_deck_by_path("/new/path.pptx")
        lib.close()
        assert found is not None
        assert found["deck_id"] == deck_id

    def test_unknown_path_and_fp_returns_none(self, tmp_path):
        lib = _make_library(tmp_path)
        assert lib.get_deck_by_path("/no/such/deck.pptx") is None
        assert lib.get_deck_by_fingerprint("nope") is None
        lib.close()


# ---------------------------------------------------------------------------
# is_active / mark_slides_inactive tests
# ---------------------------------------------------------------------------


class TestIsActive:
    def test_list_active_slides_excludes_inactive(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record("s1", slide_number=1, is_active=True))
        lib.upsert_record(_make_record("s2", slide_number=2, is_active=False))
        active = lib.list_active_slides()
        lib.close()
        ids = [r.slide_id for r in active]
        assert "s1" in ids
        assert "s2" not in ids

    def test_mark_slides_inactive_by_fingerprint(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record("s1", deck_fingerprint="fp-x", slide_number=1))
        lib.upsert_record(_make_record("s2", deck_fingerprint="fp-x", slide_number=2))
        lib.mark_slides_inactive(deck_fingerprint="fp-x")
        active = lib.list_active_slides()
        lib.close()
        assert len(active) == 0

    def test_reingest_marks_old_inactive_and_inserts_new(self, tmp_path):
        """Simulates re-indexing: mark inactive → insert new active row."""
        lib = _make_library(tmp_path)
        # Insert old-format record
        lib.upsert_record(_make_record("old-001", deck_fingerprint="fp-x", slide_number=1))
        lib.mark_slides_inactive(deck_fingerprint="fp-x")
        # Insert new-format record (same deck_fingerprint + slide_number → REPLACE)
        lib.upsert_record(_make_record("new-uuid5-001", deck_fingerprint="fp-x", slide_number=1, is_active=True))
        active = lib.list_active_slides()
        lib.close()
        assert len(active) == 1
        assert active[0].slide_id == "new-uuid5-001"

    def test_mark_inactive_requires_at_least_one_param(self, tmp_path):
        lib = _make_library(tmp_path)
        with pytest.raises(ValueError):
            lib.mark_slides_inactive()
        lib.close()

    def test_count_records_with_preview_excludes_inactive(self, tmp_path):
        lib = _make_library(tmp_path)
        r = _make_record("s1", slide_number=1)
        r = r.model_copy(update={"preview_path": Path("/fake/preview.png")})
        lib.upsert_record(r)
        lib.mark_slides_inactive(deck_fingerprint="abc123")
        lib.close()
        lib2 = SlideLibrary(tmp_path / "test.db", str(tmp_path / "lancedb"))
        lib2.init()
        count = lib2.count_records_with_preview()
        lib2.close()
        assert count == 0


# ---------------------------------------------------------------------------
# Classification persistence tests
# ---------------------------------------------------------------------------


class TestClassificationPersistence:
    def test_upsert_classification_roundtrip(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("slide-001")
        lib.upsert_classification(
            slide_id="slide-001",
            version="1.0",
            model="claude-test",
            prompt_version="1.0",
            input_fingerprint="fp-abc",
            profile=profile,
        )
        loaded = lib.get_classification("slide-001", "1.0")
        lib.close()

        assert loaded is not None
        assert loaded.slide_id == "slide-001"
        assert loaded.model == "claude-test"
        assert loaded.input_fingerprint == "fp-abc"
        assert loaded.profile.slide_id == "slide-001"

    def test_upsert_same_slide_version_replaces(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("slide-001")
        lib.upsert_classification("slide-001", "1.0", "model-a", "1.0", "fp-1", profile)
        lib.upsert_classification("slide-001", "1.0", "model-b", "1.0", "fp-2", profile)
        loaded = lib.get_classification("slide-001", "1.0")
        lib.close()

        assert loaded is not None
        assert loaded.model == "model-b"
        assert loaded.input_fingerprint == "fp-2"

    def test_get_nonexistent_returns_none(self, tmp_path):
        lib = _make_library(tmp_path)
        result = lib.get_classification("no-such-slide", "1.0")
        lib.close()
        assert result is None

    def test_is_current_true_for_matching_input_fp(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("s")
        lib.upsert_classification("s", "1.0", "model", "1.0", "fp-abc", profile)
        assert lib.classification_is_current("s", "1.0", "fp-abc") is True
        lib.close()

    def test_is_current_false_for_mismatched_input_fp(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("s")
        lib.upsert_classification("s", "1.0", "model", "1.0", "fp-abc", profile)
        assert lib.classification_is_current("s", "1.0", "fp-different") is False
        lib.close()

    def test_is_current_false_for_nonexistent(self, tmp_path):
        lib = _make_library(tmp_path)
        assert lib.classification_is_current("ghost", "1.0", "fp") is False
        lib.close()

    def test_count_current_classifications_only_counts_active_slides(self, tmp_path):
        from slidestein.identity.slide_identity import compute_input_fingerprint
        lib = _make_library(tmp_path)
        # Active record — correct input_fingerprint.
        lib.upsert_record(_make_record("s1", slide_number=1, is_active=True,
                                       content_fp="cfp", structure_fp="sfp"))
        input_fp1 = compute_input_fingerprint("s1", "cfp", "sfp", "1.0", "1.0")
        lib.upsert_classification("s1", "1.0", "model", "1.0", input_fp1, _valid_profile("s1"))
        # Inactive record with a correct classification.
        lib.upsert_record(_make_record("s2", slide_number=2, is_active=False,
                                       content_fp="cfp2", structure_fp="sfp2"))
        input_fp2 = compute_input_fingerprint("s2", "cfp2", "sfp2", "1.0", "1.0")
        lib.upsert_classification("s2", "1.0", "model", "1.0", input_fp2, _valid_profile("s2"))

        count = lib.count_current_classifications("1.0")
        lib.close()
        # Only s1 is active
        assert count == 1

    def test_list_classifications_active_only(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record("s1", slide_number=1, is_active=True))
        lib.upsert_record(_make_record("s2", slide_number=2, is_active=False))
        lib.upsert_classification("s1", "1.0", "m", "1.0", "fp", _valid_profile("s1"))
        lib.upsert_classification("s2", "1.0", "m", "1.0", "fp", _valid_profile("s2"))

        records = lib.list_classifications(active_slides_only=True)
        lib.close()
        ids = [r.slide_id for r in records]
        assert "s1" in ids
        assert "s2" not in ids

    def test_count_classified_records_delegates_to_current(self, tmp_path):
        from slidestein.identity.slide_identity import compute_input_fingerprint
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record("s1", slide_number=1, is_active=True,
                                       content_fp="cfp", structure_fp="sfp"))
        input_fp = compute_input_fingerprint("s1", "cfp", "sfp", CLASSIFICATION_VERSION, "1.0")
        lib.upsert_classification("s1", CLASSIFICATION_VERSION, "m", "1.0", input_fp, _valid_profile("s1"))
        count = lib.count_classified_records()
        lib.close()
        assert count == 1


# ---------------------------------------------------------------------------
# M3.4.1 Fix 2 — stale classification counting
# ---------------------------------------------------------------------------


class TestStaleClassificationCounting:
    """count_current_classifications must verify input_fingerprint, not just existence."""

    def _store_current_classification(
        self,
        lib,
        slide_id: str,
        content_fp: str,
        structure_fp: str,
        prompt_version: str = "1.0",
    ) -> str:
        """Upsert a classification whose input_fingerprint exactly matches the record."""
        from slidestein.identity.slide_identity import compute_input_fingerprint
        input_fp = compute_input_fingerprint(
            slide_id, content_fp, structure_fp, CLASSIFICATION_VERSION, prompt_version
        )
        lib.upsert_classification(
            slide_id, CLASSIFICATION_VERSION, "model", prompt_version, input_fp,
            _valid_profile(slide_id),
        )
        return input_fp

    def test_matching_fingerprint_counted(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-orig",
        ))
        self._store_current_classification(lib, "s1", "cfp-orig", "sfp-orig")
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 1
        lib.close()

    def test_stale_content_fingerprint_not_counted(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-orig",
        ))
        self._store_current_classification(lib, "s1", "cfp-orig", "sfp-orig")
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 1

        # Simulate a content edit: replace record with new content_fingerprint.
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-CHANGED", structure_fp="sfp-orig",
        ))
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 0
        lib.close()

    def test_stale_structure_fingerprint_not_counted(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-orig",
        ))
        self._store_current_classification(lib, "s1", "cfp-orig", "sfp-orig")

        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-CHANGED",
        ))
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 0
        lib.close()

    def test_inactive_slide_not_counted(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-orig",
        ))
        self._store_current_classification(lib, "s1", "cfp-orig", "sfp-orig")
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 1

        # Mark inactive.
        lib.mark_slides_inactive(deck_fingerprint="abc123")
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 0
        lib.close()

    def test_wrong_classification_version_not_counted(self, tmp_path):
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-orig",
        ))
        self._store_current_classification(lib, "s1", "cfp-orig", "sfp-orig")
        # Query for a different version — should find nothing.
        assert lib.count_current_classifications("2.0") == 0
        lib.close()

    def test_stale_prompt_version_not_counted(self, tmp_path):
        """A classification stored with prompt v1.0 is stale if prompt is now v2.0."""
        from slidestein.identity.slide_identity import compute_input_fingerprint
        lib = _make_library(tmp_path)
        lib.upsert_record(_make_record(
            "s1", slide_number=1, is_active=True,
            content_fp="cfp-orig", structure_fp="sfp-orig",
        ))
        # Store classification with prompt_version="1.0".
        self._store_current_classification(lib, "s1", "cfp-orig", "sfp-orig", prompt_version="1.0")
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 1

        # Now simulate a prompt bump: re-store with prompt_version="2.0",
        # which generates a DIFFERENT input_fingerprint.
        input_fp_v2 = compute_input_fingerprint(
            "s1", "cfp-orig", "sfp-orig", CLASSIFICATION_VERSION, "2.0"
        )
        lib.upsert_classification(
            "s1", CLASSIFICATION_VERSION, "model", "2.0", input_fp_v2,
            _valid_profile("s1"),
        )
        # The stored input_fp now uses prompt_version=2.0 → matches → still counted.
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 1

        # If we manually corrupt the stored fp, it should drop to 0.
        lib._get_conn().execute(
            "UPDATE slide_classifications SET input_fingerprint = 'corrupted-fp'",
        )
        lib._get_conn().commit()
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 0
        lib.close()

    def test_null_fingerprints_excluded_from_count(self, tmp_path):
        """Legacy records with NULL content/structure fingerprints are never counted."""
        lib = _make_library(tmp_path)
        # Record without content/structure fingerprints (legacy).
        lib.upsert_record(_make_record("s1", slide_number=1, is_active=True))
        lib.upsert_classification(
            "s1", CLASSIFICATION_VERSION, "model", "1.0", "any-fp",
            _valid_profile("s1"),
        )
        assert lib.count_current_classifications(CLASSIFICATION_VERSION) == 0
        lib.close()


# ---------------------------------------------------------------------------
# M3.4.1 Fix 6 — classification version coexistence
# ---------------------------------------------------------------------------


class TestClassificationVersionCoexistence:
    """UNIQUE(slide_id, classification_version) allows v1.0 and v2.0 to coexist."""

    def test_two_versions_coexist(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("slide-x")
        lib.upsert_classification("slide-x", "1.0", "model-a", "1.0", "fp-1", profile)
        lib.upsert_classification("slide-x", "2.0", "model-b", "1.0", "fp-2", profile)

        v1 = lib.get_classification("slide-x", "1.0")
        v2 = lib.get_classification("slide-x", "2.0")
        lib.close()

        assert v1 is not None and v1.model == "model-a"
        assert v2 is not None and v2.model == "model-b"
        assert v1.input_fingerprint != v2.input_fingerprint

    def test_same_version_upsert_replaces(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("slide-y")
        lib.upsert_classification("slide-y", "1.0", "first",  "1.0", "fp-a", profile)
        lib.upsert_classification("slide-y", "1.0", "second", "1.0", "fp-b", profile)

        loaded = lib.get_classification("slide-y", "1.0")
        lib.close()

        assert loaded is not None
        assert loaded.model == "second"
        assert loaded.input_fingerprint == "fp-b"

    def test_three_versions_all_distinct(self, tmp_path):
        lib = _make_library(tmp_path)
        profile = _valid_profile("slide-z")
        for v in ["1.0", "2.0", "3.0"]:
            lib.upsert_classification("slide-z", v, f"model-{v}", "1.0", f"fp-{v}", profile)

        rows = lib._get_conn().execute(
            "SELECT classification_version FROM slide_classifications WHERE slide_id = 'slide-z'"
        ).fetchall()
        lib.close()

        versions = {r[0] for r in rows}
        assert versions == {"1.0", "2.0", "3.0"}
