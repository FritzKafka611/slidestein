"""Tests for M3.1 semantic domain contract.

Covers: expanded enums, DensityLevel, SlideSemanticProfile validators,
SlideClassificationInput construction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from slidestein.domain.models import (
    CommunicationJob,
    DensityLevel,
    SlideClassificationInput,
    SlideSemanticProfile,
    StorylineRole,
    VisualArchetype,
)


def _valid_profile(**overrides) -> SlideSemanticProfile:
    """Return a minimal valid SlideSemanticProfile with optional field overrides."""
    kwargs = dict(
        slide_id="abc123-001",
        primary_communication_job=CommunicationJob.EXPLAIN,
        storyline_roles=[StorylineRole.CONTEXT],
        visual_archetype=VisualArchetype.BAR_CHART,
        density=DensityLevel.MEDIUM,
        description="Shows quarterly revenue by region.",
        structural_pattern="Single bar chart with colour-coded series.",
    )
    kwargs.update(overrides)
    return SlideSemanticProfile(**kwargs)


# ---------------------------------------------------------------------------
# 1. Valid profile roundtrip
# ---------------------------------------------------------------------------


class TestSlideSemanticProfileValid:
    def test_valid_profile_roundtrip_json(self) -> None:
        profile = _valid_profile()
        restored = SlideSemanticProfile.model_validate_json(profile.model_dump_json())
        assert restored == profile

    def test_schema_version_default(self) -> None:
        profile = _valid_profile()
        assert profile.schema_version == "1.0"

    def test_secondary_jobs_and_multiple_roles(self) -> None:
        profile = _valid_profile(
            secondary_communication_jobs=[CommunicationJob.COMPARE],
            storyline_roles=[StorylineRole.CONTEXT, StorylineRole.INSIGHT],
            best_for=["executive audiences"],
            not_for=["detailed analysis"],
        )
        assert CommunicationJob.COMPARE in profile.secondary_communication_jobs
        assert len(profile.storyline_roles) == 2


# ---------------------------------------------------------------------------
# 2. slide_id validation
# ---------------------------------------------------------------------------


class TestSlideIdValidation:
    def test_blank_slide_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="slide_id"):
            _valid_profile(slide_id="")

    def test_whitespace_only_slide_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="slide_id"):
            _valid_profile(slide_id="   ")


# ---------------------------------------------------------------------------
# 3. storyline_roles validation
# ---------------------------------------------------------------------------


class TestStorylineRolesValidation:
    def test_empty_storyline_roles_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_profile(storyline_roles=[])

    def test_single_role_accepted(self) -> None:
        profile = _valid_profile(storyline_roles=[StorylineRole.EVIDENCE])
        assert profile.storyline_roles == [StorylineRole.EVIDENCE]


# ---------------------------------------------------------------------------
# 4. secondary_communication_jobs validation
# ---------------------------------------------------------------------------


class TestSecondaryJobsValidation:
    def test_secondary_duplicates_primary_raises(self) -> None:
        with pytest.raises(ValidationError, match="secondary_communication_jobs"):
            _valid_profile(
                primary_communication_job=CommunicationJob.EXPLAIN,
                secondary_communication_jobs=[CommunicationJob.EXPLAIN],
            )

    def test_secondary_self_duplicate_raises(self) -> None:
        with pytest.raises(ValidationError, match="secondary_communication_jobs"):
            _valid_profile(
                primary_communication_job=CommunicationJob.EXPLAIN,
                secondary_communication_jobs=[
                    CommunicationJob.COMPARE,
                    CommunicationJob.COMPARE,
                ],
            )

    def test_distinct_secondary_accepted(self) -> None:
        profile = _valid_profile(
            primary_communication_job=CommunicationJob.EXPLAIN,
            secondary_communication_jobs=[CommunicationJob.COMPARE, CommunicationJob.SUMMARISE],
        )
        assert len(profile.secondary_communication_jobs) == 2


# ---------------------------------------------------------------------------
# 5. description / structural_pattern whitespace validation
# ---------------------------------------------------------------------------


class TestTextFieldValidation:
    def test_whitespace_only_description_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-whitespace"):
            _valid_profile(description="   ")

    def test_whitespace_only_structural_pattern_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-whitespace"):
            _valid_profile(structural_pattern="\t\n")


# ---------------------------------------------------------------------------
# 6. best_for / not_for deduplication
# ---------------------------------------------------------------------------


class TestListDeduplication:
    def test_best_for_deduplicates(self) -> None:
        profile = _valid_profile(best_for=["exec", "exec", "board"])
        assert profile.best_for == ["exec", "board"]

    def test_not_for_deduplicates(self) -> None:
        profile = _valid_profile(not_for=["detail", "detail"])
        assert profile.not_for == ["detail"]


# ---------------------------------------------------------------------------
# 7. M3 enum values present
# ---------------------------------------------------------------------------


class TestM3EnumValues:
    def test_communication_job_m3_values(self) -> None:
        required = {
            "explain", "summarise", "compare", "diagnose", "prioritise",
            "recommend", "show_change", "show_process", "show_timeline",
            "show_hierarchy", "show_performance", "show_drivers",
            "show_options", "show_relationship",
        }
        values = {m.value for m in CommunicationJob}
        assert required <= values, f"Missing M3 CommunicationJob values: {required - values}"

    def test_storyline_role_m3_values(self) -> None:
        required = {
            "context", "diagnosis", "insight", "implication", "recommendation",
            "decision", "plan", "evidence", "summary",
        }
        values = {m.value for m in StorylineRole}
        assert required <= values, f"Missing M3 StorylineRole values: {required - values}"

    def test_visual_archetype_m3_values(self) -> None:
        required = {
            "title", "key_message", "text_heavy", "metric_row", "comparison",
            "before_after", "funnel", "pyramid", "matrix", "timeline", "roadmap",
            "process", "flow", "hierarchy", "org_chart", "portfolio",
            "status_dashboard", "bar_chart", "line_chart", "waterfall",
            "pie_chart", "table", "mixed_exhibit",
        }
        values = {m.value for m in VisualArchetype}
        assert required <= values, f"Missing M3 VisualArchetype values: {required - values}"

    def test_density_level_values(self) -> None:
        assert DensityLevel.LOW.value == "low"
        assert DensityLevel.MEDIUM.value == "medium"
        assert DensityLevel.HIGH.value == "high"
        assert len(list(DensityLevel)) == 3


# ---------------------------------------------------------------------------
# 8. Legacy enum values preserved
# ---------------------------------------------------------------------------


class TestLegacyEnumValues:
    def test_communication_job_legacy_values(self) -> None:
        assert CommunicationJob.CONVINCE.value == "convince"
        assert CommunicationJob.INFORM.value == "inform"
        assert CommunicationJob.SHOW_PROGRESS.value == "show_progress"
        assert CommunicationJob.PRIORITIZE.value == "prioritize"

    def test_storyline_role_legacy_values(self) -> None:
        assert StorylineRole.SITUATION.value == "situation"
        assert StorylineRole.COMPLICATION.value == "complication"
        assert StorylineRole.RESOLUTION.value == "resolution"
        assert StorylineRole.NEXT_STEPS.value == "next_steps"

    def test_visual_archetype_legacy_values(self) -> None:
        assert VisualArchetype.TWO_BY_TWO.value == "2x2_matrix"
        assert VisualArchetype.TITLE_ONLY.value == "title_only"
        assert VisualArchetype.BULLETS.value == "bullets"


# ---------------------------------------------------------------------------
# 9. SlideClassificationInput
# ---------------------------------------------------------------------------


class TestSlideClassificationInput:
    def test_minimal_construction(self) -> None:
        inp = SlideClassificationInput(
            slide_id="abc123-001",
            extracted_text="Revenue declined 15% QoQ.",
            structural_metadata={"shape_count": 3, "chart_count": 1},
        )
        assert inp.preview_path is None
        assert inp.structural_metadata["chart_count"] == 1

    def test_with_preview_path(self, tmp_path: Path) -> None:
        preview = tmp_path / "slide1.png"
        preview.write_bytes(b"PNG")
        inp = SlideClassificationInput(
            slide_id="abc123-001",
            extracted_text="",
            structural_metadata={},
            preview_path=preview,
        )
        assert inp.preview_path == preview

    def test_roundtrip_json(self) -> None:
        inp = SlideClassificationInput(
            slide_id="xyz-007",
            extracted_text="Cost reduction initiatives",
            structural_metadata={"text_object_count": 4},
        )
        restored = SlideClassificationInput.model_validate_json(inp.model_dump_json())
        assert restored.slide_id == inp.slide_id
        assert restored.structural_metadata == inp.structural_metadata


# ---------------------------------------------------------------------------
# 10. Invalid enum input rejected
# ---------------------------------------------------------------------------


class TestInvalidEnumInput:
    def test_invalid_communication_job_string_raises(self) -> None:
        with pytest.raises(ValidationError):
            SlideSemanticProfile(
                slide_id="abc-001",
                primary_communication_job="not_a_real_job",  # type: ignore[arg-type]
                storyline_roles=[StorylineRole.CONTEXT],
                visual_archetype=VisualArchetype.BAR_CHART,
                structural_pattern="Single bar chart.",
                density=DensityLevel.MEDIUM,
                description="Quarterly revenue.",
            )

    def test_invalid_visual_archetype_string_raises(self) -> None:
        with pytest.raises(ValidationError):
            SlideSemanticProfile(
                slide_id="abc-001",
                primary_communication_job=CommunicationJob.EXPLAIN,
                storyline_roles=[StorylineRole.CONTEXT],
                visual_archetype="not_a_real_archetype",  # type: ignore[arg-type]
                structural_pattern="Single bar chart.",
                density=DensityLevel.MEDIUM,
                description="Quarterly revenue.",
            )


# ---------------------------------------------------------------------------
# 11. Domain layer dependency isolation
# ---------------------------------------------------------------------------


class TestDomainLayerIsolation:
    def test_models_module_has_no_forbidden_imports(self) -> None:
        import ast
        import importlib.util

        spec = importlib.util.find_spec("slidestein.domain.models")
        assert spec is not None and spec.origin is not None
        source = Path(spec.origin).read_text(encoding="utf-8")

        tree = ast.parse(source)
        imported_tops: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_tops.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_tops.add(node.module.split(".")[0])

        forbidden = {"anthropic", "comtypes", "pptmaster"}
        violations = forbidden & imported_tops
        assert not violations, (
            f"slidestein.domain.models imports forbidden modules: {violations}"
        )

    def test_models_module_does_not_import_pptx_layer(self) -> None:
        import ast
        import importlib.util

        spec = importlib.util.find_spec("slidestein.domain.models")
        assert spec is not None and spec.origin is not None
        source = Path(spec.origin).read_text(encoding="utf-8")

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("slidestein.pptx"), (
                    f"domain/models.py must not import from slidestein.pptx; "
                    f"found: {node.module}"
                )
