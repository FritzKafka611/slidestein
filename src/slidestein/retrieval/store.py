"""LanceDB vector store for slide semantic embeddings.

Table name: slide_embeddings_v1

Schema (per row):
    slide_id                  TEXT  (primary key for upsert)
    deck_id                   TEXT
    slide_number              INT32
    embedding_version         TEXT
    embedding_provider        TEXT
    embedding_model           TEXT
    embedding_input_fingerprint TEXT
    classification_version    TEXT
    retrieval_text            TEXT
    slide_function            TEXT
    primary_communication_job TEXT  (empty string for null)
    visual_archetype          TEXT
    density                   TEXT
    description               TEXT
    is_active                 BOOL
    vector                    fixed_size_list<float32>[dim]

Dimension is inferred from the first batch inserted; subsequent inserts
validate dimension matches.

Cosine similarity is used for all vector search.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

_TABLE_NAME = "slide_embeddings_v1"


@dataclass
class EmbeddingRecord:
    """One row in the vector store (no vector field — metadata only)."""

    slide_id: str
    deck_id: str
    slide_number: int
    embedding_version: str
    embedding_provider: str
    embedding_model: str
    embedding_input_fingerprint: str
    classification_version: str
    retrieval_text: str
    slide_function: str
    primary_communication_job: str  # "" for null
    visual_archetype: str
    density: str
    description: str
    is_active: bool


@dataclass
class SearchResult:
    """Single result from a vector similarity search."""

    rank: int
    slide_id: str
    deck_id: str
    slide_number: int
    distance: float
    slide_function: str
    primary_communication_job: str | None  # None if "" in store
    visual_archetype: str
    density: str
    description: str
    retrieval_text: str


class DimensionMismatchError(Exception):
    """Raised when incoming vector dimension differs from table schema."""


class SlideVectorStore:
    """Manages LanceDB table for slide semantic embeddings.

    Parameters
    ----------
    lancedb_uri:
        Path / URI for the LanceDB database directory.
    """

    def __init__(self, lancedb_uri: str) -> None:
        self._uri = lancedb_uri
        self._db: Any = None
        self._table: Any = None
        self._dim: int | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _get_db(self) -> Any:
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self._uri)
        return self._db

    def _get_table(self) -> Any | None:
        """Return the table if it exists, else None."""
        db = self._get_db()
        raw = db.list_tables()
        # LanceDB ≥0.17 may return a ListTablesResponse with a .tables attribute.
        if hasattr(raw, "tables"):
            tables = raw.tables
        else:
            tables = raw
        if _TABLE_NAME in tables:
            if self._table is None:
                self._table = db.open_table(_TABLE_NAME)
            return self._table
        return None

    def table_exists(self) -> bool:
        return self._get_table() is not None

    def dimension(self) -> int | None:
        """Return the vector dimension if the table exists, else None."""
        tbl = self._get_table()
        if tbl is None:
            return None
        schema = tbl.schema
        for field in schema:
            if field.name == "vector":
                return field.type.list_size
        return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, record: EmbeddingRecord, vector: list[float]) -> None:
        """Insert or replace the embedding for *record.slide_id*."""
        self._upsert_batch([record], [vector])

    def upsert_batch(
        self, records: list[EmbeddingRecord], vectors: list[list[float]]
    ) -> None:
        """Batch upsert.  records[i] corresponds to vectors[i]."""
        if len(records) != len(vectors):
            raise ValueError(
                f"records ({len(records)}) and vectors ({len(vectors)}) must have the same length."
            )
        if not records:
            return
        self._upsert_batch(records, vectors)

    def _upsert_batch(
        self, records: list[EmbeddingRecord], vectors: list[list[float]]
    ) -> None:
        dim = len(vectors[0])

        # Validate all incoming vectors have the same dimension.
        for i, vec in enumerate(vectors):
            if len(vec) != dim:
                raise DimensionMismatchError(
                    f"Vector {i} has dimension {len(vec)}, expected {dim}."
                )

        db = self._get_db()
        existing_dim = self.dimension()

        if existing_dim is not None and existing_dim != dim:
            raise DimensionMismatchError(
                f"Table '{_TABLE_NAME}' has dimension {existing_dim} "
                f"but incoming vectors have dimension {dim}. "
                "Bump EMBEDDING_VERSION and recreate the table to resolve."
            )

        rows = [
            {
                "slide_id": r.slide_id,
                "deck_id": r.deck_id,
                "slide_number": r.slide_number,
                "embedding_version": r.embedding_version,
                "embedding_provider": r.embedding_provider,
                "embedding_model": r.embedding_model,
                "embedding_input_fingerprint": r.embedding_input_fingerprint,
                "classification_version": r.classification_version,
                "retrieval_text": r.retrieval_text,
                "slide_function": r.slide_function,
                "primary_communication_job": r.primary_communication_job,
                "visual_archetype": r.visual_archetype,
                "density": r.density,
                "description": r.description,
                "is_active": r.is_active,
                "vector": vec,
            }
            for r, vec in zip(records, vectors)
        ]

        if not self.table_exists():
            # Create table from first batch — schema inferred from data.
            self._table = db.create_table(_TABLE_NAME, data=rows)
        else:
            tbl = self._get_table()
            # merge_insert: update if slide_id matches, insert if not.
            (
                tbl.merge_insert("slide_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(rows)
            )

    # ------------------------------------------------------------------
    # Read / staleness
    # ------------------------------------------------------------------

    def get_fingerprint(self, slide_id: str) -> str | None:
        """Return stored embedding_input_fingerprint for slide_id, or None."""
        tbl = self._get_table()
        if tbl is None:
            return None
        rows = (
            tbl.search()
            .where(f"slide_id = '{_escape(slide_id)}'", prefilter=True)
            .select(["embedding_input_fingerprint"])
            .limit(1)
            .to_list()
        )
        if not rows:
            return None
        return rows[0]["embedding_input_fingerprint"]

    def is_current(self, slide_id: str, expected_fingerprint: str) -> bool:
        """True if there is an ACTIVE row for slide_id with a matching fingerprint.

        A matching fingerprint on an *inactive* row is NOT treated as current.
        This ensures that a slide that goes inactive and then becomes active again
        is correctly detected as needing a new embedding pass.
        """
        tbl = self._get_table()
        if tbl is None:
            return False
        rows = (
            tbl.search()
            .where(
                f"slide_id = '{_escape(slide_id)}'"
                f" AND embedding_input_fingerprint = '{_escape(expected_fingerprint)}'"
                f" AND is_active = true",
                prefilter=True,
            )
            .select(["slide_id"])
            .limit(1)
            .to_list()
        )
        return len(rows) > 0

    def count_active_current(
        self, embedding_version: str, embedding_model: str
    ) -> int:
        """Count active rows matching this embedding_version and model.

        Note: this does NOT verify that the stored fingerprint matches the
        current semantic profile.  Use count_current_active() for that.
        """
        tbl = self._get_table()
        if tbl is None:
            return 0
        try:
            rows = (
                tbl.search()
                .where(
                    f"is_active = true"
                    f" AND embedding_version = '{_escape(embedding_version)}'"
                    f" AND embedding_model = '{_escape(embedding_model)}'",
                    prefilter=True,
                )
                .select(["slide_id"])
                .limit(None)
                .to_list()
            )
            return len(rows)
        except Exception:
            return 0

    def count_current_active(self, expected: dict[str, str]) -> int:
        """Count slides whose active embedding matches the expected fingerprint.

        Parameters
        ----------
        expected:
            Mapping ``{slide_id: expected_embedding_input_fingerprint}``.
            Built by the caller from current V2 profiles + EmbeddingConfig.

        Returns
        -------
        int
            Number of entries in *expected* that have an active row in the
            vector store with a matching ``embedding_input_fingerprint``.
            Counts only active rows — inactive rows are always excluded.
        """
        if not expected:
            return 0
        tbl = self._get_table()
        if tbl is None:
            return 0
        try:
            rows = (
                tbl.search()
                .where("is_active = true", prefilter=True)
                .select(["slide_id", "embedding_input_fingerprint"])
                .limit(None)
                .to_list()
            )
            stored = {r["slide_id"]: r["embedding_input_fingerprint"] for r in rows}
            return sum(1 for sid, fp in expected.items() if stored.get(sid) == fp)
        except Exception:
            return 0

    def deactivate_slides(self, slide_ids: list[str]) -> None:
        """Mark rows for the given slide_ids as is_active=False."""
        if not slide_ids:
            return
        tbl = self._get_table()
        if tbl is None:
            return
        id_list = ", ".join(f"'{_escape(sid)}'" for sid in slide_ids)
        tbl.update(
            where=f"slide_id IN ({id_list})",
            values={"is_active": False},
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_cosine(
        self,
        query_vector: list[float],
        top_k: int,
        active_only: bool = True,
    ) -> list[dict]:
        """Return top_k rows by cosine distance (ascending = most similar first).

        Each result dict contains all non-vector columns plus '_distance'.
        """
        tbl = self._get_table()
        if tbl is None:
            return []

        q = tbl.search(query_vector).metric("cosine").limit(top_k)
        if active_only:
            q = q.where("is_active = true", prefilter=True)

        # Do NOT call .select() with a column list that omits `_distance`.
        # LanceDB currently autoprojections `_distance` into filtered selects but
        # will stop doing so in a future release (hence the deprecation warning).
        # Fetching all columns guarantees `_distance` is always present; we
        # project to a clean dict below.
        raw_rows = q.to_list()

        results: list[dict] = []
        for row in raw_rows:
            if "_distance" not in row:
                raise RuntimeError(
                    f"LanceDB vector search result is missing '_distance' for "
                    f"slide {row.get('slide_id', '?')}. Cannot score result."
                )
            results.append(
                {
                    "slide_id": row["slide_id"],
                    "deck_id": row.get("deck_id", ""),
                    "slide_number": row.get("slide_number", 0),
                    "slide_function": row.get("slide_function", ""),
                    "primary_communication_job": row.get("primary_communication_job", ""),
                    "visual_archetype": row.get("visual_archetype", ""),
                    "density": row.get("density", ""),
                    "description": row.get("description", ""),
                    "retrieval_text": row.get("retrieval_text", ""),
                    "embedding_version": row.get("embedding_version", ""),
                    "embedding_model": row.get("embedding_model", ""),
                    "embedding_input_fingerprint": row.get("embedding_input_fingerprint", ""),
                    "_distance": row["_distance"],
                }
            )
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape(s: str) -> str:
    """Minimal SQL-string escape for LanceDB WHERE clauses."""
    return s.replace("'", "''")
