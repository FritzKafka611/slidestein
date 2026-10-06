"""Slide library: SQLite for metadata, LanceDB for embedding vectors.

Dependency rule: imports only from slidestein.domain.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from slidestein.classification.versions import CLASSIFICATION_VERSION
from slidestein.domain.models import (
    ClassificationRecord,
    SlideBrief,
    SlideCandidate,
    SlideMetadata,
    SlideRecord,
    SlideSemanticProfile,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS slides (
    slide_id      TEXT PRIMARY KEY,
    template_path TEXT NOT NULL,
    archetype     TEXT NOT NULL,
    description   TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS slide_records (
    slide_id           TEXT PRIMARY KEY,
    deck_fingerprint   TEXT NOT NULL,
    source_deck_path   TEXT NOT NULL,
    slide_number       INTEGER NOT NULL,
    extracted_text     TEXT NOT NULL DEFAULT '',
    slide_width_emu    INTEGER NOT NULL DEFAULT 0,
    slide_height_emu   INTEGER NOT NULL DEFAULT 0,
    text_object_count  INTEGER NOT NULL DEFAULT 0,
    image_count        INTEGER NOT NULL DEFAULT 0,
    chart_count        INTEGER NOT NULL DEFAULT 0,
    table_count        INTEGER NOT NULL DEFAULT 0,
    shape_count        INTEGER NOT NULL DEFAULT 0,
    preview_path       TEXT,
    archetype          TEXT,
    communication_jobs TEXT,
    storyline_role     TEXT,
    description        TEXT,
    record_json        TEXT NOT NULL,
    indexed_at         TEXT DEFAULT (datetime('now')),
    UNIQUE(deck_fingerprint, slide_number)
);

CREATE TABLE IF NOT EXISTS decks (
    deck_id             TEXT PRIMARY KEY,
    current_fingerprint TEXT NOT NULL,
    current_path        TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS slide_classifications (
    id                     INTEGER PRIMARY KEY,
    slide_id               TEXT NOT NULL,
    classification_version TEXT NOT NULL,
    model                  TEXT NOT NULL,
    prompt_version         TEXT NOT NULL,
    input_fingerprint      TEXT NOT NULL,
    profile_json           TEXT NOT NULL,
    classified_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(slide_id, classification_version)
);
"""

# Columns to add to slide_records that may not exist in older databases.
_MIGRATION_COLS = [
    ("deck_id", "TEXT"),
    ("native_slide_id", "INTEGER"),
    ("content_fingerprint", "TEXT"),
    ("structure_fingerprint", "TEXT"),
    ("is_active", "INTEGER NOT NULL DEFAULT 1"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to slide_records if not already present."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(slide_records)")}
    for col, defn in _MIGRATION_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE slide_records ADD COLUMN {col} {defn}")
    conn.commit()


