from pathlib import Path

from obed_edom.parse_outline import parse_outline
from obed_edom.slide_map import map_slides
from obed_edom.validate import validate_inspect, validate_slide_specs, validate_style_text

OUTLINES = Path(__file__).resolve().parents[1] / "Sermon Outlines"


def test_style_en_dash_and_books():
    flags = validate_style_text("See Psalms 23 and Revelation 1. Lived 1980-2012. Meet 3-4 Jun.", location="t")
    cats = {f.category for f in flags}
    assert "book_name" in cats
    assert "date" in cats
    messages = " ".join(f.message for f in flags)
    assert "Psalm" in messages
    assert "Revelations" in messages
    assert "en dash" in messages


def test_trinity_lowercase_god():
    flags = validate_style_text("we love god forever", location="t")
    assert any(f.category == "trinity" for f in flags)


def test_continued_dsk_verse_overflow_is_flagged():
    offering = parse_outline(OUTLINES / "Offering JX.docx")
    lw, dsk, _ = map_slides(offering)
    flags = validate_slide_specs(lw, dsk)
    overflow = [f for f in flags if f.category == "overflow"]
    assert overflow
    assert any("DSK" in (f.location or "") for f in overflow)
    assert any("VERSE-CONTINUED" in f.message for f in overflow)
    assert any("lower-third" in f.message for f in overflow)
    assert not any("LW" in (f.location or "") for f in overflow)


def test_inspect_overflow_from_box_geometry():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    {
                        "kind": "text",
                        "text": (
                            "People who don't know God and the way he works fuss over these things, "
                            "but you know both God and how he works. Steep your life in God-reality, "
                            "God-initiative, God-provisions. Don't worry about missing out. You'll "
                            "find all your everyday human concerns will be met."
                        ),
                        "w": 1540,
                        "h": 90,
                        "size": 45,
                        "runs": [{"text": "People who don't know God", "size": 45}],
                    }
                ],
            }
        ],
    }
    flags = validate_inspect(payload, location_prefix="demo.key")
    assert any(f.category == "overflow" for f in flags)

    tight_ok = {
        "path": "ok.key",
        "slideWidth": 1920,
        "slides": [
            {
                "number": 1,
                "items": [
                    {
                        "kind": "text",
                        "text": "but you know both God and how he works.",
                        "w": 1540,
                        "h": 120,
                        "size": 45,
                    }
                ],
            }
        ],
    }
    ok_flags = validate_inspect(tight_ok, location_prefix="ok.key")
    assert not any(f.category == "overflow" for f in ok_flags)


def test_validate_inspect_skips_hidden_slides():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "skipped": True,
                "items": [
                    {
                        "kind": "text",
                        "text": "we love god forever",
                        "w": 1540,
                        "h": 120,
                        "size": 45,
                    }
                ],
            },
            {
                "number": 2,
                "skipped": False,
                "items": [{"kind": "text", "text": "Faith", "w": 400, "h": 80, "size": 45}],
            },
        ],
    }
    flags = validate_inspect(payload, location_prefix="demo.key")
    assert not any(f.category == "trinity" for f in flags)
    assert not any("slide 1" in (f.location or "") for f in flags)


def _wall(*items) -> dict:
    return {
        "path": "wall.key",
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": list(items)}],
    }


def test_bounds_ignores_side_panels_and_backdrops():
    """A 7680 wall legitimately uses both wings; only cut objects are mistakes."""
    from obed_edom.validate import _bounds_flags

    payload = _wall(
        {"kind": "image", "text": "", "x": 0, "y": 0, "w": 7680, "h": 1080},
        {"kind": "image", "text": "", "x": 0, "y": 0, "w": 1920, "h": 1080},
        {"kind": "image", "text": "", "x": 5760, "y": 0, "w": 1920, "h": 1080},
        {"kind": "text", "text": "Faith", "x": 2200, "y": 400, "w": 1200, "h": 200},
    )
    assert _bounds_flags(payload, "LW", deck="lw") == []


def test_bounds_flags_straddling_object_with_evidence(tmp_path):
    from PIL import Image

    from obed_edom.validate import _bounds_flags

    png = tmp_path / "slide-001.png"
    Image.new("RGB", (7680, 1080), (20, 20, 20)).save(png)
    payload = _wall({"kind": "text", "text": "Faith", "x": 1400, "y": 400, "w": 1400, "h": 200})
    evidence_dir = tmp_path / "evidence"
    flags = _bounds_flags(
        payload, "LW", deck="lw", png_map={0: png}, evidence_dir=evidence_dir
    )
    assert [f.rule for f in flags] == ["bounds.straddles"]
    assert flags[0].slide == 1
    assert "x=1920" in flags[0].message
    assert flags[0].evidence
    assert (evidence_dir / flags[0].evidence).exists()


