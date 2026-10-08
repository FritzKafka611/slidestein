"""Tests for the embedding input fingerprint utility."""

from __future__ import annotations

import re

import pytest

from slidestein.retrieval.fingerprint import EmbeddingConfig, compute_embedding_fingerprint
from slidestein.retrieval.versions import EMBEDDING_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**kwargs) -> EmbeddingConfig:
    defaults = dict(
        version=EMBEDDING_VERSION,
        provider="sap_ai_core",
        model="text-embedding-3-large",
    )
    defaults.update(kwargs)
    return EmbeddingConfig(**defaults)


_TEXT = "Slide function: content\nCommunication job: summarise"


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestFingerprintFormat:
    def test_returns_64_char_hex_string(self) -> None:
        fp = compute_embedding_fingerprint(_TEXT, _cfg())
        assert isinstance(fp, str)
        assert len(fp) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", fp)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_fingerprint(self) -> None:
        cfg = _cfg()
        assert compute_embedding_fingerprint(_TEXT, cfg) == compute_embedding_fingerprint(_TEXT, cfg)

    def test_independent_calls_same_fingerprint(self) -> None:
        assert (
            compute_embedding_fingerprint(_TEXT, _cfg())
            == compute_embedding_fingerprint(_TEXT, _cfg())
        )


# ---------------------------------------------------------------------------
# Sensitivity — each change must produce a different fingerprint
# ---------------------------------------------------------------------------


class TestSensitivity:
    def test_changed_text_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg()) != compute_embedding_fingerprint(
            _TEXT + " extra", _cfg()
        )

    def test_changed_model_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(model="model-a")) != (
            compute_embedding_fingerprint(_TEXT, _cfg(model="model-b"))
        )

    def test_changed_version_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(version="1.0")) != (
            compute_embedding_fingerprint(_TEXT, _cfg(version="2.0"))
        )

    def test_changed_provider_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(provider="p1")) != (
            compute_embedding_fingerprint(_TEXT, _cfg(provider="p2"))
        )

    def test_changed_dimensions_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(dimensions=256)) != (
            compute_embedding_fingerprint(_TEXT, _cfg(dimensions=512))
        )

    def test_normalize_true_vs_false_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(normalize=True)) != (
            compute_embedding_fingerprint(_TEXT, _cfg(normalize=False))
        )

    def test_normalize_set_vs_unset_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(normalize=True)) != (
            compute_embedding_fingerprint(_TEXT, _cfg(normalize=None))
        )

    def test_dimensions_set_vs_unset_differs(self) -> None:
        assert compute_embedding_fingerprint(_TEXT, _cfg(dimensions=256)) != (
            compute_embedding_fingerprint(_TEXT, _cfg(dimensions=None))
        )


# ---------------------------------------------------------------------------
# EmbeddingConfig fingerprint parts
# ---------------------------------------------------------------------------


class TestEmbeddingConfigParts:
    def test_minimal_config_has_three_parts(self) -> None:
        cfg = EmbeddingConfig(version="1.0", provider="p", model="m")
        parts = cfg.to_fingerprint_parts()
        assert parts == ["1.0", "p", "m"]

    def test_dimensions_appended(self) -> None:
        cfg = EmbeddingConfig(version="1.0", provider="p", model="m", dimensions=256)
        parts = cfg.to_fingerprint_parts()
        assert "256" in parts

    def test_normalize_true_appended(self) -> None:
        cfg = EmbeddingConfig(version="1.0", provider="p", model="m", normalize=True)
        assert "normalize=true" in cfg.to_fingerprint_parts()

    def test_normalize_false_appended(self) -> None:
        cfg = EmbeddingConfig(version="1.0", provider="p", model="m", normalize=False)
        assert "normalize=false" in cfg.to_fingerprint_parts()

    def test_none_normalize_not_appended(self) -> None:
        cfg = EmbeddingConfig(version="1.0", provider="p", model="m", normalize=None)
        parts = cfg.to_fingerprint_parts()
        assert not any(p.startswith("normalize") for p in parts)

    def test_config_is_frozen(self) -> None:
        cfg = _cfg()
        with pytest.raises((AttributeError, TypeError)):
            cfg.model = "changed"  # type: ignore[misc]
