"""Tests for SlideVectorStore (LanceDB-backed).

Uses a real LanceDB instance in a tmp directory — no mocking of storage.
No network calls; LanceDB is fully local.
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


def _vec(val: float = 0.0, dim: int = 4) -> list[float]:
    return [val] * dim


def _record(
    slide_id: str = "slide-001",
    deck_id: str = "deck-001",
    slide_number: int = 1,
    job: str = "summarise",
    fingerprint: str = "fp-abc",
    is_active: bool = True,
) -> EmbeddingRecord:
    return EmbeddingRecord(
        slide_id=slide_id,
        deck_id=deck_id,
        slide_number=slide_number,
        embedding_version="1.0",
        embedding_provider="sap_ai_core",
        embedding_model="text-embedding-3-large",
        embedding_input_fingerprint=fingerprint,
        classification_version="2.0",
        retrieval_text="Slide function: content",
        slide_function="content",
        primary_communication_job=job,
        visual_archetype="structured_one_pager",
        density="high",
        description="A test slide.",
        is_active=is_active,
    )


@pytest.fixture
def store(tmp_path) -> SlideVectorStore:
    return SlideVectorStore(str(tmp_path / "lancedb"))


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


class TestEmptyStore:
    def test_table_does_not_exist_initially(self, store: SlideVectorStore) -> None:
        assert not store.table_exists()

    def test_dimension_none_before_insert(self, store: SlideVectorStore) -> None:
        assert store.dimension() is None

    def test_get_fingerprint_returns_none_for_unknown(self, store: SlideVectorStore) -> None:
        assert store.get_fingerprint("does-not-exist") is None

    def test_is_current_false_when_no_table(self, store: SlideVectorStore) -> None:
        assert not store.is_current("any", "fp")

    def test_count_active_current_zero_when_no_table(self, store: SlideVectorStore) -> None:
        assert store.count_active_current("1.0", "text-embedding-3-large") == 0

    def test_deactivate_noop_when_no_table(self, store: SlideVectorStore) -> None:
        store.deactivate_slides(["s1"])  # Must not raise

    def test_search_returns_empty_when_no_table(self, store: SlideVectorStore) -> None:
        assert store.search_cosine(_vec(), top_k=5) == []


# ---------------------------------------------------------------------------
# Insert + query
# ---------------------------------------------------------------------------


class TestInsert:
    def test_table_created_after_upsert(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec())
        assert store.table_exists()

    def test_dimension_set_after_insert(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec(dim=8))
        assert store.dimension() == 8

    def test_get_fingerprint_after_insert(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-xyz"), _vec())
        assert store.get_fingerprint("slide-001") == "fp-xyz"

    def test_is_current_true_for_matching_fp(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-abc"), _vec())
        assert store.is_current("slide-001", "fp-abc")

    def test_is_current_false_for_wrong_fp(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-abc"), _vec())
        assert not store.is_current("slide-001", "fp-other")

    def test_count_active_current(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="s1"), _vec())
        store.upsert(_record(slide_id="s2"), _vec())
        assert store.count_active_current("1.0", "text-embedding-3-large") == 2


# ---------------------------------------------------------------------------
# Upsert (idempotency / replace)
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_upsert_same_slide_replaces_fingerprint(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-v1"), _vec(0.1))
        store.upsert(_record(fingerprint="fp-v2"), _vec(0.2))
        assert store.get_fingerprint("slide-001") == "fp-v2"

    def test_upsert_same_slide_does_not_duplicate(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec())
        store.upsert(_record(), _vec())
        assert store.count_active_current("1.0", "text-embedding-3-large") == 1

    def test_upsert_batch_inserts_multiple(self, store: SlideVectorStore) -> None:
        records = [_record(slide_id=f"s{i}") for i in range(3)]
        vectors = [_vec(float(i)) for i in range(3)]
        store.upsert_batch(records, vectors)
        assert store.count_active_current("1.0", "text-embedding-3-large") == 3

    def test_upsert_batch_mismatched_length_raises(self, store: SlideVectorStore) -> None:
        with pytest.raises(ValueError, match="same length"):
            store.upsert_batch([_record()], [_vec(), _vec()])


# ---------------------------------------------------------------------------
# Deactivation
# ---------------------------------------------------------------------------


class TestDeactivation:
    def test_deactivate_reduces_active_count(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="s1"), _vec())
        store.upsert(_record(slide_id="s2"), _vec())
        store.deactivate_slides(["s1"])
        assert store.count_active_current("1.0", "text-embedding-3-large") == 1

    def test_deactivate_empty_list_noop(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec())
        store.deactivate_slides([])
        assert store.count_active_current("1.0", "text-embedding-3-large") == 1


# ---------------------------------------------------------------------------
# Dimension mismatch
# ---------------------------------------------------------------------------


class TestDimensionMismatch:
    def test_insert_wrong_dim_raises_after_table_created(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="s1"), _vec(dim=4))
        with pytest.raises(DimensionMismatchError):
            store.upsert(_record(slide_id="s2"), _vec(dim=8))

    def test_inconsistent_vectors_in_single_batch_raises(self, store: SlideVectorStore) -> None:
        with pytest.raises(DimensionMismatchError):
            store.upsert_batch(
                [_record(slide_id="s1"), _record(slide_id="s2")],
                [[1.0, 2.0, 3.0], [1.0, 2.0]],  # different dims
            )


# ---------------------------------------------------------------------------
# Null job roundtrip (empty string storage)
# ---------------------------------------------------------------------------


class TestNullJobRoundtrip:
    def test_empty_string_job_stored_and_searchable(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="nav-01", job=""), _vec(1.0))
        rows = store.search_cosine(_vec(1.0), top_k=5)
        assert rows, "Expected at least one result"
        match = next((r for r in rows if r["slide_id"] == "nav-01"), None)
        assert match is not None
        assert match["primary_communication_job"] == ""


# ---------------------------------------------------------------------------
# Cosine search
# ---------------------------------------------------------------------------


class TestCosineSearch:
    def test_search_returns_results(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec(1.0))
        rows = store.search_cosine(_vec(1.0), top_k=5)
        assert len(rows) >= 1

    def test_top_k_limits_results(self, store: SlideVectorStore) -> None:
        for i in range(5):
            store.upsert(_record(slide_id=f"s{i}"), _vec(float(i)))
        rows = store.search_cosine(_vec(2.0), top_k=2)
        assert len(rows) <= 2

    def test_inactive_not_returned(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="active", is_active=True), _vec(1.0))
        store.upsert(_record(slide_id="inactive", is_active=False), _vec(1.0))
        rows = store.search_cosine(_vec(1.0), top_k=10, active_only=True)
        ids = [r["slide_id"] for r in rows]
        assert "inactive" not in ids

    def test_inactive_returned_when_active_only_false(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="active", is_active=True), _vec(1.0))
        store.upsert(_record(slide_id="inactive", is_active=False), _vec(1.0))
        rows = store.search_cosine(_vec(1.0), top_k=10, active_only=False)
        ids = [r["slide_id"] for r in rows]
        assert "inactive" in ids

    def test_search_result_has_distance_key(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec(1.0))
        rows = store.search_cosine(_vec(1.0), top_k=1)
        assert "_distance" in rows[0]


# ---------------------------------------------------------------------------
# _distance explicit — regression tests for Fix 1
# ---------------------------------------------------------------------------


class TestDistanceExplicit:
    def test_distance_always_present_in_every_result(self, store: SlideVectorStore) -> None:
        for i in range(3):
            store.upsert(_record(slide_id=f"s{i}"), _vec(float(i + 1)))
        rows = store.search_cosine(_vec(1.0), top_k=3)
        assert all("_distance" in r for r in rows)

    def test_distance_is_nonzero_for_different_direction_vectors(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), [1.0, 0.0, 0.0, 0.0])
        rows = store.search_cosine([0.0, 1.0, 0.0, 0.0], top_k=1)
        # Orthogonal vectors → cosine distance = 1.0 (maximum)
        assert rows[0]["_distance"] > 0.5

    def test_distance_near_zero_for_identical_direction_vectors(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec(1.0, dim=4))
        rows = store.search_cosine(_vec(1.0, dim=4), top_k=1)
        assert rows[0]["_distance"] < 0.01

    def test_distance_value_not_silent_default(self, store: SlideVectorStore) -> None:
        """Prove _distance is the real cosine distance, not a 0.0 fallback."""
        store.upsert(_record(slide_id="s1"), [1.0, 0.0, 0.0, 0.0])
        store.upsert(_record(slide_id="s2"), [0.0, 1.0, 0.0, 0.0])
        rows = store.search_cosine([1.0, 0.0, 0.0, 0.0], top_k=2)
        distances = {r["slide_id"]: r["_distance"] for r in rows}
        # s1 should be much closer than s2
        assert distances["s1"] < distances["s2"]


# ---------------------------------------------------------------------------
# Reactivation / currentness regression tests — Fix 2
# ---------------------------------------------------------------------------


class TestReactivation:
    def test_is_current_false_for_inactive_matching_fingerprint(self, store: SlideVectorStore) -> None:
        """Inactive row with matching fingerprint must NOT be treated as current."""
        store.upsert(_record(fingerprint="fp-abc"), _vec())
        store.deactivate_slides(["slide-001"])
        assert not store.is_current("slide-001", "fp-abc")

    def test_is_current_true_after_upsert_reactivation(self, store: SlideVectorStore) -> None:
        """active → deactivate → upsert again → current."""
        store.upsert(_record(fingerprint="fp-abc"), _vec())
        store.deactivate_slides(["slide-001"])
        assert not store.is_current("slide-001", "fp-abc")
        store.upsert(_record(fingerprint="fp-abc", is_active=True), _vec())
        assert store.is_current("slide-001", "fp-abc")

    def test_reactivated_slide_appears_in_search(self, store: SlideVectorStore) -> None:
        """active → deactivate → upsert → searchable again."""
        store.upsert(_record(slide_id="target", is_active=True), _vec(1.0))
        store.deactivate_slides(["target"])
        ids = [r["slide_id"] for r in store.search_cosine(_vec(1.0), top_k=5, active_only=True)]
        assert "target" not in ids
        store.upsert(_record(slide_id="target", is_active=True), _vec(1.0))
        ids = [r["slide_id"] for r in store.search_cosine(_vec(1.0), top_k=5, active_only=True)]
        assert "target" in ids


# ---------------------------------------------------------------------------
# count_current_active — scenarios A–F (Fix 3)
# ---------------------------------------------------------------------------


class TestCountCurrentActive:
    def test_a_matching_fingerprint_counted(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-1"), _vec())
        assert store.count_current_active({"slide-001": "fp-1"}) == 1

    def test_b_different_fingerprint_not_counted(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-1"), _vec())
        assert store.count_current_active({"slide-001": "fp-different"}) == 0

    def test_c_and_d_model_or_provider_change_not_counted(self, store: SlideVectorStore) -> None:
        """Changed model or provider produces a different expected fingerprint → not counted."""
        store.upsert(_record(fingerprint="fp-old"), _vec())
        assert store.count_current_active({"slide-001": "fp-new-model"}) == 0

    def test_e_inactive_row_not_counted(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-1"), _vec())
        store.deactivate_slides(["slide-001"])
        assert store.count_current_active({"slide-001": "fp-1"}) == 0

    def test_f_reembedded_row_counted_again(self, store: SlideVectorStore) -> None:
        store.upsert(_record(fingerprint="fp-1"), _vec())
        store.deactivate_slides(["slide-001"])
        assert store.count_current_active({"slide-001": "fp-1"}) == 0
        store.upsert(_record(fingerprint="fp-1", is_active=True), _vec())
        assert store.count_current_active({"slide-001": "fp-1"}) == 1

    def test_empty_expected_returns_zero(self, store: SlideVectorStore) -> None:
        store.upsert(_record(), _vec())
        assert store.count_current_active({}) == 0

    def test_no_table_returns_zero(self, store: SlideVectorStore) -> None:
        assert store.count_current_active({"slide-001": "fp-1"}) == 0

    def test_partial_match_counts_only_matches(self, store: SlideVectorStore) -> None:
        store.upsert(_record(slide_id="s1", fingerprint="fp-1"), _vec())
        store.upsert(_record(slide_id="s2", fingerprint="fp-2"), _vec())
        result = store.count_current_active({
            "s1": "fp-1",      # matches
            "s2": "fp-wrong",  # wrong fingerprint
            "s3": "fp-3",      # not in store at all
        })
        assert result == 1
