"""Regression tests for the vision-rerank CLI command.

Covers bugs found during M4.3 pilot:
  - SlideLibrary must be constructed with both db_path and lancedb_uri
  - --dry-run must not call the vision reranker API
  - Result display must contain only cp1252-safe characters (no U+2192 arrow etc.)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from typer.testing import CliRunner

from slidestein.cli import app
from slidestein.reranking.result import VisionRankedCandidate, VisionRerankResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Patch targets (all imports inside the CLI function are local, so we patch
# at the source module to intercept them at import time inside the function)
# ---------------------------------------------------------------------------

_PATCH_SETTINGS     = "slidestein.config.get_settings"
_PATCH_EMB_PROV     = "slidestein.retrieval.providers.factory.create_embedding_provider"
_PATCH_STORE        = "slidestein.retrieval.store.SlideVectorStore"
_PATCH_SEARCHER     = "slidestein.retrieval.hybrid.HybridSlideSearch"
_PATCH_LIBRARY      = "slidestein.library.store.SlideLibrary"
_PATCH_RERANKER_FAC = "slidestein.reranking.providers.factory.create_vision_reranker"
_PATCH_SERVICE      = "slidestein.reranking.service.VisionSlideRerankService"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.lancedb_uri = "data/lancedb"
    s.db_path = Path("data/slidestein.db")
    s.vision_rerank_provider = "sap_ai_core"
    s.sap_ai_core_model = "claude-3.5-sonnet"
    return s


def _mock_hybrid_result(slide_id: str, slide_number: int, rank: int) -> MagicMock:
    r = MagicMock()
    r.slide_id = slide_id
    r.slide_number = slide_number
    r.rank = rank
    r.hybrid_score = 0.70
    r.semantic_score = 0.60
    r.deck_id = "deck-1"
    return r


def _mock_slide_record(slide_id: str, preview_path: str = "/tmp/slide.png") -> MagicMock:
    r = MagicMock()
    r.slide_id = slide_id
    r.preview_path = preview_path
    return r


def _make_context_manager(instance: MagicMock) -> MagicMock:
    """Wrap a mock instance so it can be used as a context manager."""
    instance.__enter__ = lambda s: s
    instance.__exit__ = MagicMock(return_value=False)
    return instance


def _make_vision_result(
    slide_id: str = "aaaabbbbccccdddd",
    slide_number: int = 5,
) -> VisionRerankResult:
    candidate = VisionRankedCandidate(
        vision_rank=1,
        candidate_key="C1",
        slide_id=slide_id,
        slide_number=slide_number,
        visual_score=0.84,
        communication_structure_fit=4,
        content_capacity_fit=4,
        visual_hierarchy=4,
        argument_flow=4,
        density_fit=4,
        original_hybrid_rank=1,
        hybrid_score=0.75,
        semantic_score=0.65,
        rationale="Good visual structure for the requested communication need.",
        strengths=["Clear layout", "Strong hierarchy"],
        limitations=["Moderate density"],
    )
    return VisionRerankResult(
        selected_slide_id=slide_id,
        selected_slide_number=slide_number,
        vision_rerank_version="1.0",
        prompt_version="1.0",
        ranked_candidates=[candidate],
    )


def _base_patches(settings: MagicMock):
    """Return a list of patches common to most tests."""
    return [
        patch(_PATCH_SETTINGS, return_value=settings),
        patch(_PATCH_EMB_PROV, return_value=MagicMock()),
        patch(_PATCH_STORE, return_value=MagicMock()),
    ]


# ---------------------------------------------------------------------------
# A. SlideLibrary construction: both required arguments
# ---------------------------------------------------------------------------


class TestSlideLibraryConstruction:
    """Regression for: 'SlideLibrary.__init__() missing 1 required positional argument: lancedb_uri'"""

    def test_dry_run_constructs_library_with_both_args(self) -> None:
        settings = _mock_settings()
        hybrid_result = _mock_hybrid_result("slide-abc", 5, 1)
        searcher_instance = MagicMock()
        searcher_instance.search.return_value = [hybrid_result]
        lib_instance = _make_context_manager(MagicMock())
        lib_instance.get_slide.return_value = _mock_slide_record("slide-abc")

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance) as MockLib, \
             patch.object(Path, "exists", return_value=True):
            runner.invoke(app, ["vision-rerank", "timeline query", "--dry-run"])

        MockLib.assert_called_once_with(settings.db_path, settings.lancedb_uri)

    def test_rerank_constructs_library_with_both_args(self) -> None:
        settings = _mock_settings()
        searcher_instance = MagicMock()
        lib_instance = _make_context_manager(MagicMock())
        svc_instance = MagicMock()
        svc_instance.rerank.return_value = _make_vision_result()

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_RERANKER_FAC, return_value=MagicMock()), \
             patch(_PATCH_SERVICE, return_value=svc_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance) as MockLib:
            runner.invoke(app, ["vision-rerank", "timeline query"])

        MockLib.assert_called_once_with(settings.db_path, settings.lancedb_uri)


# ---------------------------------------------------------------------------
# B. --dry-run makes zero vision API calls
# ---------------------------------------------------------------------------


class TestDryRun:
    """Regression: --dry-run must never call create_vision_reranker or reranker.assess()."""

    def test_dry_run_does_not_call_create_vision_reranker(self) -> None:
        settings = _mock_settings()
        hybrid_result = _mock_hybrid_result("slide-xyz", 3, 1)
        searcher_instance = MagicMock()
        searcher_instance.search.return_value = [hybrid_result]
        lib_instance = _make_context_manager(MagicMock())
        lib_instance.get_slide.return_value = _mock_slide_record("slide-xyz")

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance), \
             patch(_PATCH_RERANKER_FAC) as mock_create_reranker, \
             patch.object(Path, "exists", return_value=True):
            result = runner.invoke(app, ["vision-rerank", "test query", "--dry-run"])

        mock_create_reranker.assert_not_called()
        assert result.exit_code == 0

    def test_dry_run_does_not_instantiate_service(self) -> None:
        settings = _mock_settings()
        hybrid_result = _mock_hybrid_result("slide-abc", 5, 1)
        searcher_instance = MagicMock()
        searcher_instance.search.return_value = [hybrid_result]
        lib_instance = _make_context_manager(MagicMock())
        lib_instance.get_slide.return_value = _mock_slide_record("slide-abc")

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance), \
             patch(_PATCH_SERVICE) as mock_svc_cls, \
             patch(_PATCH_RERANKER_FAC, return_value=MagicMock()), \
             patch.object(Path, "exists", return_value=True):
            runner.invoke(app, ["vision-rerank", "test query", "--dry-run"])

        mock_svc_cls.assert_not_called()

    def test_dry_run_output_mentions_dry_run(self) -> None:
        settings = _mock_settings()
        hybrid_result = _mock_hybrid_result("slide-xyz", 3, 1)
        searcher_instance = MagicMock()
        searcher_instance.search.return_value = [hybrid_result]
        lib_instance = _make_context_manager(MagicMock())
        lib_instance.get_slide.return_value = _mock_slide_record("slide-xyz")

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance), \
             patch(_PATCH_RERANKER_FAC, return_value=MagicMock()), \
             patch.object(Path, "exists", return_value=True):
            result = runner.invoke(app, ["vision-rerank", "test query", "--dry-run"])

        assert "dry" in result.output.lower()
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# C. Result display: cp1252-safe, no U+2192 (→) or other unsafe arrows
# ---------------------------------------------------------------------------


class TestResultDisplayEncoding:
    """Regression for: UnicodeEncodeError 'charmap' can't encode character U+2192 (→)."""

    def _invoke_rerank(self) -> str:
        settings = _mock_settings()
        searcher_instance = MagicMock()
        lib_instance = _make_context_manager(MagicMock())
        svc_instance = MagicMock()
        svc_instance.rerank.return_value = _make_vision_result()

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_RERANKER_FAC, return_value=MagicMock()), \
             patch(_PATCH_SERVICE, return_value=svc_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance):
            result = runner.invoke(app, ["vision-rerank", "test query"])

        return result.output

    def test_no_rightwards_arrow_in_output(self) -> None:
        """U+2192 RIGHTWARDS ARROW must not appear — crashes cp1252 Windows consoles."""
        output = self._invoke_rerank()
        assert "→" not in output, (
            "Found U+2192 (→) in CLI output. This character crashes Windows cp1252 consoles."
        )

    def test_output_is_cp1252_encodable(self) -> None:
        """Every character in CLI output must be encodable as Windows cp1252."""
        output = self._invoke_rerank()
        try:
            output.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(
                f"CLI output contains a character not encodable as cp1252: {exc}\n"
                f"Full output: {output!r}"
            )

    def test_winner_indicator_is_ascii_only(self) -> None:
        """The winner-row prefix indicator must use only ASCII characters.

        The indicator is the first 3 characters before the rank label.
        U+2026 (…) in slide IDs is cp1252-safe and acceptable.
        """
        output = self._invoke_rerank()
        for line in output.splitlines():
            if "winner" in line.lower():
                # The indicator prefix (first 3 chars) must be ASCII
                indicator = line[:3]
                assert indicator.isascii(), (
                    f"Winner indicator {indicator!r} contains non-ASCII. "
                    f"Full line: {line!r}"
                )
                break

    def test_exit_code_zero_after_successful_rerank(self) -> None:
        settings = _mock_settings()
        searcher_instance = MagicMock()
        lib_instance = _make_context_manager(MagicMock())
        svc_instance = MagicMock()
        svc_instance.rerank.return_value = _make_vision_result()

        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=searcher_instance), \
             patch(_PATCH_RERANKER_FAC, return_value=MagicMock()), \
             patch(_PATCH_SERVICE, return_value=svc_instance), \
             patch(_PATCH_LIBRARY, return_value=lib_instance):
            result = runner.invoke(app, ["vision-rerank", "test query"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# D. Basic input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_blank_query_exits_1(self) -> None:
        settings = _mock_settings()
        with patch(_PATCH_SETTINGS, return_value=settings):
            result = runner.invoke(app, ["vision-rerank", "   "])
        assert result.exit_code == 1

    def test_candidate_k_too_low_exits_1(self) -> None:
        settings = _mock_settings()
        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=MagicMock()):
            result = runner.invoke(app, ["vision-rerank", "query", "--candidate-k", "1"])
        assert result.exit_code == 1

    def test_candidate_k_too_high_exits_1(self) -> None:
        settings = _mock_settings()
        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=MagicMock()):
            result = runner.invoke(app, ["vision-rerank", "query", "--candidate-k", "9"])
        assert result.exit_code == 1

    def test_unknown_archetype_exits_1(self) -> None:
        settings = _mock_settings()
        with patch(_PATCH_SETTINGS, return_value=settings), \
             patch(_PATCH_EMB_PROV, return_value=MagicMock()), \
             patch(_PATCH_STORE, return_value=MagicMock()), \
             patch(_PATCH_SEARCHER, return_value=MagicMock()):
            result = runner.invoke(
                app, ["vision-rerank", "query", "--archetype", "does_not_exist_123"]
            )
        assert result.exit_code == 1