def test_rule_severity_map_can_silence_a_rule(monkeypatch):
    from obed_edom import validate

    monkeypatch.setattr(validate, "load_rules", lambda: {"rules": {"text.word": "off"}})
    assert validate.rule_severity("text.word") is None
    assert validate.make_flag("text.word", "diff", "nope") is None
    monkeypatch.setattr(validate, "load_rules", lambda: {"rules": {"text.word": "error"}})
    flag = validate.make_flag("text.word", "diff", "yep", default="warning")
    assert flag is not None and flag.severity == "error"


def test_flag_dict_includes_yaml_title():
    from obed_edom.validate import flag_dict, make_flag

    flag = make_flag("style.glossary", "glossary", "near miss", location="LW slide 1", slide=1, deck="lw")
    assert flag is not None
    body = flag_dict(flag)
    assert body["title"] == "House spelling"
    trinity = make_flag("style.trinity", "trinity", "caps", location="LW slide 3", slide=3, deck="lw")
    assert trinity is not None
    assert flag_dict(trinity)["title"] == "Trinity Word Style"


def test_rule_title_uses_yaml_and_fallback(monkeypatch):
    from obed_edom import validate

    monkeypatch.setattr(
        validate,
        "load_rules",
        lambda: {"titles": {"style.trinity": "Trinity Word Style", "text.major": "Wording differs."}},
    )
    assert validate.rule_title("style.trinity") == "Trinity Word Style"
    assert validate.rule_title("text.major") == "Wording differs."
    assert validate.rule_title("bible.wrong_reference") == "Bible Wrong Reference"


def test_inspect_trinity_names_a_slide():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slides": [
            {"number": 3, "items": [{"kind": "text", "text": "we love god forever"}]},
        ],
    }
    flags = validate_inspect(
        payload, location_prefix="LW", deck="lw", use_ocr=False, check_passages=False
    )
    trinity = [f for f in flags if f.rule == "style.trinity"]
    assert trinity
    assert trinity[0].slide == 3
    assert trinity[0].location == "LW slide 3"


def test_inspect_date_names_a_slide():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slides": [
            {"number": 4, "items": [{"kind": "text", "text": "Lived 1980-2012."}]},
        ],
    }
    flags = validate_inspect(
        payload, location_prefix="DSK", deck="dsk", use_ocr=False, check_passages=False
    )
    dates = [f for f in flags if f.rule == "style.date"]
    assert dates
    assert dates[0].slide == 4
    assert dates[0].location == "DSK slide 4"
    assert dates[0].deck == "dsk"


def test_missing_previews_are_info_not_warning():
    from obed_edom.contrast import check_contrast

    flags, overlays = check_contrast([], Path("/tmp/no-such-previews"), "lw")
    assert overlays == []
    assert flags
    assert all(f.severity == "info" for f in flags)
    assert all(f.category == "contrast" for f in flags)


def test_same_type_diff_count_is_info_missing_is_warning(tmp_path):
    from obed_edom.diff_keynotes import compare_inspects

    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 2,
        "slides": [
            {"number": 1, "items": [{"text": "a"}]},
            {"number": 2, "items": [{"text": "b"}]},
        ],
    }
    right = {
        "path": str(tmp_path / "Copy_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "items": [{"text": "a"}]}],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="LW")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any(f.severity == "info" and "Slide count differs" in f.message for f in diffs)
    assert any(f.severity == "warning" and "Missing" in f.message for f in diffs)
    assert not any(f.severity == "error" and f.category == "diff" for f in result["flags"])


def test_mixed_type_diff_skips_count_and_missing(tmp_path):
    from obed_edom.diff_keynotes import compare_inspects

    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 2,
        "slides": [
            {"number": 1, "items": [{"text": "hello"}]},
            {"number": 2, "items": [{"text": "extra"}]},
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "items": [{"text": "hello"}]}],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="Other"
    )
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert not any("Slide count differs" in f.message for f in diffs)
    assert not any("Missing" in f.message for f in diffs)

