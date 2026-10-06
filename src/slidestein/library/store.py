"""Slide library: SQLite for metadata, LanceDB for embedding vectors.

Dependency rule: imports only from slidestein.domain.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from slidestein.domain.models import SlideBrief, SlideCandidate, SlideMetadata

_SCHEMA = """
CREATE TABLE IF NOT EXISTS slides (
    slide_id      TEXT PRIMARY KEY,
    template_path TEXT NOT NULL,
    archetype     TEXT NOT NULL,
    description   TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);
"""


class SlideLibrary:
    """Manages slide template metadata and (future) semantic search."""

    def __init__(self, db_path: Path, lancedb_uri: str) -> None:
        self._db_path = db_path
        self._lancedb_uri = lancedb_uri
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create database schema if it does not exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._get_conn().executescript(_SCHEMA)

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
    # Write
    # ------------------------------------------------------------------

    def index_slide(self, metadata: SlideMetadata) -> None:
        """Add or replace a slide in the library."""
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
        # TODO: compute text embedding for description + tags and upsert into LanceDB

    # ------------------------------------------------------------------
    # Read
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
    # Search
    # ------------------------------------------------------------------

    def search(self, brief: SlideBrief, top_k: int = 5) -> list[SlideCandidate]:
        """Return top-k candidates for a brief.

        Scoring strategy (to be implemented):
          - similarity_score: cosine distance in LanceDB embedding space
          - job_fit_score: overlap between brief.communication_job and slide.communication_jobs
          - structural_capacity_score: len(content_slots) vs len(required_content_elements)
          - archetype_score: overlap between brief.preferred_visual_archetypes and slide.archetype
          - combined_score: weighted average of the above
        """
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
