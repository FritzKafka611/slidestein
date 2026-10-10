"""Tests for M10 structural fingerprint computation."""

from __future__ import annotations

import hashlib
import json

import pytest

from slidestein.structural.fingerprint import (
    compute_structural_fingerprint,
    compute_structural_fingerprint_from_slot_map,
)

from .conftest import make_slot, make_slot_map
from slidestein.drafting.service import build_slot_key_mapping
from slidestein.slots.roles import SlotRole


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def _make_key_map(**overrides):
    slots = [
        make_slot(
            slot_id="slot-001",
            shape_id=21,
            shape_path="21",
            slot_role=SlotRole.TITLE,
            semantic_label="Title",
            x_emu=457200,
            y_emu=457200,
            w_emu=10972800,
            h_emu=685800,
            y_ratio=0.07,
            x_ratio=0.04,
        ),
        make_slot(
            slot_id="slot-002",
            shape_id=22,
            shape_path="22",
            slot_role=SlotRole.BODY_TEXT,
            semantic_label="Body",
            x_emu=457200,
            y_emu=1143000,
            w_emu=10972800,
            h_emu=4572000,
            y_ratio=0.25,
            x_ratio=0.04,
            max_chars=300,
            max_lines=6,
        ),
    ]
    return build_slot_key_mapping(slots)


def test_fingerprint_returns_string():
    km = _make_key_map()
    fp = compute_structural_fingerprint(km)
    assert isinstance(fp, str)
    assert len(fp) == 64  # SHA-256 hex


def test_fingerprint_deterministic():
    km1 = _make_key_map()
    km2 = _make_key_map()
    assert compute_structural_fingerprint(km1) == compute_structural_fingerprint(km2)


def test_fingerprint_from_slot_map_matches_from_key_map():
    sm = make_slot_map()
    km = build_slot_key_mapping(sm.slots)
    fp_map = compute_structural_fingerprint(km)
    fp_slot = compute_structural_fingerprint_from_slot_map(sm)
    assert fp_map == fp_slot


def test_fingerprint_changes_on_geometry_change():
    sm_a = make_slot_map(
        slots=[
            make_slot(
                slot_id="slot-001", shape_id=21, shape_path="21",
                slot_role=SlotRole.TITLE, semantic_label="Title",
                x_emu=457200, y_emu=457200, w_emu=10972800, h_emu=685800,
                y_ratio=0.07, x_ratio=0.04,
            )
        ]
    )
    sm_b = make_slot_map(
        slots=[
            make_slot(
                slot_id="slot-001", shape_id=21, shape_path="21",
                slot_role=SlotRole.TITLE, semantic_label="Title",
                x_emu=500000,  # different x
                y_emu=457200, w_emu=10972800, h_emu=685800,
                y_ratio=0.08, x_ratio=0.05,
            )
        ]
    )
    fp_a = compute_structural_fingerprint_from_slot_map(sm_a)
    fp_b = compute_structural_fingerprint_from_slot_map(sm_b)
    assert fp_a != fp_b


def test_fingerprint_excludes_text_content():
    """Fingerprint must NOT encode slot text — only geometry and role."""
    slot_a = make_slot(
        slot_id="slot-001", shape_id=21, shape_path="21",
        slot_role=SlotRole.TITLE, semantic_label="Title",
        x_emu=457200, y_emu=457200, w_emu=10972800, h_emu=685800,
        y_ratio=0.07, x_ratio=0.04,
    )
    # Manually mutate current_text after creation (geometry stays the same)
    import copy
    slot_b = slot_a.model_copy(update={"current_text": "Completely different text!"})
    km_a = build_slot_key_mapping([slot_a])
    km_b = build_slot_key_mapping([slot_b])
    assert compute_structural_fingerprint(km_a) == compute_structural_fingerprint(km_b)


def test_fingerprint_changes_on_role_change():
    slot_title = make_slot(
        slot_id="slot-001", shape_id=21, shape_path="21",
        slot_role=SlotRole.TITLE, semantic_label="Title",
        x_emu=457200, y_emu=457200, w_emu=10972800, h_emu=685800,
        y_ratio=0.07, x_ratio=0.04,
    )
    slot_body = slot_title.model_copy(update={"slot_role": SlotRole.BODY_TEXT})
    km_a = build_slot_key_mapping([slot_title])
    km_b = build_slot_key_mapping([slot_body])
    assert compute_structural_fingerprint(km_a) != compute_structural_fingerprint(km_b)


def test_fingerprint_changes_on_editable_change():
    slot_editable = make_slot(
        slot_id="slot-001", shape_id=21, shape_path="21",
        slot_role=SlotRole.TITLE, semantic_label="Title",
        x_emu=457200, y_emu=457200, w_emu=10972800, h_emu=685800,
        y_ratio=0.07, x_ratio=0.04,
        editable=True,
    )
    slot_non_editable = slot_editable.model_copy(update={"editable": False})
    km_a = build_slot_key_mapping([slot_editable])
    km_b = build_slot_key_mapping([slot_non_editable])
    assert compute_structural_fingerprint(km_a) != compute_structural_fingerprint(km_b)


def test_fingerprint_empty_slot_map():
    sm = make_slot_map(slots=[])
    fp = compute_structural_fingerprint_from_slot_map(sm)
    # SHA-256 of empty JSON list
    expected = hashlib.sha256(json.dumps([]).encode()).hexdigest()
    assert fp == expected
