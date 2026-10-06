"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from slidestein.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="sk-ant-test-key",
        slides_dir=tmp_path / "slides",
        output_dir=tmp_path / "output",
        db_path=tmp_path / "slidestein.db",
        lancedb_uri=str(tmp_path / "lancedb"),
    )
