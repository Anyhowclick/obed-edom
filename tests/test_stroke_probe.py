"""Offline stroke-width probe tests (scripts.probe_stroke_patch). No Keynote.

Two-member synthetic deck (builders reused from ``test_iwa_write``):
Index/DocumentStylesheet.iwa carries two MediaStyleArchives — 900 (0.25 white
solid, referenced 4x, one nested in a group) and 901 (1.0 black solid, 1 ref).
Index/Document.iwa + Index/Slide-100.iwa carry the slide/show scaffold and the
image drawables.
"""
from __future__ import annotations

import io
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_runs import _load_deck  # noqa: E402
from test_iwa_write import _arch, _geom, _member  # noqa: E402

from scripts.probe_stroke_patch import (  # noqa: E402
    border_run,
    card_styles,
    patch_stroke_widths,
    select_card_styles,
    stroke_probe_applescript,
)
from scripts.write_gate_ab import changed_members  # noqa: E402

_WHITE_SOLID_STROKE = {
    "width": 0.25,
    "color": {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"},
    "pattern": {"type": "TSDSolidPattern"},
}
_BLACK_SOLID_STROKE = {
    "width": 1.0,
    "color": {"model": "rgb", "r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0, "rgbspace": "srgb"},
    "pattern": {"type": "TSDSolidPattern"},
}
_WHITE_EMPTY_STROKE = {
    "width": 2.0,
    "color": {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"},
    "pattern": {"type": "TSDEmptyPattern"},
}


def _build_deck(path, *, extra_stylesheet_archives=(), extra_slide_archives=(), extra_zorder=()):
    """Two-member deck: 4 images with style 900 (one nested in a group), 1 with 901."""
    stylesheet = [
        _arch(900, "TSD.MediaStyleArchive", {
            "super": {"styleIdentifier": "image-0-imageStyle"},
            "mediaProperties": {"stroke": _WHITE_SOLID_STROKE},
        }),
        _arch(901, "TSD.MediaStyleArchive", {
            "super": {"styleIdentifier": "image-1-imageStyle"},
            "mediaProperties": {"stroke": _BLACK_SOLID_STROKE},
        }),
        *extra_stylesheet_archives,
    ]

    slide_member = [
        _arch(300, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(0, 0, 50, 50)}),
        _arch(301, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(60, 0, 50, 50)}),
        _arch(302, "TSD.ImageArchive", {"style": {"identifier": 901}, "super": _geom(120, 0, 50, 50)}),
        _arch(303, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(0, 0, 50, 50)}),
        _arch(250, "TSD.GroupArchive", {"super": _geom(500, 500, 0, 0), "children": [{"identifier": 303}]}),
        _arch(304, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(180, 0, 50, 50)}),
        *extra_slide_archives,
    ]
    zorder = [300, 301, 302, 250, 304, *extra_zorder]
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": i} for i in zorder]})
    show = _arch(2, "KN.ShowArchive", {
        "slideTree": {"slides": [{"identifier": 10}]},
        "size": {"width": 1920.0, "height": 1080.0},
    })
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/DocumentStylesheet.iwa", _member(stylesheet))
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member(slide_member + [slide]))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "stroke.key")


def test_card_styles_reports_both_styles(deck):
    objects, id_to_file, _file_ids = _load_deck(deck)
    styles = {s["id"]: s for s in card_styles(objects, id_to_file)}

    assert set(styles) == {"900", "901"}
    for style_id in ("900", "901"):
        assert styles[style_id]["member"] == "Index/DocumentStylesheet.iwa"
        assert styles[style_id]["slides"] == [1]
        assert styles[style_id]["pattern"] == "TSDSolidPattern"
        assert styles[style_id]["inherited"] is False

    assert styles["900"]["width"] == pytest.approx(0.25)
    assert styles["900"]["refs"] == 4
    r, g, b, a = styles["900"]["color"]
    assert (r, g, b, a) == pytest.approx((1.0, 1.0, 1.0, 1.0))

    assert styles["901"]["width"] == pytest.approx(1.0)
    assert styles["901"]["refs"] == 1
    r, g, b, a = styles["901"]["color"]
    assert (r, g, b, a) == pytest.approx((0.0, 0.0, 0.0, 1.0))


def test_card_styles_inherits_stroke_from_parent(tmp_path):
    child = _arch(902, "TSD.MediaStyleArchive", {
        "super": {"styleIdentifier": "image-2-imageStyle", "parent": {"identifier": 900}},
    })
    image = _arch(310, "TSD.ImageArchive", {"style": {"identifier": 902}, "super": _geom(200, 0, 50, 50)})
    deck = _build_deck(
        tmp_path / "inherit.key",
        extra_stylesheet_archives=(child,),
        extra_slide_archives=(image,),
        extra_zorder=(310,),
    )

    objects, id_to_file, _file_ids = _load_deck(deck)
    styles = {s["id"]: s for s in card_styles(objects, id_to_file)}
    assert styles["902"]["width"] == pytest.approx(0.25)
    assert styles["902"]["pattern"] == "TSDSolidPattern"
    r, g, b, _a = styles["902"]["color"]
    assert (r, g, b) == pytest.approx((1.0, 1.0, 1.0))
    assert styles["902"]["inherited"] is True


