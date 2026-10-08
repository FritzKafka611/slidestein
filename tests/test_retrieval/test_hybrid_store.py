"""Tests for SlideVectorStore enriched metadata: secondary_communication_jobs, storyline_roles.

Tests rebuild_with_enriched_metadata and search_cosine new fields.
"""

from __future__ import annotations

import pytest

from slidestein.retrieval.store import (
    DimensionMismatchError,
    EmbeddingRecord,
    SlideVectorStore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    slide_id: str = "s1",
    secondary_jobs: str = "show_timeline",
    roles: str = "context,plan",
    job: str = "summarise",
    func: str = "content",
    archetype: str = "structured_one_pager",
    density: str = "high",
    is_active: bool = True,
) -> EmbeddingRecord:
    return EmbeddingRecord(
        slide_id=slide_id,
        deck_id="deck-01",
        slide_number=1,
        embedding_version="1.0",
        embedding_provider="test",
        embedding_model="test-model",
        embedding_input_fingerprint=f"fp-{slide_id}",
        classification_version="2.0",
        retrieval_text=f"text for {slide_id}",
        slide_function=func,
        primary_communication_job=job,
        secondary_communication_jobs=secondary_jobs,
        storyline_roles=roles,
        visual_archetype=archetype,
        density=density,
        description=f"description for {slide_id}",
        is_active=is_active,
    )


def _store(tmp_path) -> SlideVectorStore:
    return SlideVectorStore(str(tmp_path / "lancedb"))


def _vec(dim: int = 4) -> list[float]:
    return [0.1] * dim


# ---------------------------------------------------------------------------
# EmbeddingRecord — new fields
# ---------------------------------------------------------------------------


class TestEmbeddingRecordNewFields:
    def test_record_has_secondary_jobs_field(self) -> None:
        rec = _make_record(secondary_jobs="explain,show_timeline")
        assert rec.secondary_communication_jobs == "explain,show_timeline"

    def test_record_has_storyline_roles_field(self) -> None:
        rec = _make_record(roles="context,plan,diagnosis")
        assert rec.storyline_roles == "context,plan,diagnosis"

    def test_empty_secondary_jobs(self) -> None:
        rec = _make_record(secondary_jobs="")
        assert rec.secondary_communication_jobs == ""

    def test_empty_roles_allowed(self) -> None:
        # Just confirms the dataclass accepts it
        rec = _make_record(roles="")
        assert rec.storyline_roles == ""


# ---------------------------------------------------------------------------
# search_cosine — new fields in returned dict
# ---------------------------------------------------------------------------


