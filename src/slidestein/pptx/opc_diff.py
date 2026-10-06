"""OPC package comparison — diagnose which PPTX parts change after native editing.

PPTX files are ZIP-based OPC (Open Packaging Convention) packages.  This module
compares two packages by the MD5 digest of each part and categorises the diff:

  changed   — present in both; different content
  unchanged — present in both; identical content
  added     — present only in the *after* package
  removed   — present only in the *before* package

Intended use: after native COM text replacement, verify that only the expected
parts changed.  A minimal text edit should touch only the relevant slide XML and
PowerPoint-generated metadata (docProps/core.xml, [Content_Types].xml).

Charts, media, theme, masters, layouts, and slide relationships should remain
unchanged when text is replaced through COM without touching other objects.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def compare_pptx_packages(
    before_path: Path,
    after_path: Path,
) -> dict[str, list[str]]:
    """Return a categorised diff of two PPTX (OPC) packages.

    Compares every part (ZIP entry) by MD5 digest.  Ordering within all returned
    lists is lexicographic so results are deterministic across runs.

    Returns:
        A dict with keys 'changed', 'unchanged', 'added', 'removed', each mapping
        to a sorted list of OPC part paths (e.g. 'ppt/slides/slide1.xml').
    """
    before = _digest_parts(before_path)
    after = _digest_parts(after_path)

    before_names = set(before)
    after_names = set(after)
    common = before_names & after_names

    return {
        "changed": sorted(n for n in common if before[n] != after[n]),
        "unchanged": sorted(n for n in common if before[n] == after[n]),
        "added": sorted(after_names - before_names),
        "removed": sorted(before_names - after_names),
    }


def _digest_parts(path: Path) -> dict[str, bytes]:
    """Return {part_path: md5_digest} for every entry in the OPC package."""
    with zipfile.ZipFile(str(path), "r") as z:
        return {name: hashlib.md5(z.read(name)).digest() for name in z.namelist()}
