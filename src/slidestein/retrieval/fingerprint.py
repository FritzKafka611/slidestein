"""Deterministic embedding input fingerprint.

Captures: retrieval text + embedding version + provider + model + config.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from slidestein.retrieval.versions import EMBEDDING_VERSION


@dataclass(frozen=True)
class EmbeddingConfig:
    """All parameters that determine a unique embedding contract."""

    version: str = EMBEDDING_VERSION
    provider: str = ""
    model: str = ""
    dimensions: int | None = None
    normalize: bool | None = None

    def to_fingerprint_parts(self) -> list[str]:
        parts = [self.version, self.provider, self.model]
        if self.dimensions is not None:
            parts.append(str(self.dimensions))
        if self.normalize is not None:
            parts.append("normalize=true" if self.normalize else "normalize=false")
        return parts


def compute_embedding_fingerprint(retrieval_text: str, config: EmbeddingConfig) -> str:
    """Return a stable SHA-256 fingerprint for (text, embedding config).

    Deterministic: same inputs always produce the same fingerprint.
    Changed retrieval text, model, version, or config → different fingerprint.
    """
    parts = [retrieval_text] + config.to_fingerprint_parts()
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
