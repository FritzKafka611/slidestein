"""Unit tests for OPC package comparison helper."""

from __future__ import annotations

import zipfile
from pathlib import Path

from slidestein.pptx.opc_diff import compare_pptx_packages


def _make_zip(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(str(path), "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)


class TestComparePptxPackages:
    def test_identical_packages_all_unchanged(self, tmp_path: Path) -> None:
        p = tmp_path / "test.pptx"
        _make_zip(p, {"ppt/slides/slide1.xml": "<slide/>"})
        diff = compare_pptx_packages(p, p)
        assert diff["changed"] == []
        assert diff["added"] == []
        assert diff["removed"] == []
        assert "ppt/slides/slide1.xml" in diff["unchanged"]

    def test_detects_changed_part(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {
            "ppt/slides/slide1.xml": "<slide>old</slide>",
            "ppt/theme/theme1.xml": "<theme/>",
        })
        _make_zip(after, {
            "ppt/slides/slide1.xml": "<slide>new</slide>",
            "ppt/theme/theme1.xml": "<theme/>",
        })
        diff = compare_pptx_packages(before, after)
        assert "ppt/slides/slide1.xml" in diff["changed"]
        assert "ppt/theme/theme1.xml" in diff["unchanged"]
        assert diff["added"] == []
        assert diff["removed"] == []

    def test_detects_added_part(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {"ppt/slides/slide1.xml": "<slide/>"})
        _make_zip(after, {
            "ppt/slides/slide1.xml": "<slide/>",
            "docProps/core.xml": "<core/>",
        })
        diff = compare_pptx_packages(before, after)
        assert "docProps/core.xml" in diff["added"]
        assert diff["removed"] == []
        assert diff["changed"] == []

    def test_detects_removed_part(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {
            "ppt/slides/slide1.xml": "<slide/>",
            "ppt/media/image1.png": "FAKEPNG",
        })
        _make_zip(after, {"ppt/slides/slide1.xml": "<slide/>"})
        diff = compare_pptx_packages(before, after)
        assert "ppt/media/image1.png" in diff["removed"]
        assert diff["added"] == []
        assert diff["changed"] == []

    def test_empty_packages(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {})
        _make_zip(after, {})
        diff = compare_pptx_packages(before, after)
        assert diff == {"changed": [], "unchanged": [], "added": [], "removed": []}

    def test_all_changed(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {"a.xml": "old_a", "b.xml": "old_b"})
        _make_zip(after, {"a.xml": "new_a", "b.xml": "new_b"})
        diff = compare_pptx_packages(before, after)
        assert sorted(diff["changed"]) == ["a.xml", "b.xml"]
        assert diff["unchanged"] == []

    def test_results_are_sorted_lexicographically(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {"z.xml": "old", "a.xml": "old"})
        _make_zip(after, {"z.xml": "new", "a.xml": "new"})
        diff = compare_pptx_packages(before, after)
        assert diff["changed"] == sorted(diff["changed"])

    def test_mixed_scenario(self, tmp_path: Path) -> None:
        before = tmp_path / "before.pptx"
        after = tmp_path / "after.pptx"
        _make_zip(before, {
            "ppt/slides/slide1.xml": "<slide>original text</slide>",
            "ppt/theme/theme1.xml": "<theme/>",
            "ppt/media/img.png": "FAKEPNG",
        })
        _make_zip(after, {
            "ppt/slides/slide1.xml": "<slide>replaced text</slide>",
            "ppt/theme/theme1.xml": "<theme/>",
            "docProps/core.xml": "<core/>",
        })
        diff = compare_pptx_packages(before, after)
        assert "ppt/slides/slide1.xml" in diff["changed"]
        assert "ppt/theme/theme1.xml" in diff["unchanged"]
        assert "docProps/core.xml" in diff["added"]
        assert "ppt/media/img.png" in diff["removed"]