class SlideLibrary:
    """Manages slide template metadata, ingested slide records, and (future) semantic search."""

    def __init__(self, db_path: Path, lancedb_uri: str) -> None:
        self._db_path = db_path
        self._lancedb_uri = lancedb_uri
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create database schema and run column migrations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        _migrate(conn)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SlideLibrary:
        self.init()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Template slide write (generation pipeline)
    # ------------------------------------------------------------------

    def index_slide(self, metadata: SlideMetadata) -> None:
        """Add or replace a template slide entry."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO slides
                (slide_id, template_path, archetype, description, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                metadata.slide_id,
                str(metadata.template_path),
                metadata.archetype.value,
                metadata.description,
                metadata.model_dump_json(),
            ),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Template slide read
    # ------------------------------------------------------------------

    def count(self) -> int:
        row = self._get_conn().execute("SELECT COUNT(*) FROM slides").fetchone()
        return row[0]

    def get_by_id(self, slide_id: str) -> SlideMetadata | None:
        row = self._get_conn().execute(
            "SELECT metadata_json FROM slides WHERE slide_id = ?", (slide_id,)
        ).fetchone()
        if row is None:
            return None
        return SlideMetadata.model_validate_json(row[0])

    def list_all(self) -> list[SlideMetadata]:
        rows = self._get_conn().execute("SELECT metadata_json FROM slides").fetchall()
        return [SlideMetadata.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------
    # Ingestion record write
    # ------------------------------------------------------------------

    def upsert_record(self, record: SlideRecord) -> None:
        """Insert or replace an ingested slide record.

        Idempotent: re-indexing the same (deck_fingerprint, slide_number) pair
        updates the existing row in-place.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO slide_records (
                slide_id, deck_fingerprint, source_deck_path, slide_number,
                extracted_text, slide_width_emu, slide_height_emu,
                text_object_count, image_count, chart_count, table_count, shape_count,
                preview_path, archetype, communication_jobs, storyline_role,
                description, record_json,
                deck_id, native_slide_id, content_fingerprint, structure_fingerprint,
                is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.slide_id,
                record.deck_fingerprint,
                str(record.source_deck_path),
                record.slide_number,
                record.extracted_text,
                record.slide_width_emu,
                record.slide_height_emu,
                record.text_object_count,
                record.image_count,
                record.chart_count,
                record.table_count,
                record.shape_count,
                str(record.preview_path) if record.preview_path is not None else None,
                record.archetype.value if record.archetype is not None else None,
                json.dumps([j.value for j in record.communication_jobs])
                if record.communication_jobs is not None
                else None,
                record.storyline_role.value if record.storyline_role is not None else None,
                record.description,
                record.model_dump_json(),
                record.deck_id,
                record.native_slide_id,
                record.content_fingerprint,
                record.structure_fingerprint,
                1 if record.is_active else 0,
            ),
        )
        conn.commit()

    def mark_slides_inactive(
        self,
        deck_fingerprint: str | None = None,
        deck_id: str | None = None,
    ) -> None:
        """Set is_active=0 for all active slides matching the given deck.

        Requires at least one of deck_fingerprint or deck_id.
        """
        if deck_fingerprint is None and deck_id is None:
            raise ValueError("Provide deck_fingerprint or deck_id")
        conn = self._get_conn()
        if deck_fingerprint is not None:
            conn.execute(
                "UPDATE slide_records SET is_active = 0 WHERE deck_fingerprint = ? AND is_active = 1",
                (deck_fingerprint,),
            )
        else:
            conn.execute(
                "UPDATE slide_records SET is_active = 0 WHERE deck_id = ? AND is_active = 1",
                (deck_id,),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Ingestion record read
    # ------------------------------------------------------------------

    def get_record(self, slide_id: str) -> SlideRecord | None:
        row = self._get_conn().execute(
            "SELECT record_json FROM slide_records WHERE slide_id = ?", (slide_id,)
        ).fetchone()
        if row is None:
            return None
        return SlideRecord.model_validate_json(row[0])

    def get_slide(self, slide_id: str) -> SlideRecord | None:
        """Alias for get_record."""
        return self.get_record(slide_id)

    def get_record_by_deck_and_slide(
        self, deck_fingerprint: str, slide_number: int
    ) -> SlideRecord | None:
        """Fetch the active record for (deck_fingerprint, slide_number)."""
        row = self._get_conn().execute(
            "SELECT record_json FROM slide_records "
            "WHERE deck_fingerprint = ? AND slide_number = ? AND is_active = 1",
            (deck_fingerprint, slide_number),
        ).fetchone()
        if row is None:
            return None
        return SlideRecord.model_validate_json(row[0])

    def list_records(self, deck_fingerprint: str | None = None) -> list[SlideRecord]:
        if deck_fingerprint is not None:
            rows = self._get_conn().execute(
                "SELECT record_json FROM slide_records "
                "WHERE deck_fingerprint = ? ORDER BY slide_number",
                (deck_fingerprint,),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT record_json FROM slide_records "
                "ORDER BY deck_fingerprint, slide_number"
            ).fetchall()
        return [SlideRecord.model_validate_json(r[0]) for r in rows]

    def list_active_slides(self) -> list[SlideRecord]:
        """Return all active slide records ordered by path and slide number."""
        rows = self._get_conn().execute(
            "SELECT record_json FROM slide_records "
            "WHERE is_active = 1 "
            "ORDER BY source_deck_path, slide_number"
        ).fetchall()
        return [SlideRecord.model_validate_json(r[0]) for r in rows]

    def count_records(self) -> int:
        row = self._get_conn().execute("SELECT COUNT(*) FROM slide_records").fetchone()
        return row[0]

    def count_records_with_preview(self) -> int:
        row = self._get_conn().execute(
            "SELECT COUNT(*) FROM slide_records WHERE preview_path IS NOT NULL AND is_active = 1"
        ).fetchone()
        return row[0]

    def count_classified_records(self) -> int:
        """Return the count of current (non-stale) classifications for active slides."""
        return self.count_current_classifications(CLASSIFICATION_VERSION)

    def count_records_with_embeddings(self) -> int:
        return 0

    # ------------------------------------------------------------------
    # Deck lineage
    # ------------------------------------------------------------------

    def get_deck_by_path(self, path: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT deck_id, current_fingerprint, current_path FROM decks WHERE current_path = ?",
            (path,),
        ).fetchone()
        if row is None:
            return None
        return {"deck_id": row[0], "fingerprint": row[1], "path": row[2]}

    def get_deck_by_fingerprint(self, fingerprint: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT deck_id, current_fingerprint, current_path FROM decks WHERE current_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return {"deck_id": row[0], "fingerprint": row[1], "path": row[2]}

    def create_deck(self, deck_id: str, fingerprint: str, path: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO decks (deck_id, current_fingerprint, current_path) VALUES (?, ?, ?)",
            (deck_id, fingerprint, path),
        )
        conn.commit()

    def update_deck_fingerprint(self, deck_id: str, fingerprint: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE decks SET current_fingerprint = ?, updated_at = datetime('now') WHERE deck_id = ?",
            (fingerprint, deck_id),
        )
        conn.commit()

    def update_deck_path(self, deck_id: str, path: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE decks SET current_path = ?, updated_at = datetime('now') WHERE deck_id = ?",
            (path, deck_id),
        )
        conn.commit()

    def list_decks(self) -> list[dict]:
        """Return one summary row per indexed deck (by fingerprint)."""
        rows = self._get_conn().execute(
            """
            SELECT
                sr.deck_fingerprint,
                sr.source_deck_path,
                COUNT(*) AS slide_count,
                d.deck_id
            FROM slide_records sr
            LEFT JOIN decks d ON d.current_fingerprint = sr.deck_fingerprint
            WHERE sr.is_active = 1
            GROUP BY sr.deck_fingerprint
            ORDER BY sr.source_deck_path
            """
        ).fetchall()
        return [
            {
                "fingerprint": r[0],
                "path": r[1],
                "slide_count": r[2],
                "deck_id": r[3],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Classification persistence
    # ------------------------------------------------------------------

    def upsert_classification(
        self,
        slide_id: str,
        version: str,
        model: str,
        prompt_version: str,
        input_fingerprint: str,
        profile: SlideSemanticProfile,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO slide_classifications
                (slide_id, classification_version, model, prompt_version,
                 input_fingerprint, profile_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(slide_id, classification_version) DO UPDATE SET
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                input_fingerprint = excluded.input_fingerprint,
                profile_json = excluded.profile_json,
                classified_at = datetime('now')
            """,
            (
                slide_id,
                version,
                model,
                prompt_version,
                input_fingerprint,
                profile.model_dump_json(),
            ),
        )
        conn.commit()

    def get_classification(
        self, slide_id: str, version: str
    ) -> ClassificationRecord | None:
        row = self._get_conn().execute(
            """
            SELECT id, slide_id, classification_version, model, prompt_version,
                   input_fingerprint, profile_json, classified_at
            FROM slide_classifications
            WHERE slide_id = ? AND classification_version = ?
            """,
            (slide_id, version),
        ).fetchone()
        if row is None:
            return None
        return ClassificationRecord(
            id=row[0],
            slide_id=row[1],
            classification_version=row[2],
            model=row[3],
            prompt_version=row[4],
            input_fingerprint=row[5],
            profile=SlideSemanticProfile.model_validate_json(row[6]),
            classified_at=row[7] or "",
        )

    def classification_is_current(
        self, slide_id: str, version: str, current_input_fp: str
    ) -> bool:
        """Return True if a classification exists and its input_fingerprint matches."""
        row = self._get_conn().execute(
            "SELECT input_fingerprint FROM slide_classifications "
            "WHERE slide_id = ? AND classification_version = ?",
            (slide_id, version),
        ).fetchone()
        if row is None:
            return False
        return row[0] == current_input_fp

    def count_current_classifications(self, version: str) -> int:
        """Count active slides that have a current (non-stale) classification."""
        row = self._get_conn().execute(
            """
            SELECT COUNT(*)
            FROM slide_records sr
            JOIN slide_classifications sc
              ON sc.slide_id = sr.slide_id
             AND sc.classification_version = ?
            WHERE sr.is_active = 1
            """,
            (version,),
        ).fetchone()
        return row[0]

    def list_classifications(
        self,
        version: str | None = None,
        active_slides_only: bool = True,
    ) -> list[ClassificationRecord]:
        """Return all persisted classifications, optionally filtered."""
        if active_slides_only:
            join = "JOIN slide_records sr ON sr.slide_id = sc.slide_id AND sr.is_active = 1"
        else:
            join = ""

        version_clause = "WHERE sc.classification_version = ?" if version else ""
        params: list = [version] if version else []

        rows = self._get_conn().execute(
            f"""
            SELECT sc.id, sc.slide_id, sc.classification_version, sc.model,
                   sc.prompt_version, sc.input_fingerprint, sc.profile_json, sc.classified_at
            FROM slide_classifications sc
            {join}
            {version_clause}
            ORDER BY sc.slide_id, sc.classification_version
            """,
            params,
        ).fetchall()
        results = []
        for row in rows:
            results.append(
                ClassificationRecord(
                    id=row[0],
                    slide_id=row[1],
                    classification_version=row[2],
                    model=row[3],
                    prompt_version=row[4],
                    input_fingerprint=row[5],
                    profile=SlideSemanticProfile.model_validate_json(row[6]),
                    classified_at=row[7] or "",
                )
            )
        return results

    # ------------------------------------------------------------------
    # Search (generation pipeline — future milestone)
    # ------------------------------------------------------------------

    def search(self, brief: SlideBrief, top_k: int = 5) -> list[SlideCandidate]:
        """Return top-k candidates for a brief (not yet implemented)."""
        raise NotImplementedError(
            "Semantic search not yet implemented — index slides first, then implement LanceDB query"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn
