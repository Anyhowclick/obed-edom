from pathlib import Path

from sermon_slides.parse_outline import parse_outline
from sermon_slides.slide_map import map_slides
from sermon_slides.validate import validate_inspect, validate_slide_specs, validate_style_text

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

