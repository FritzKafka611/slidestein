"""SAP AI Core visual QA provider tests for M8."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidestein.qa.models import VisualQAModelOutput
from slidestein.qa.providers.sap_aicore import (
    SAPAICoreVisualQAReviewer,
    VisualQAGenerationError,
    _strip_fences,
)


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_plain_json():
    raw = '{"recommendation": "pass"}'
    assert _strip_fences(raw) == raw


def test_strip_fences_markdown_json():
    raw = "```json\n{\"recommendation\": \"pass\"}\n```"
    assert _strip_fences(raw) == '{"recommendation": "pass"}'


def test_strip_fences_plain_code_block():
    raw = "```\n{\"foo\": 1}\n```"
    assert _strip_fences(raw) == '{"foo": 1}'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reviewer():
    ai_core_client = MagicMock()
    return SAPAICoreVisualQAReviewer(
        ai_core_client=ai_core_client,
        model="claude-3.5-sonnet",
    )


def _make_valid_output_json() -> str:
    return json.dumps({
        "recommendation": "pass",
        "text_fit_and_clipping": {"score": 5, "rationale": "Clean."},
        "visual_hierarchy": {"score": 4, "rationale": "Clear."},
        "alignment_and_spacing": {"score": 4, "rationale": "OK."},
        "balance_and_whitespace": {"score": 4, "rationale": "Good."},
        "typography_and_style_consistency": {"score": 4, "rationale": "Consistent."},
        "overall_readability": {"score": 4, "rationale": "Readable."},
        "issues": [],
        "executive_summary": "Slide renders cleanly.",
    })


def _make_fake_images(tmp_path) -> tuple[Path, Path, Path]:
    from PIL import Image  # noqa: PLC0415

    gen = tmp_path / "generated.png"
    tpl = tmp_path / "template.png"
    ovl = tmp_path / "overlay.png"
    for p in (gen, tpl, ovl):
        Image.new("RGB", (100, 100), color=(128, 128, 128)).save(str(p))
    return gen, tpl, ovl


# ---------------------------------------------------------------------------
# review() — valid output
# ---------------------------------------------------------------------------


def test_review_valid_json_returns_model_output(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    with patch.object(reviewer, "_run_orchestration", return_value=_make_valid_output_json()):
        result = reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])

    assert isinstance(result, VisualQAModelOutput)
    assert result.recommendation == "pass"


def test_review_fenced_json_is_parsed(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    fenced = f"```json\n{_make_valid_output_json()}\n```"
    with patch.object(reviewer, "_run_orchestration", return_value=fenced):
        result = reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])

    assert result.recommendation == "pass"


def test_review_calls_run_orchestration_exactly_once(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    with patch.object(reviewer, "_run_orchestration", return_value=_make_valid_output_json()) as m:
        reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])

    m.assert_called_once()


# ---------------------------------------------------------------------------
# review() — invalid output
# ---------------------------------------------------------------------------


def test_review_invalid_score_raises_generation_error(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    bad_json = json.dumps({
        "recommendation": "pass",
        "text_fit_and_clipping": {"score": 10, "rationale": "Bad"},  # invalid
        "visual_hierarchy": {"score": 4, "rationale": "OK"},
        "alignment_and_spacing": {"score": 4, "rationale": "OK"},
        "balance_and_whitespace": {"score": 4, "rationale": "OK"},
        "typography_and_style_consistency": {"score": 4, "rationale": "OK"},
        "overall_readability": {"score": 4, "rationale": "OK"},
        "issues": [],
        "executive_summary": "Summary.",
    })
    with patch.object(reviewer, "_run_orchestration", return_value=bad_json):
        with pytest.raises(VisualQAGenerationError):
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])


def test_review_invalid_recommendation_raises_generation_error(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    bad_json = json.dumps({
        "recommendation": "approve",  # invalid for VisualQAModelOutput
        "text_fit_and_clipping": {"score": 4, "rationale": "OK"},
        "visual_hierarchy": {"score": 4, "rationale": "OK"},
        "alignment_and_spacing": {"score": 4, "rationale": "OK"},
        "balance_and_whitespace": {"score": 4, "rationale": "OK"},
        "typography_and_style_consistency": {"score": 4, "rationale": "OK"},
        "overall_readability": {"score": 4, "rationale": "OK"},
        "issues": [],
        "executive_summary": "Summary.",
    })
    with patch.object(reviewer, "_run_orchestration", return_value=bad_json):
        with pytest.raises(VisualQAGenerationError):
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])


def test_review_malformed_json_raises_with_raw_preview(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    with patch.object(reviewer, "_run_orchestration", return_value="not json at all"):
        with pytest.raises(VisualQAGenerationError) as exc_info:
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])

    assert "Raw response" in str(exc_info.value)


def test_review_sdk_exception_wrapped(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    with patch.object(reviewer, "_run_orchestration", side_effect=RuntimeError("SDK exploded")):
        with pytest.raises(VisualQAGenerationError) as exc_info:
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])

    error_msg = str(exc_info.value)
    assert "SAP AI Core" in error_msg
    assert "RuntimeError" in error_msg
    # Must NOT contain credential-bearing details
    assert "SDK exploded" not in error_msg


def test_review_error_message_contains_no_credentials(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    class FakeSdkError(Exception):
        pass

    with patch.object(reviewer, "_run_orchestration",
                      side_effect=FakeSdkError("client_secret=supersecret token=abc123")):
        with pytest.raises(VisualQAGenerationError) as exc_info:
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])

    msg = str(exc_info.value)
    assert "supersecret" not in msg
    assert "token=abc123" not in msg


def test_review_extra_fields_in_output_raises(tmp_path):
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    bad_json = json.dumps({
        "recommendation": "pass",
        "text_fit_and_clipping": {"score": 4, "rationale": "OK"},
        "visual_hierarchy": {"score": 4, "rationale": "OK"},
        "alignment_and_spacing": {"score": 4, "rationale": "OK"},
        "balance_and_whitespace": {"score": 4, "rationale": "OK"},
        "typography_and_style_consistency": {"score": 4, "rationale": "OK"},
        "overall_readability": {"score": 4, "rationale": "OK"},
        "issues": [],
        "executive_summary": "Summary.",
        "average_score": 4.0,  # extra — should be forbidden
    })
    with patch.object(reviewer, "_run_orchestration", return_value=bad_json):
        with pytest.raises(VisualQAGenerationError):
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])


# ---------------------------------------------------------------------------
# Image content in _build_content
# ---------------------------------------------------------------------------


def test_build_content_includes_three_images(tmp_path):
    from gen_ai_hub.orchestration_v2 import ImageItem, TextPart  # type: ignore[import]
    reviewer = _make_reviewer()
    gen, tpl, ovl = _make_fake_images(tmp_path)

    try:
        content = reviewer._build_content(
            generated_image=gen,
            template_image=tpl,
            overlay_image=ovl,
            prompt_text="test",
        )
        image_parts = [p for p in content if isinstance(p, ImageItem)]
        assert len(image_parts) == 3
    except ImportError:
        pytest.skip("gen_ai_hub not available in test environment")


def test_build_content_missing_image_raises(tmp_path):
    reviewer = _make_reviewer()
    gen = tmp_path / "missing.png"  # does not exist
    tpl = tmp_path / "template.png"
    ovl = tmp_path / "overlay.png"
    from PIL import Image  # noqa: PLC0415
    Image.new("RGB", (10, 10)).save(str(tpl))
    Image.new("RGB", (10, 10)).save(str(ovl))

    try:
        with pytest.raises((VisualQAGenerationError, FileNotFoundError)):
            reviewer.review(gen, tpl, ovl, slot_specs=[], native_checks=[])
    except ImportError:
        pytest.skip("gen_ai_hub not available")


# ---------------------------------------------------------------------------
# Deployment ID caching
# ---------------------------------------------------------------------------


def test_deployment_id_cached_after_first_call():
    reviewer = _make_reviewer()
    reviewer._deployment_id_cache = "dep-abc"  # type: ignore[attr-defined]
    assert reviewer._get_orchestration_deployment_id() == "dep-abc"