class TestSearchCosineNewFields:
    def test_search_returns_secondary_jobs(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec = _make_record(secondary_jobs="explain")
        store.upsert(rec, _vec())
        results = store.search_cosine(_vec(), top_k=1)
        assert "secondary_communication_jobs" in results[0]
        assert results[0]["secondary_communication_jobs"] == "explain"

    def test_search_returns_storyline_roles(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec = _make_record(roles="context,plan")
        store.upsert(rec, _vec())
        results = store.search_cosine(_vec(), top_k=1)
        assert "storyline_roles" in results[0]
        assert results[0]["storyline_roles"] == "context,plan"

    def test_search_returns_empty_secondary_jobs_for_empty(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec = _make_record(secondary_jobs="")
        store.upsert(rec, _vec())
        results = store.search_cosine(_vec(), top_k=1)
        assert results[0]["secondary_communication_jobs"] == ""


# ---------------------------------------------------------------------------
# rebuild_with_enriched_metadata
# ---------------------------------------------------------------------------


class TestRebuildWithEnrichedMetadata:
    def test_raises_if_table_does_not_exist(self, tmp_path) -> None:
        store = _store(tmp_path)
        with pytest.raises(RuntimeError, match="does not exist"):
            store.rebuild_with_enriched_metadata([], expected_dim=4)

    def test_raises_dimension_mismatch(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec = _make_record()
        store.upsert(rec, _vec(4))
        with pytest.raises(DimensionMismatchError):
            store.rebuild_with_enriched_metadata([rec], expected_dim=8)

    def test_returns_row_count(self, tmp_path) -> None:
        store = _store(tmp_path)
        recs = [_make_record(f"s{i}") for i in range(3)]
        vecs = [_vec() for _ in recs]
        store.upsert_batch(recs, vecs)

        enriched = [_make_record(f"s{i}", secondary_jobs="explain") for i in range(3)]
        n = store.rebuild_with_enriched_metadata(enriched, expected_dim=4)
        assert n == 3

    def test_enriched_metadata_visible_after_rebuild(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec = _make_record("s1", secondary_jobs="", roles="context")
        store.upsert(rec, _vec())

        enriched = _make_record("s1", secondary_jobs="show_timeline", roles="context,plan")
        n = store.rebuild_with_enriched_metadata([enriched], expected_dim=4)
        assert n == 1

        results = store.search_cosine(_vec(), top_k=1)
        assert results[0]["secondary_communication_jobs"] == "show_timeline"
        assert results[0]["storyline_roles"] == "context,plan"

    def test_vectors_preserved_after_rebuild(self, tmp_path) -> None:
        store = _store(tmp_path)
        vec = [0.1, 0.2, 0.3, 0.4]
        rec = _make_record("s1")
        store.upsert(rec, vec)

        # Rebuild with same record (vectors should be read from table, not changed)
        store.rebuild_with_enriched_metadata([rec], expected_dim=4)

        # Search with the same vector should still find s1 at top
        results = store.search_cosine(vec, top_k=1)
        assert results[0]["slide_id"] == "s1"

    def test_rows_not_in_enriched_preserved_with_empty_new_fields(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec1 = _make_record("s1", secondary_jobs="explain")
        rec2 = _make_record("s2", secondary_jobs="")
        store.upsert_batch([rec1, rec2], [_vec(), _vec()])

        # Rebuild only with enriched for s1; s2 gets kept with fallback empty string
        enriched_s1 = _make_record("s1", secondary_jobs="show_timeline")
        n = store.rebuild_with_enriched_metadata([enriched_s1], expected_dim=4)
        assert n == 2

        results = store.search_cosine(_vec(), top_k=5)
        by_id = {r["slide_id"]: r for r in results}
        assert by_id["s1"]["secondary_communication_jobs"] == "show_timeline"
        # s2 should still be present (may have empty secondary_jobs from original or fallback)
        assert "s2" in by_id

    def test_rebuild_is_idempotent(self, tmp_path) -> None:
        store = _store(tmp_path)
        rec = _make_record("s1", secondary_jobs="explain", roles="context")
        store.upsert(rec, _vec())

        enriched = _make_record("s1", secondary_jobs="explain,show_timeline", roles="context,plan")
        store.rebuild_with_enriched_metadata([enriched], expected_dim=4)
        store.rebuild_with_enriched_metadata([enriched], expected_dim=4)

        results = store.search_cosine(_vec(), top_k=1)
        assert results[0]["secondary_communication_jobs"] == "explain,show_timeline"
        assert results[0]["storyline_roles"] == "context,plan"


# ---------------------------------------------------------------------------
# Fingerprint preservation regression
# ---------------------------------------------------------------------------


class TestFingerprintPreservationAfterRebuild:
    """Verify that embedding identity fields survive rebuild_with_enriched_metadata."""

    def test_fingerprint_preserved_after_rebuild(self, tmp_path) -> None:
        store = _store(tmp_path)
        vec = [0.1, 0.2, 0.3, 0.4]
        rec = _make_record(
            "s1",
            secondary_jobs="",
            roles="context",
        )
        store.upsert(rec, vec)

        # Capture originals before rebuild
        before = store.search_cosine(vec, top_k=1)[0]

        enriched = _make_record("s1", secondary_jobs="show_timeline", roles="context,plan")
        store.rebuild_with_enriched_metadata([enriched], expected_dim=4)

        after = store.search_cosine(vec, top_k=1)[0]

        # Identity fields must be byte-identical
        assert after["embedding_input_fingerprint"] == before["embedding_input_fingerprint"]
        assert after["slide_id"] == before["slide_id"]
        assert after["embedding_version"] == before["embedding_version"]
        assert after["embedding_provider"] == before["embedding_provider"]
        assert after["embedding_model"] == before["embedding_model"]
        assert after["is_active"] == before["is_active"]

        # Vector dimension must be preserved
        assert len(after["vector"]) == len(before["vector"])


# ---------------------------------------------------------------------------
# Failure-path: restore on create failure
# ---------------------------------------------------------------------------


class TestRebuildRestoresOnCreateFailure:
    """Verify that original data is restored when create_table fails."""

    def test_rebuild_restores_original_on_create_failure(self, tmp_path, monkeypatch) -> None:
        store = _store(tmp_path)
        rec = _make_record("s1", secondary_jobs="explain", roles="context")
        vec = [0.1, 0.2, 0.3, 0.4]
        store.upsert(rec, vec)

        # Monkeypatch the underlying lancedb db to fail on the FIRST create_table call
        original_db = store._db  # access internal db
        call_count = {"n": 0}

        original_create = original_db.create_table

        def failing_create(name, data=None, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated create_table failure")
            return original_create(name, data=data, **kwargs)

        monkeypatch.setattr(original_db, "create_table", failing_create)

        enriched = _make_record("s1", secondary_jobs="show_timeline", roles="context,plan")
        with pytest.raises(RuntimeError, match="Migration failed"):
            store.rebuild_with_enriched_metadata([enriched], expected_dim=4)

        # Original data should still be searchable
        monkeypatch.undo()
        results = store.search_cosine(vec, top_k=1)
        assert len(results) == 1
        assert results[0]["slide_id"] == "s1"
