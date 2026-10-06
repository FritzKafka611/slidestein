"""Unit and integration tests for PowerPointComEditor.

Unit tests mock comtypes so they run without Microsoft PowerPoint installed.
Integration tests are opt-in via @pytest.mark.integration and require:
  - tools/pptmaster-env/ with ppt-master installed
  - Microsoft PowerPoint (for COM automation and preview rendering)
Run integration tests with: pytest -m integration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.pptx.com_editor import (
    PowerPointComEditor,
    PowerPointComEditorError,
    ReplacementResult,
    ReplacementStatus,
    TextTarget,
    _collect_text_targets,
    _replace_all,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_shape(
    shape_id: int,
    name: str,
    text: str,
    shape_type: int = 1,
) -> MagicMock:
    """Return a mock COM shape with a text frame containing *text*."""
    shape = MagicMock()
    shape.Id = shape_id
    shape.Name = name
    shape.HasTextFrame = True
    shape.TextFrame.HasText = True
    shape.TextFrame.TextRange.Text = text
    shape.Type = shape_type
    # Bounds
    shape.Left = 100.0
    shape.Top = 50.0
    shape.Width = 400.0
    shape.Height = 60.0
    return shape


def _make_non_text_shape() -> MagicMock:
    shape = MagicMock()
    shape.HasTextFrame = False
    return shape


def _make_empty_text_shape() -> MagicMock:
    shape = MagicMock()
    shape.HasTextFrame = True
    shape.TextFrame.HasText = False
    return shape


def _make_ppt_mock(shapes: list[MagicMock]) -> MagicMock:
    """Return a mock PowerPoint.Application wired with *shapes* on slide 1."""
    mock_slide = MagicMock()
    mock_slide.Shapes = shapes

    mock_prs = MagicMock()
    mock_prs.Slides.return_value = mock_slide

    mock_ppt = MagicMock()
    mock_ppt.Presentations.Open.return_value = mock_prs
    return mock_ppt


# ---------------------------------------------------------------------------
# TextTarget dataclass
# ---------------------------------------------------------------------------


class TestTextTarget:
    def test_required_fields(self) -> None:
        t = TextTarget(shape_id=2, shape_name="Title 1", current_text="Agenda")
        assert t.shape_id == 2
        assert t.shape_name == "Title 1"
        assert t.current_text == "Agenda"
        assert t.placeholder_type is None
        assert t.paragraph_count == 0
        assert t.text_bounds is None

    def test_with_all_optional_fields(self) -> None:
        t = TextTarget(
            shape_id=5,
            shape_name="TextBox 1",
            current_text="Hello",
            placeholder_type=1,
            paragraph_count=3,
            text_bounds=(10.0, 20.0, 200.0, 50.0),
        )
        assert t.placeholder_type == 1
        assert t.paragraph_count == 3
        assert t.text_bounds == (10.0, 20.0, 200.0, 50.0)


# ---------------------------------------------------------------------------
# _replace_all
# ---------------------------------------------------------------------------


class TestReplaceAll:
    def test_calls_replace_once_when_single_occurrence(self) -> None:
        tr = MagicMock()
        # First call: found (returns non-None). Second: no more (returns None).
        tr.Replace.side_effect = [MagicMock(), None]
        _replace_all(tr, "old", "new")
        assert tr.Replace.call_count == 2

    def test_replace_called_with_correct_args(self) -> None:
        tr = MagicMock()
        tr.Replace.side_effect = [MagicMock(), None]
        _replace_all(tr, "Agenda", "Our Plan")
        # positional: Replace(FindWhat, ReplaceWhat, After, MatchCase, WholeWords)
        tr.Replace.assert_called_with("Agenda", "Our Plan", 0, -1, 0)

    def test_breaks_immediately_when_none_returned(self) -> None:
        tr = MagicMock()
        tr.Replace.return_value = None
        _replace_all(tr, "old", "new")
        assert tr.Replace.call_count == 1

    def test_breaks_when_new_contains_old(self) -> None:
        """Replace 'a' with 'ab': new contains old — guard against infinite loop."""
        tr = MagicMock()
        tr.Replace.return_value = MagicMock()  # always found
        _replace_all(tr, "a", "ab")
        assert tr.Replace.call_count == 1  # stopped after first replacement

    def test_safety_limit_stops_loop(self) -> None:
        tr = MagicMock()
        tr.Replace.return_value = MagicMock()  # never returns None
        _replace_all(tr, "x", "y", max_iterations=5)
        assert tr.Replace.call_count == 5

    def test_exception_in_replace_propagates(self) -> None:
        """COM errors must propagate — _replace_all no longer swallows them."""
        tr = MagicMock()
        tr.Replace.side_effect = RuntimeError("COM error")
        with pytest.raises(RuntimeError, match="COM error"):
            _replace_all(tr, "old", "new")
        assert tr.Replace.call_count == 1


# ---------------------------------------------------------------------------
# _collect_text_targets
# ---------------------------------------------------------------------------


class TestCollectTextTargets:
    def test_returns_text_targets_for_text_shapes(self) -> None:
        shape = _make_text_shape(2, "Title 1", "Agenda", shape_type=14)
        shape.PlaceholderFormat.Type = 1
        mock_slide = MagicMock()
        mock_slide.Shapes = [shape]
        targets = _collect_text_targets(mock_slide)
        assert len(targets) == 1
        assert targets[0].shape_id == 2
        assert targets[0].shape_name == "Title 1"
        assert targets[0].current_text == "Agenda"

    def test_skips_non_text_shapes(self) -> None:
        mock_slide = MagicMock()
        mock_slide.Shapes = [_make_non_text_shape(), _make_empty_text_shape()]
        targets = _collect_text_targets(mock_slide)
        assert targets == []

    def test_captures_bounds(self) -> None:
        shape = _make_text_shape(3, "Box", "Hello")
        mock_slide = MagicMock()
        mock_slide.Shapes = [shape]
        targets = _collect_text_targets(mock_slide)
        assert targets[0].text_bounds == (100.0, 50.0, 400.0, 60.0)

    def test_placeholder_type_captured_for_placeholder_shapes(self) -> None:
        shape = _make_text_shape(1, "Title", "Main Title", shape_type=14)
        shape.PlaceholderFormat.Type = 1
        mock_slide = MagicMock()
        mock_slide.Shapes = [shape]
        targets = _collect_text_targets(mock_slide)
        assert targets[0].placeholder_type == 1

    def test_placeholder_type_none_for_non_placeholder(self) -> None:
        shape = _make_text_shape(7, "TextBox 1", "Body text", shape_type=17)
        mock_slide = MagicMock()
        mock_slide.Shapes = [shape]
        targets = _collect_text_targets(mock_slide)
        assert targets[0].placeholder_type is None

    def test_skips_shape_on_error_and_continues(self) -> None:
        bad_shape = MagicMock()
        bad_shape.HasTextFrame = True
        bad_shape.TextFrame.HasText = True
        bad_shape.TextFrame.TextRange.Text = "ok"
        bad_shape.Id = 9
        bad_shape.Name = "ok"
        bad_shape.Type = 1
        bad_shape.Left = MagicMock(side_effect=RuntimeError("COM error"))

        good_shape = _make_text_shape(10, "Good", "Good text")

        mock_slide = MagicMock()
        mock_slide.Shapes = [bad_shape, good_shape]
        # bad_shape raises on Left, but should still produce a TextTarget
        # (bounds would be None).  Both shapes are processed.
        targets = _collect_text_targets(mock_slide)
        assert any(t.shape_id == 10 for t in targets)


# ---------------------------------------------------------------------------
# PowerPointComEditor.enumerate_text_shapes
# ---------------------------------------------------------------------------


class TestEnumerateTextShapes:
    def test_returns_text_targets(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"PK")
        shape = _make_text_shape(2, "Title 1", "Agenda", shape_type=14)
        shape.PlaceholderFormat.Type = 1
        mock_ppt = _make_ppt_mock([shape])

        with patch("comtypes.client.CreateObject", return_value=mock_ppt):
            editor = PowerPointComEditor()
            targets = editor.enumerate_text_shapes(pptx)

        assert len(targets) == 1
        assert targets[0].current_text == "Agenda"

    def test_opens_read_only(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"PK")
        mock_ppt = _make_ppt_mock([])

        with patch("comtypes.client.CreateObject", return_value=mock_ppt):
            PowerPointComEditor().enumerate_text_shapes(pptx)

        call_kwargs = mock_ppt.Presentations.Open.call_args
        assert call_kwargs.kwargs.get("ReadOnly") is True or call_kwargs[1].get("ReadOnly") is True

    def test_quits_after_success(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"PK")
        mock_ppt = _make_ppt_mock([])

        with patch("comtypes.client.CreateObject", return_value=mock_ppt):
            PowerPointComEditor().enumerate_text_shapes(pptx)

        mock_ppt.Quit.assert_called_once()

    def test_quits_on_error(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"PK")
        mock_ppt = MagicMock()
        mock_ppt.Presentations.Open.side_effect = RuntimeError("COM failure")

        with patch("comtypes.client.CreateObject", return_value=mock_ppt):
            with pytest.raises(PowerPointComEditorError):
                PowerPointComEditor().enumerate_text_shapes(pptx)

        mock_ppt.Quit.assert_called_once()

    def test_raises_if_comtypes_missing(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"PK")
        with patch.dict("sys.modules", {"comtypes": None, "comtypes.client": None}):
            with pytest.raises((PowerPointComEditorError, ImportError)):
                PowerPointComEditor().enumerate_text_shapes(pptx)


# ---------------------------------------------------------------------------
# PowerPointComEditor.replace_text
# ---------------------------------------------------------------------------

# Patch target for the python-pptx-based occurrence counter used in replace_text.
_COUNT_PATCH = "slidestein.pptx.com_editor._count_in_slide_text"


class TestReplaceText:
    def test_replaces_matching_text_and_saves(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        output = tmp_path / "out.pptx"

        shape = _make_text_shape(2, "Title", "Agenda")
        shape.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, side_effect=[1, 0]),  # before=1, after=0
        ):
            editor = PowerPointComEditor()
            results = editor.replace_text(
                source_pptx=source,
                replacements={"Agenda": "Our Plan"},
                output_path=output,
            )

        assert len(results) == 1
        assert results[0].requested == "Agenda"
        assert results[0].status == ReplacementStatus.REPLACED_AND_VERIFIED
        assert results[0].matched is True
        assert results[0].verified is True
        mock_ppt.Presentations.Open.return_value.SaveAs.assert_called_once()
        mock_ppt.Quit.assert_called_once()

    def test_returns_no_match_when_text_absent(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")

        shape = _make_text_shape(2, "Title", "Something else")
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, return_value=0),  # text not in source
        ):
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Our Plan"},
                output_path=tmp_path / "out.pptx",
            )

        assert len(results) == 1
        assert results[0].status == ReplacementStatus.NO_MATCH
        assert results[0].matched is False
        shape.TextFrame.TextRange.Replace.assert_not_called()

    def test_skips_shapes_without_text_frame(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")

        non_text = _make_non_text_shape()
        mock_ppt = _make_ppt_mock([non_text])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, return_value=0),
        ):
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Any": "Text"},
                output_path=tmp_path / "out.pptx",
            )

        assert len(results) == 1
        assert results[0].status == ReplacementStatus.NO_MATCH

    def test_skips_empty_old_key(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")

        shape = _make_text_shape(1, "Title", "Hello")
        mock_ppt = _make_ppt_mock([shape])

        with patch("comtypes.client.CreateObject", return_value=mock_ppt):
            # No _count_in_slide_text call — empty key filtered before counting
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"": "Should not replace"},
                output_path=tmp_path / "out.pptx",
            )

        shape.TextFrame.TextRange.Replace.assert_not_called()
        assert results == []

    def test_multiple_shapes_all_searched(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        output = tmp_path / "out.pptx"

        shape1 = _make_text_shape(1, "Title", "Agenda")
        shape1.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]

        shape2 = _make_text_shape(2, "Body", "Agenda details")
        shape2.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]

        mock_ppt = _make_ppt_mock([shape1, shape2])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, side_effect=[1, 0]),
        ):
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Plan"},
                output_path=output,
            )

        shape1.TextFrame.TextRange.Replace.assert_called()
        shape2.TextFrame.TextRange.Replace.assert_called()
        assert len(results) == 1
        assert results[0].status == ReplacementStatus.REPLACED_AND_VERIFIED

    def test_saves_to_correct_output_path(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        output = tmp_path / "subdir" / "result.pptx"

        # Use a shape with text so active_replacements is non-empty and COM opens.
        shape = _make_text_shape(1, "Box", "Agenda")
        shape.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, side_effect=[1, 0]),
        ):
            PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Plan"},
                output_path=output,
            )

        prs = mock_ppt.Presentations.Open.return_value
        prs.SaveAs.assert_called_once_with(str(output.resolve()))
        assert output.parent.exists()

    def test_opens_for_editing(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        shape = _make_text_shape(1, "Box", "Agenda")
        shape.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, side_effect=[1, 0]),
        ):
            PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Plan"},
                output_path=tmp_path / "out.pptx",
            )

        open_kwargs = mock_ppt.Presentations.Open.call_args
        kwargs = open_kwargs.kwargs if open_kwargs.kwargs else open_kwargs[1]
        assert kwargs.get("ReadOnly") is False

    def test_quits_on_com_error(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        mock_ppt = MagicMock()
        mock_ppt.Presentations.Open.side_effect = RuntimeError("COM error")

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, return_value=1),
        ):
            with pytest.raises(PowerPointComEditorError):
                PowerPointComEditor().replace_text(
                    source_pptx=source,
                    replacements={"old": "new"},
                    output_path=tmp_path / "out.pptx",
                )

        mock_ppt.Quit.assert_called_once()

    def test_raises_powerpoint_com_editor_error_on_failure(self, tmp_path: Path) -> None:
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        mock_ppt = MagicMock()
        mock_ppt.Presentations.Open.side_effect = RuntimeError("Access denied")

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, return_value=1),
        ):
            with pytest.raises(PowerPointComEditorError, match="PowerPoint COM editing failed"):
                PowerPointComEditor().replace_text(
                    source_pptx=source,
                    replacements={"a": "b"},
                    output_path=tmp_path / "out.pptx",
                )


# ---------------------------------------------------------------------------
# Hardening regression tests
# ---------------------------------------------------------------------------


class TestReplaceTextHardening:
    """Regression tests for the fail-closed + verification hardening pass.

    These four scenarios previously produced silent false-positive success.
    """

    def test_com_replace_error_raises_editor_error(self, tmp_path: Path) -> None:
        """COM Replace raising must surface as PowerPointComEditorError, not be swallowed."""
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")

        shape = _make_text_shape(1, "Box", "Agenda")
        shape.TextFrame.TextRange.Replace.side_effect = RuntimeError("COM Replace failed")
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, return_value=1),
        ):
            with pytest.raises(PowerPointComEditorError):
                PowerPointComEditor().replace_text(
                    source_pptx=source,
                    replacements={"Agenda": "Our Plan"},
                    output_path=tmp_path / "out.pptx",
                )

    def test_saveas_success_but_text_unchanged_returns_error_status(
        self, tmp_path: Path
    ) -> None:
        """If SaveAs completes but old text still present in output, status must be ERROR."""
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        output = tmp_path / "out.pptx"

        shape = _make_text_shape(1, "Box", "Agenda")
        # Replace claims success (returns non-None then None)
        shape.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            # before=1, after=1 — old text still present after SaveAs
            patch(_COUNT_PATCH, side_effect=[1, 1]),
        ):
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Our Plan"},
                output_path=output,
            )

        assert len(results) == 1
        r = results[0]
        assert r.status == ReplacementStatus.ERROR
        assert r.matched is True
        assert r.replaced is True
        assert r.verified is False
        assert r.occurrences_before == 1
        assert r.occurrences_after == 1
        assert r.error is not None

    def test_successful_replacement_verified(self, tmp_path: Path) -> None:
        """Successful replacement must produce REPLACED_AND_VERIFIED with correct counts."""
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")
        output = tmp_path / "out.pptx"

        shape = _make_text_shape(1, "Box", "Agenda")
        shape.TextFrame.TextRange.Replace.side_effect = [MagicMock(), None]
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, side_effect=[3, 0]),  # 3 before, 0 after
        ):
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Our Plan"},
                output_path=output,
            )

        assert len(results) == 1
        r = results[0]
        assert r.status == ReplacementStatus.REPLACED_AND_VERIFIED
        assert r.occurrences_before == 3
        assert r.occurrences_after == 0
        assert r.matched is True
        assert r.replaced is True
        assert r.verified is True
        assert r.error is None

    def test_no_match_returns_no_match_status(self, tmp_path: Path) -> None:
        """Text not found in any shape must produce NO_MATCH, not an empty list."""
        source = tmp_path / "source.pptx"
        source.write_bytes(b"PK")

        shape = _make_text_shape(1, "Box", "Something completely different")
        mock_ppt = _make_ppt_mock([shape])

        with (
            patch("comtypes.client.CreateObject", return_value=mock_ppt),
            patch(_COUNT_PATCH, return_value=0),
        ):
            results = PowerPointComEditor().replace_text(
                source_pptx=source,
                replacements={"Agenda": "Our Plan"},
                output_path=tmp_path / "out.pptx",
            )

        assert len(results) == 1
        r = results[0]
        assert r.status == ReplacementStatus.NO_MATCH
        assert r.matched is False
        assert r.replaced is False
        assert r.verified is False
        assert r.occurrences_before == 0


# ---------------------------------------------------------------------------
# Integration (opt-in — requires ppt-master + PowerPoint)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPowerPointComEditorIntegration:
    """End-to-end tests.  Require:
    - tools/pptmaster-env/ with ppt-master installed
    - Microsoft PowerPoint COM available
    Run with: pytest -m integration
    """

    DECK = Path("data/test_decks/sample_consulting_deck.pptx")

    def _extract_slide(
        self,
        slide_number: int,
        tmp_path: Path,
        ws_suffix: str = "ws",
    ) -> Path:
        from slidestein.pptx.pptmaster_real_adapter import PPTMasterRealAdapter

        adapter = PPTMasterRealAdapter.from_auto_discover(
            workspace_root=tmp_path / ws_suffix
        )
        out = tmp_path / f"slide_{slide_number:02d}.pptx"
        adapter.extract_slide(self.DECK, slide_number=slide_number, output_path=out)
        return out

    # A. Slide 3 — 37 shapes

    def test_enumerate_text_shapes_slide3(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        extracted = self._extract_slide(3, tmp_path)
        editor = PowerPointComEditor()
        targets = editor.enumerate_text_shapes(extracted, slide_number=1)
        assert len(targets) > 0, "No text shapes returned for slide 3"
        # Verify metadata is populated
        assert all(isinstance(t.shape_id, int) for t in targets)
        assert all(isinstance(t.shape_name, str) for t in targets)
        assert all(isinstance(t.current_text, str) for t in targets)

    def test_replace_text_slide3_agenda(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        extracted = self._extract_slide(3, tmp_path)
        editor = PowerPointComEditor()

        # Discover actual text on slide 3 — do not assume specific content
        targets = editor.enumerate_text_shapes(extracted, slide_number=1)
        target_text: str | None = None
        for t in targets:
            text = t.current_text.strip()
            # Pick a clean short string: no vertical tabs, no newlines, 3-40 chars
            if text and 3 <= len(text) <= 40 and "\x0b" not in text and "\n" not in text:
                target_text = text
                break
        if target_text is None:
            pytest.skip("No suitable short text found on slide 3 for replacement test")

        output = tmp_path / "slide_03_native.pptx"
        results = editor.replace_text(
            source_pptx=extracted,
            replacements={target_text: "NATIVE_TEST"},
            output_path=output,
        )

        assert output.exists(), "Output PPTX not created"
        assert output.stat().st_size > 10_000
        verified = [
            r for r in results
            if r.requested == target_text
            and r.status == ReplacementStatus.REPLACED_AND_VERIFIED
        ]
        assert verified, (
            f"Target text {target_text!r} not REPLACED_AND_VERIFIED; got: {results}"
        )

        # Verify the text change persisted using python-pptx
        from pptx import Presentation

        prs = Presentation(str(output))
        all_text = " ".join(
            shape.text_frame.text
            for slide in prs.slides
            for shape in slide.shapes
            if shape.has_text_frame
        )
        assert "NATIVE_TEST" in all_text, "Text change not visible in output PPTX"

    def test_opc_diff_slide3_only_slide_xml_changes(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        from slidestein.pptx.opc_diff import compare_pptx_packages

        extracted = self._extract_slide(3, tmp_path)
        editor = PowerPointComEditor()

        # Pick a real text string from this slide
        targets = editor.enumerate_text_shapes(extracted, slide_number=1)
        target_text: str | None = None
        for t in targets:
            text = t.current_text.strip()
            if text and 3 <= len(text) <= 40 and "\x0b" not in text and "\n" not in text:
                target_text = text
                break
        if target_text is None:
            pytest.skip("No suitable replacement text found on slide 3")

        output = tmp_path / "slide_03_native.pptx"
        editor.replace_text(
            source_pptx=extracted,
            replacements={target_text: "OPC_DIFF_TEST"},
            output_path=output,
        )

        diff = compare_pptx_packages(extracted, output)

        # At minimum the slide XML should change
        assert any("slide" in p for p in diff["changed"]), (
            f"Expected slide XML in changed parts; got changed={diff['changed']}"
        )
        # Charts should not be touched
        chart_changed = [p for p in diff["changed"] if "chart" in p]
        assert chart_changed == [], f"Charts unexpectedly changed: {chart_changed}"
        # Media should not change
        media_changed = [p for p in diff["changed"] if "media" in p]
        assert media_changed == [], f"Media unexpectedly changed: {media_changed}"
        # NOTE: slideLayout and slideMaster changes are expected — PowerPoint normalizes
        # these when it first opens a PPT-Master-generated file and saves it.  We do not
        # assert on them here.

    def test_render_preview_after_native_edit_slide3(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        extracted = self._extract_slide(3, tmp_path)
        editor = PowerPointComEditor()

        targets = editor.enumerate_text_shapes(extracted, slide_number=1)
        target_text: str | None = None
        for t in targets:
            text = t.current_text.strip()
            if text and 3 <= len(text) <= 40 and "\x0b" not in text and "\n" not in text:
                target_text = text
                break
        if target_text is None:
            pytest.skip("No suitable replacement text found on slide 3")

        output = tmp_path / "slide_03_native.pptx"
        editor.replace_text(
            source_pptx=extracted,
            replacements={target_text: "PREVIEW_TEST"},
            output_path=output,
        )

        from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

        png = tmp_path / "slide_03_native.png"
        PythonPptxAdapter().render_preview(output, slide_number=1, output_path=png)
        assert png.exists()
        assert png.stat().st_size > 1_000
        assert png.read_bytes()[:4] == b"\x89PNG"

    # B. Slide 14 — 100+ shapes

    def test_extract_and_enumerate_slide14_large(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        extracted = self._extract_slide(14, tmp_path)
        assert extracted.exists()
        assert extracted.stat().st_size > 10_000

        editor = PowerPointComEditor()
        targets = editor.enumerate_text_shapes(extracted, slide_number=1)
        assert len(targets) > 0, "No text shapes found on slide 14"

    def test_native_edit_slide14_if_text_exists(self, tmp_path: Path) -> None:
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        extracted = self._extract_slide(14, tmp_path, ws_suffix="ws14")
        editor = PowerPointComEditor()
        targets = editor.enumerate_text_shapes(extracted, slide_number=1)
        if not targets:
            pytest.skip("No text shapes on slide 14")

        # Use first available text as replacement target
        target_text = targets[0].current_text.strip()
        if not target_text or len(target_text) > 100:
            pytest.skip("First text shape has no suitable short text for replacement")

        output = tmp_path / "slide_14_native.pptx"
        results = editor.replace_text(
            source_pptx=extracted,
            replacements={target_text: "NATIVE_TEST_14"},
            output_path=output,
        )
        assert output.exists()
        verified = [
            r for r in results
            if r.requested == target_text
            and r.status == ReplacementStatus.REPLACED_AND_VERIFIED
        ]
        assert verified, f"Expected REPLACED_AND_VERIFIED; got: {results}"

    # C. Chart/table preservation

    def test_chart_unchanged_after_text_edit(self, tmp_path: Path) -> None:
        """Edit a text field on a slide with a chart; chart XML must not change."""
        if not self.DECK.exists():
            pytest.skip("Test deck not found")
        from slidestein.pptx.opc_diff import compare_pptx_packages
        import pptx

        # Find a slide that has both text and a chart
        presentation = pptx.Presentation(str(self.DECK))
        chart_slide_number = None
        chart_text = None
        for i, sl in enumerate(presentation.slides, start=1):
            has_chart = any(
                s.shape_type == 3 for s in sl.shapes  # MSO_SHAPE_TYPE.CHART = 3
            )
            has_text = any(
                s.has_text_frame and s.text_frame.text.strip()
                for s in sl.shapes
            )
            if has_chart and has_text:
                chart_slide_number = i
                for s in sl.shapes:
                    if s.has_text_frame and s.text_frame.text.strip():
                        chart_text = s.text_frame.text.strip()
                        if len(chart_text) < 80:
                            break
                break

        if chart_slide_number is None or not chart_text:
            pytest.skip("No slide with both chart and text found in this deck")

        extracted = self._extract_slide(chart_slide_number, tmp_path, ws_suffix="wsc")
        output = tmp_path / f"slide_{chart_slide_number:02d}_native.pptx"
        editor = PowerPointComEditor()
        editor.replace_text(
            source_pptx=extracted,
            replacements={chart_text: "CHART_SLIDE_TEST"},
            output_path=output,
        )

        diff = compare_pptx_packages(extracted, output)
        chart_changed = [p for p in diff["changed"] if "chart" in p]
        assert chart_changed == [], (
            f"Chart parts changed after text-only edit: {chart_changed}"
        )
