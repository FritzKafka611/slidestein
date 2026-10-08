"""Tests for V1/V2 classification versioning and coexistence in the store.

Verifies:
- V1 and V2 can coexist for the same slide (different classification_version rows)
- V1 is retrievable by version "1.0"
- V2 is retrievable by version "2.0"
- status counts only the CURRENT version (V2 = 2.0)
- input_fingerprint differs between V1 and V2 (version in fingerprint)
- V1 JSON remains parseable via parse_semantic_profile_json
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from slidestein.classification.versions import CLASSIFICATION_VERSION, PROMPT_VERSION
from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideFunction,
    SlideSemanticProfile,
    SlideSemanticProfileV2,
    StorylineRole,
    VisualArchetype,
    parse_semantic_profile_json,
)
from slidestein.identity.slide_identity import compute_input_fingerprint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _v1_profile(slide_id: str) -> SlideSemanticProfile:
    return SlideSemanticProfile(
        slide_id=slide_id,
        schema_version="1.0",
        primary_communication_job=CommunicationJob.SUMMARISE,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.TEXT_HEAVY,
        structural_pattern="One-pager with labeled rows.",
        density=DensityLevel.HIGH,
        description="A workstream charter (V1).",
    )


def _v2_profile(slide_id: str) -> SlideSemanticProfileV2:
    return SlideSemanticProfileV2(
        slide_id=slide_id,
        slide_function=SlideFunction.CONTENT,
        primary_communication_job=CommunicationJob.SUMMARISE,
        storyline_roles=[StorylineRole.PLAN],
        visual_archetype=VisualArchetype.STRUCTURED_ONE_PAGER,
        structural_pattern="Five-section one-pager (V2).",
        density=DensityLevel.HIGH,
        description="A workstream charter (V2).",
    )


# ---------------------------------------------------------------------------
# 1. Version constants
# ---------------------------------------------------------------------------

class TestVersionConstants:
    def test_classification_version_is_2(self) -> None:
        assert CLASSIFICATION_VERSION == "2.0"

    def test_prompt_version_is_2(self) -> None:
        assert PROMPT_VERSION == "2.0"


# ---------------------------------------------------------------------------
# 2. V1/V2 coexistence in SQLite
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path):
    from slidestein.library.store import SlideLibrary

    lib = SlideLibrary(
        db_path=tmp_path / "test.db",
        lancedb_uri=str(tmp_path / "lance"),
    )
    lib.init()
    yield lib
    lib.close()


@pytest.fixture
def indexed_slide(db, tmp_path: Path):
    """Insert a minimal slide_record so classification can reference it."""
    from slidestein.domain.models import SlideRecord

    rec = SlideRecord(
        slide_id="coexist-slide-001",
        deck_fingerprint="aaa" * 10 + "aaaa",
        source_deck_path=tmp_path / "deck.pptx",
        slide_number=1,
        content_fingerprint="cf_" + "a" * 61,
        structure_fingerprint="sf_" + "b" * 61,
        is_active=True,
    )
    db.upsert_record(rec)
    return rec


class TestV1V2Coexistence:
    def test_v1_and_v2_stored_separately(self, db, indexed_slide) -> None:
        sid = indexed_slide.slide_id
        v1 = _v1_profile(sid)
        v2 = _v2_profile(sid)

        db.upsert_classification(sid, "1.0", "model-v1", "1.0", "fp1", v1)
        db.upsert_classification(sid, "2.0", "model-v2", "2.0", "fp2", v2)

        v1_rec = db.get_classification(sid, "1.0")
        v2_rec = db.get_classification(sid, "2.0")

        assert v1_rec is not None
        assert v2_rec is not None

    def test_v1_profile_is_parseable_after_v2_stored(self, db, indexed_slide) -> None:
        sid = indexed_slide.slide_id
        db.upsert_classification(sid, "1.0", "m", "1.0", "fp1", _v1_profile(sid))
        db.upsert_classification(sid, "2.0", "m", "2.0", "fp2", _v2_profile(sid))

        v1_rec = db.get_classification(sid, "1.0")
        assert isinstance(v1_rec.profile, SlideSemanticProfile)
        assert v1_rec.profile.schema_version == "1.0"

    def test_v2_profile_retrieved_as_v2_type(self, db, indexed_slide) -> None:
        sid = indexed_slide.slide_id
        db.upsert_classification(sid, "2.0", "m", "2.0", "fp2", _v2_profile(sid))

        v2_rec = db.get_classification(sid, "2.0")
        assert isinstance(v2_rec.profile, SlideSemanticProfileV2)
        assert v2_rec.profile.schema_version == "2.0"

    def test_v1_not_deleted_after_v2_added(self, db, indexed_slide) -> None:
        sid = indexed_slide.slide_id
        db.upsert_classification(sid, "1.0", "m", "1.0", "fp1", _v1_profile(sid))
        db.upsert_classification(sid, "2.0", "m", "2.0", "fp2", _v2_profile(sid))

        # Both still present
        conn = sqlite3.connect(str(db._db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM slide_classifications WHERE slide_id = ?", (sid,)
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_count_current_only_counts_v2(self, db, indexed_slide) -> None:
        sid = indexed_slide.slide_id
        rec = indexed_slide

        # Compute the real input fingerprint for V2
        fp_v2 = compute_input_fingerprint(
            sid, rec.content_fingerprint, rec.structure_fingerprint, "2.0", "2.0"
        )
        # Compute the real input fingerprint for V1
        fp_v1 = compute_input_fingerprint(
            sid, rec.content_fingerprint, rec.structure_fingerprint, "1.0", "1.0"
        )

        db.upsert_classification(sid, "1.0", "m", "1.0", fp_v1, _v1_profile(sid))
        db.upsert_classification(sid, "2.0", "m", "2.0", fp_v2, _v2_profile(sid))

        # The store uses CLASSIFICATION_VERSION = "2.0"
        count = db.count_current_classifications("2.0")
        assert count == 1

        count_v1 = db.count_current_classifications("1.0")
        assert count_v1 == 1  # V1 fingerprint also valid when stored correctly

    def test_input_fingerprint_differs_between_versions(self, indexed_slide) -> None:
        sid = indexed_slide.slide_id
        cfp = indexed_slide.content_fingerprint
        sfp = indexed_slide.structure_fingerprint

        fp_v1 = compute_input_fingerprint(sid, cfp, sfp, "1.0", "1.0")
        fp_v2 = compute_input_fingerprint(sid, cfp, sfp, "2.0", "2.0")
        assert fp_v1 != fp_v2


# ---------------------------------------------------------------------------
# 3. V1 JSON backward compat
# ---------------------------------------------------------------------------

class TestV1BackwardCompat:
    def test_v1_json_string_still_parses(self) -> None:
        v1_json = (
            '{"schema_version": "1.0", "slide_id": "x",'
            ' "primary_communication_job": "summarise",'
            ' "storyline_roles": ["context"],'
            ' "visual_archetype": "text_heavy",'
            ' "structural_pattern": "p",'
            ' "density": "high", "description": "d"}'
        )
        result = parse_semantic_profile_json(v1_json)
        assert isinstance(result, SlideSemanticProfile)
        assert result.primary_communication_job == CommunicationJob.SUMMARISE

    def test_v1_profile_survives_roundtrip_through_classification_record(self) -> None:
        from slidestein.domain.models import ClassificationRecord

        v1 = _v1_profile("slide-old")
        rec = ClassificationRecord(
            slide_id="slide-old",
            classification_version="1.0",
            model="old-model",
            prompt_version="1.0",
            input_fingerprint="fp-old",
            profile=v1.model_dump_json(),  # pass as JSON string
        )
        assert isinstance(rec.profile, SlideSemanticProfile)
        assert rec.profile.slide_id == "slide-old"
