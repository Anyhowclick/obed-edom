"""Offline tests for ``iwa_write.patch_media_stroke`` (no Keynote).

Reuses the ``_build_deck`` synthetic stylesheet fixture from
``test_stroke_probe`` (styles 900/901 in ``Index/DocumentStylesheet.iwa``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_runs import _load_deck  # noqa: E402
from obed_edom.iwa_write import patch_media_stroke  # noqa: E402
from scripts.write_gate_ab import changed_members  # noqa: E402
from test_iwa_write import _arch, _member  # noqa: E402
from test_stroke_probe import _build_deck  # noqa: E402


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "stroke.key")


def test_overwrites_existing_stroke(deck, tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(deck.read_bytes())

    result = patch_media_stroke(deck, {"900": {"width": 3.5, "color": (0.2, 0.4, 0.6, 1.0)}})
    assert not result["refused"]
    assert result["patched"] == ["900"]
    assert result["created"] == []
    assert result["value_clean"]

    objects, id_to_file, _fi = _load_deck(deck)
    stroke = objects["900"]["mediaProperties"]["stroke"]
    assert stroke["width"] == pytest.approx(3.5)
    color = stroke["color"]
    assert (color["r"], color["g"], color["b"], color["a"]) == pytest.approx((0.2, 0.4, 0.6, 1.0))
    assert stroke["pattern"]["type"] == "TSDSolidPattern"

    other = objects["901"]["mediaProperties"]["stroke"]
    assert other["width"] == pytest.approx(1.0)
    assert (other["color"]["r"], other["color"]["g"], other["color"]["b"]) == pytest.approx((0.0, 0.0, 0.0))

    assert changed_members(original, deck) == {"Index/DocumentStylesheet.iwa"}


def test_creates_stroke_where_absent(tmp_path):
    bare = _arch(902, "TSD.MediaStyleArchive", {"super": {"styleIdentifier": "image-2-imageStyle"}})
    deck = _build_deck(tmp_path / "bare.key", extra_stylesheet_archives=(bare,))

    result = patch_media_stroke(deck, {"902": {"width": 2.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert not result["refused"]
    assert result["created"] == ["902"]
    assert result["patched"] == ["902"]

    objects, id_to_file, _fi = _load_deck(deck)
    stroke = objects["902"]["mediaProperties"]["stroke"]
    assert stroke == {
        "color": {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"},
        "width": 2.0,
        "cap": "ButtCap",
        "join": "MiterJoin",
        "miterLimit": 4.0,
        "pattern": {
            "type": "TSDSolidPattern",
            "phase": 0.0,
            "count": 0,
            "pattern": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
    }


def test_refuses_unknown_style_id(deck):
    before = deck.read_bytes()
    result = patch_media_stroke(deck, {"999999": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_refuses_wrong_archive_type(tmp_path):
    bogus = _arch(950, "TSD.ImageArchive", {"super": {"geometry": {"position": {"x": 0, "y": 0},
                                                                     "size": {"width": 1, "height": 1}, "angle": 0.0}}})
    deck = _build_deck(tmp_path / "wrongtype.key", extra_slide_archives=(bogus,))
    before = deck.read_bytes()

    result = patch_media_stroke(deck, {"950": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]
    assert "TSD.MediaStyleArchive" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_style_id_from_a_different_member(tmp_path):
    rogue = _arch(950, "TSD.MediaStyleArchive", {"super": {"styleIdentifier": "rogue-style"}})
    deck = _build_deck(tmp_path / "wrongmember.key", extra_slide_archives=(rogue,))
    before = deck.read_bytes()

    result = patch_media_stroke(deck, {"950": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]
    assert "Index/Slide-100.iwa" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_stylesheet_member_missing(tmp_path):
    import io
    import zipfile

    show = _arch(2, "KN.ShowArchive", {
        "slideTree": {"slides": [{"identifier": 10}]},
        "size": {"width": 1920.0, "height": 1080.0},
    })
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": []})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node, slide]))
    path = tmp_path / "no_stylesheet.key"
    path.write_bytes(buf.getvalue())

    result = patch_media_stroke(path, {"900": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]


def test_only_stylesheet_member_changes(deck, tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(deck.read_bytes())
    inode_before = deck.stat().st_ino

    result = patch_media_stroke(deck, {"901": {"width": 7.0, "color": (0.1, 0.2, 0.3, 1.0)}})
    assert not result["refused"]

    assert changed_members(original, deck) == {"Index/DocumentStylesheet.iwa"}
    assert deck.stat().st_ino == inode_before


_DSK_SAMPLE = Path("~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key").expanduser()


@pytest.mark.skipif(not _DSK_SAMPLE.exists(), reason="real DSK sample not present")
def test_created_stroke_matches_real_sample_shape():
    objects, id_to_file, _fi = _load_deck(_DSK_SAMPLE)
    real = objects["15303898"]["mediaProperties"]["stroke"]

    from obed_edom.iwa_write import _stroke_submessage
    built = _stroke_submessage({"width": real["width"], "color": (
        real["color"]["r"], real["color"]["g"], real["color"]["b"], real["color"]["a"],
    )})
    assert set(built) == set(real)
    assert set(built["color"]) == set(real["color"])
    assert set(built["pattern"]) == set(real["pattern"])
    assert built["cap"] == real["cap"]
    assert built["join"] == real["join"]
    assert built["miterLimit"] == pytest.approx(real["miterLimit"])
    assert built["pattern"]["type"] == real["pattern"]["type"]
