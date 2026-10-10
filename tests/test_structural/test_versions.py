"""Tests for M10 version constants."""

from slidestein.structural.versions import (
    STRUCTURAL_RECOVERY_POLICY_VERSION,
    STRUCTURAL_RECOVERY_PROMPT_VERSION,
    STRUCTURAL_RECOVERY_SCHEMA_VERSION,
)


def test_schema_version_string():
    assert STRUCTURAL_RECOVERY_SCHEMA_VERSION == "1.0"


def test_policy_version_string():
    assert STRUCTURAL_RECOVERY_POLICY_VERSION == "1.0"


def test_prompt_version_string():
    assert STRUCTURAL_RECOVERY_PROMPT_VERSION == "1.0"


def test_versions_are_strings():
    for v in (
        STRUCTURAL_RECOVERY_SCHEMA_VERSION,
        STRUCTURAL_RECOVERY_POLICY_VERSION,
        STRUCTURAL_RECOVERY_PROMPT_VERSION,
    ):
        assert isinstance(v, str)