def test_select_card_styles_picks_only_white_solid_above_min_refs(tmp_path):
    empty = _arch(903, "TSD.MediaStyleArchive", {
        "super": {"styleIdentifier": "image-3-imageStyle"},
        "mediaProperties": {"stroke": _WHITE_EMPTY_STROKE},
    })
    images = (
        _arch(320, "TSD.ImageArchive", {"style": {"identifier": 903}, "super": _geom(0, 0, 50, 50)}),
        _arch(321, "TSD.ImageArchive", {"style": {"identifier": 903}, "super": _geom(60, 0, 50, 50)}),
    )
    deck = _build_deck(
        tmp_path / "select.key",
        extra_stylesheet_archives=(empty,),
        extra_slide_archives=images,
        extra_zorder=(320, 321),
    )
    objects, id_to_file, _file_ids = _load_deck(deck)
    styles = card_styles(objects, id_to_file)

    # 900: white solid, 4 refs; 901: black solid, 1 ref; 903: white but EMPTY pattern, 2 refs.
    picked = select_card_styles(styles, min_refs=2)
    assert [s["id"] for s in picked] == ["900"]  # 903 rejected despite white + refs>=2

    assert select_card_styles(styles, min_refs=10) == []


def test_patch_stroke_widths_is_value_clean_and_reads_back(deck):
    result = patch_stroke_widths(deck, {"900": 3.0})
    assert not result["refused"]
    assert result["value_clean"]
    assert result["obj_diffs"] == 1
    assert result["header_diffs"] == 0

    objects, id_to_file, _file_ids = _load_deck(deck)
    styles = {s["id"]: s for s in card_styles(objects, id_to_file)}
    assert styles["900"]["width"] == pytest.approx(3.0)
    assert styles["901"]["width"] == pytest.approx(1.0)


def test_patch_touches_only_the_stylesheet_member(deck, tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(deck.read_bytes())
    inode_before = deck.stat().st_ino

    result = patch_stroke_widths(deck, {"900": 3.0})
    assert not result["refused"]

    assert changed_members(original, deck) == {"Index/DocumentStylesheet.iwa"}
    assert deck.stat().st_ino == inode_before  # in-place O_TRUNC, never a new file


def test_patch_refuses_unknown_style_id(deck):
    before = deck.read_bytes()
    result = patch_stroke_widths(deck, {"999999": 3.0})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_stroke_widths_normalises_int_keys(deck):
    result = patch_stroke_widths(deck, {900: 3.0})
    assert not result["refused"]
    assert result["value_clean"]

    objects, id_to_file, _file_ids = _load_deck(deck)
    styles = {s["id"]: s for s in card_styles(objects, id_to_file)}
    assert styles["900"]["width"] == pytest.approx(3.0)


def test_patch_refuses_style_id_from_a_different_member(tmp_path):
    rogue = _arch(950, "TSD.MediaStyleArchive", {
        "super": {"styleIdentifier": "rogue-style"},
        "mediaProperties": {"stroke": _WHITE_SOLID_STROKE},
    })
    deck = _build_deck(tmp_path / "wrongmember.key", extra_slide_archives=(rogue,))
    before = deck.read_bytes()

    result = patch_stroke_widths(deck, {"950": 3.0})
    assert result["refused"]
    assert "Index/Slide-100.iwa" in result["reason"]
    assert deck.read_bytes() == before


def test_border_run_counts_near_white_pixels(tmp_path):
    from PIL import Image

    px_per_pt = 1.0
    frame = (10.0, 10.0, 40.0, 30.0)  # x0, y0, x1, y1
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    px = img.load()
    row = int(((frame[1] + frame[3]) / 2.0) * px_per_pt)
    start_x = int(frame[0] * px_per_pt) - 6
    for i in range(3):
        px[start_x + i, row] = (255, 255, 255)
    white_png = tmp_path / "white.png"
    img.save(white_png)
    assert border_run(white_png, frame, px_per_pt) == 3

    black_png = tmp_path / "black.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(black_png)
    assert border_run(black_png, frame, px_per_pt) == 0


def test_stroke_probe_applescript_blocks_balanced_and_save_gated(tmp_path):
    for save in (False, True):
        script = stroke_probe_applescript(
            tmp_path / "deck.key", tmp_path / "out", doc_name="deck_stroke", save=save
        )
        lines = [line.strip() for line in script.split("\n")]
        assert lines.count("with timeout of 3600 seconds") == lines.count("end timeout")
        assert sum(line.startswith("tell application id") for line in lines) == lines.count("end tell")
        assert (sum(line.startswith("using terms from application id") for line in lines)
                == lines.count("end using terms from"))
        assert ("save theDoc" in lines) == save
        assert ("close theDoc saving yes" in lines) == save
