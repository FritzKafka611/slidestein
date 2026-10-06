"""Stable slide identity: native PowerPoint IDs, UUID5 slide IDs, and fingerprints.

Functions in this module are pure — they read files and return values.
No Anthropic SDK, no SQLite, no pptx writing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_SLIDE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
)


@dataclass(frozen=True)
class SlideIdentity:
    """Native identity info for one slide in a PPTX deck."""
    slide_number: int       # 1-indexed, determined by order in sldIdLst
    native_slide_id: int    # from p:sldId id="" attribute — stable across edits
    slide_part: str         # zip-relative path: "slides/slideN.xml" (relative to ppt/)


def extract_slide_identities(pptx_path: Path) -> list[SlideIdentity]:
    """Return one SlideIdentity per slide, ordered by presentation order.

    Reads the PPTX zip directly (no python-pptx) so the native IDs are not
    altered.  The slide_part is relative to the ppt/ directory inside the zip,
    e.g. "slides/slide1.xml".

    Raises
    ------
    ValueError
        If the PPTX is malformed (missing presentation.xml or relationships).
    """
    with zipfile.ZipFile(pptx_path, "r") as z:
        # Parse relationship file to build {r_id -> slide_part} mapping.
        try:
            rels_xml = z.read("ppt/_rels/presentation.xml.rels")
        except KeyError as exc:
            raise ValueError(
                f"Malformed PPTX — missing ppt/_rels/presentation.xml.rels: {pptx_path}"
            ) from exc

        rels_root = ET.fromstring(rels_xml)
        r_id_to_part: dict[str, str] = {}
        for rel in rels_root.findall(f"{{{_NS_REL}}}Relationship"):
            if rel.get("Type") == _SLIDE_REL_TYPE:
                r_id = rel.get("Id", "")
                target = rel.get("Target", "")
                # Target is like "slides/slide1.xml" (relative to ppt/)
                if target.startswith("/ppt/"):
                    target = target[len("/ppt/"):]
                r_id_to_part[r_id] = target

        # Parse presentation.xml to get ordered sldIdLst entries.
        try:
            prs_xml = z.read("ppt/presentation.xml")
        except KeyError as exc:
            raise ValueError(
                f"Malformed PPTX — missing ppt/presentation.xml: {pptx_path}"
            ) from exc

        prs_root = ET.fromstring(prs_xml)
        sld_id_lst = prs_root.find(f"{{{_NS_P}}}sldIdLst")
        if sld_id_lst is None:
            return []

        identities: list[SlideIdentity] = []
        for slide_number, sld_id_elem in enumerate(
            sld_id_lst.findall(f"{{{_NS_P}}}sldId"), start=1
        ):
            native_id_str = sld_id_elem.get("id", "")
            r_id = sld_id_elem.get(f"{{{_NS_R}}}id", "")
            if not native_id_str or not r_id:
                continue
            slide_part = r_id_to_part.get(r_id)
            if slide_part is None:
                continue
            identities.append(
                SlideIdentity(
                    slide_number=slide_number,
                    native_slide_id=int(native_id_str),
                    slide_part=slide_part,
                )
            )

    return identities


def make_stable_slide_id(deck_id: str, native_slide_id: int) -> str:
    """Return a UUID5 string stable across text edits, reorders, and renames.

    UUID5 is deterministic: same (deck_id, native_slide_id) → same UUID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{deck_id}:{native_slide_id}"))


def compute_deck_fingerprint(pptx_path: Path) -> str:
    """SHA-256 of the raw file bytes; returned as a full 64-character hex string."""
    return hashlib.sha256(pptx_path.read_bytes()).hexdigest()


def compute_content_fingerprint(pptx_path: Path, slide_part: str) -> str:
    """SHA-256 of the raw slide XML bytes from the PPTX zip.

    slide_part is relative to the ppt/ directory, e.g. "slides/slide1.xml".
    """
    with zipfile.ZipFile(pptx_path, "r") as z:
        data = z.read(f"ppt/{slide_part}")
    return hashlib.sha256(data).hexdigest()


def compute_structure_fingerprint(pptx_path: Path, slide_number: int) -> str:
    """SHA-256 of shape geometry — excludes all text values.

    The descriptor for each shape captures: shape_type, position, size,
    placeholder_type, has_chart, has_table.  Sorted by (top, left) for
    determinism.  Text changes do not affect this fingerprint.
    """
    prs = Presentation(str(pptx_path))
    slide = prs.slides[slide_number - 1]

    descriptors: list[dict] = []
    for shape in slide.shapes:
        placeholder_type: str | None = None
        if shape.is_placeholder:
            ph = shape.placeholder_format
            try:
                placeholder_type = ph.type.name
            except AttributeError:
                placeholder_type = str(ph.idx)

        try:
            shape_type_str = shape.shape_type.name
        except AttributeError:
            shape_type_str = str(shape.shape_type)

        descriptors.append(
            {
                "shape_type": shape_type_str,
                "left": int(shape.left) if shape.left is not None else None,
                "top": int(shape.top) if shape.top is not None else None,
                "width": int(shape.width) if shape.width is not None else None,
                "height": int(shape.height) if shape.height is not None else None,
                "placeholder_type": placeholder_type,
                "has_chart": bool(getattr(shape, "has_chart", False)),
                "has_table": bool(getattr(shape, "has_table", False)),
            }
        )

    # Sort by (top, left) so position-reordering in the XML does not matter.
    descriptors.sort(key=lambda d: (d["top"] or 0, d["left"] or 0))

    canonical = json.dumps(descriptors, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_input_fingerprint(
    slide_id: str,
    content_fp: str,
    structure_fp: str,
    classification_version: str,
    prompt_version: str,
) -> str:
    """SHA-256 of the colon-joined identity components.

    Changes whenever the slide content, structure, or classifier version changes.
    Used for staleness detection in the classification store.
    """
    raw = ":".join([slide_id, content_fp, structure_fp, classification_version, prompt_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
