"""Tests for SAPAICoreEmbeddingProvider.

All tests mock the SAP SDK boundary — no real API calls.
The _call_api() method is patched directly for batching/logic tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from slidestein.retrieval.provider import EmbeddingBatch
from slidestein.retrieval.providers.sap_aicore import EmbeddingError, SAPAICoreEmbeddingProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(batch_size: int = 32) -> SAPAICoreEmbeddingProvider:
    mock_client = MagicMock()
    return SAPAICoreEmbeddingProvider(
        ai_core_client=mock_client,
        model="text-embedding-3-large",
        normalize=True,
        batch_size=batch_size,
    )


def _make_batch(count: int, dim: int = 4, model: str = "text-embedding-3-large") -> EmbeddingBatch:
    vectors = [[float(i)] * dim for i in range(count)]
    return EmbeddingBatch(vectors=vectors, model=model, dimension=dim)


# ---------------------------------------------------------------------------
# Empty / blank input guards
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_empty_texts_raises(self) -> None:
        p = _make_provider()
        with pytest.raises(EmbeddingError, match="non-empty"):
            p.embed_documents([])

    def test_blank_query_raises(self) -> None:
        p = _make_provider()
        with pytest.raises(EmbeddingError, match="non-blank"):
            p.embed_query("   ")


# ---------------------------------------------------------------------------
# embed_documents — passes "document" input type to _call_api
# ---------------------------------------------------------------------------


class TestEmbedDocumentsInputType:
    def test_calls_call_api_with_document_type(self) -> None:
        p = _make_provider()
        captured_types: list[str] = []

        def fake_call_api(texts, input_type):
            captured_types.append(input_type)
            return _make_batch(len(texts))

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            p.embed_documents(["doc one", "doc two"])

        assert captured_types == ["document"]

    def test_returns_embedding_batch(self) -> None:
        p = _make_provider()
        with patch.object(p, "_call_api", return_value=_make_batch(2)):
            result = p.embed_documents(["a", "b"])
        assert isinstance(result, EmbeddingBatch)
        assert len(result.vectors) == 2


# ---------------------------------------------------------------------------
# embed_query — passes "query" input type to _call_api
# ---------------------------------------------------------------------------


class TestEmbedQueryInputType:
    def test_calls_call_api_with_query_type(self) -> None:
        p = _make_provider()
        captured_types: list[str] = []

        def fake_call_api(texts, input_type):
            captured_types.append(input_type)
            return _make_batch(len(texts))

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            p.embed_query("my search query")

        assert captured_types == ["query"]

    def test_returns_single_vector(self) -> None:
        p = _make_provider()
        with patch.object(p, "_call_api", return_value=_make_batch(1, dim=4)):
            vec = p.embed_query("search")
        assert isinstance(vec, list)
        assert len(vec) == 4


# ---------------------------------------------------------------------------
# Batching logic
# ---------------------------------------------------------------------------


class TestBatching:
    def test_single_batch_when_texts_fit(self) -> None:
        p = _make_provider(batch_size=10)
        call_log: list[list[str]] = []

        def fake_call_api(texts, input_type):
            call_log.append(texts)
            return _make_batch(len(texts))

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            result = p.embed_documents(["t1", "t2", "t3"])

        assert len(call_log) == 1
        assert len(result.vectors) == 3

    def test_two_batches_when_exceeds_batch_size(self) -> None:
        p = _make_provider(batch_size=3)
        call_log: list[list[str]] = []

        def fake_call_api(texts, input_type):
            call_log.append(list(texts))
            return _make_batch(len(texts))

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            result = p.embed_documents(["t1", "t2", "t3", "t4", "t5"])

        assert len(call_log) == 2
        assert call_log[0] == ["t1", "t2", "t3"]
        assert call_log[1] == ["t4", "t5"]
        assert len(result.vectors) == 5

    def test_batch_order_preserved(self) -> None:
        """Vectors must come back in the same order as input texts."""
        p = _make_provider(batch_size=2)

        # Encode index into vector so we can verify order
        def fake_call_api(texts, input_type):
            vecs = [[float(int(t))] * 4 for t in texts]
            return EmbeddingBatch(vectors=vecs, model="m", dimension=4)

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            result = p.embed_documents(["0", "1", "2", "3"])

        assert result.vectors[0][0] == 0.0
        assert result.vectors[1][0] == 1.0
        assert result.vectors[2][0] == 2.0
        assert result.vectors[3][0] == 3.0


# ---------------------------------------------------------------------------
# Count mismatch
# ---------------------------------------------------------------------------


class TestCountMismatch:
    def test_count_mismatch_raises_embedding_error(self) -> None:
        p = _make_provider()

        def fake_call_api(texts, input_type):
            # Returns fewer vectors than requested
            return _make_batch(len(texts) - 1)

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            with pytest.raises(EmbeddingError, match="vectors"):
                p.embed_documents(["a", "b", "c"])


# ---------------------------------------------------------------------------
# Dimension mismatch across batches
# ---------------------------------------------------------------------------


class TestDimensionMismatch:
    def test_inconsistent_vector_dims_raises(self) -> None:
        p = _make_provider(batch_size=2)
        call_count = 0

        def fake_call_api(texts, input_type):
            nonlocal call_count
            dim = 4 if call_count == 0 else 8  # Second batch different dim
            call_count += 1
            return _make_batch(len(texts), dim=dim)

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            with pytest.raises(EmbeddingError, match="dimension"):
                p.embed_documents(["a", "b", "c"])


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_embedding_error_from_call_api_propagates(self) -> None:
        """EmbeddingError raised inside _call_api propagates from embed_documents."""
        p = _make_provider()

        def fake_call_api(texts, input_type):
            raise EmbeddingError("connection refused")

        with patch.object(p, "_call_api", side_effect=fake_call_api):
            with pytest.raises(EmbeddingError, match="connection refused"):
                p.embed_documents(["text"])

    def test_model_name_accessible(self) -> None:
        p = _make_provider()
        assert p.model == "text-embedding-3-large"
