"""Tests for the offline mode-aware text-geometry shaper (obed_edom.iwa_text_shape).

The mode dispatch, the flags==1 vertical-anchor fix and the font-missing guard are
exercised on synthetic IWA archive dicts (no keynote-parser, no Keynote). The AppKit
text engine is a real dependency of the shaping paths, so tests that actually shape
are skipped when the ``AppKit`` pyobjc bridge is not importable (e.g. off macOS);
the frame-mode and no-style paths need no AppKit and always run.
"""
from __future__ import annotations

import pytest

from obed_edom.iwa_text_shape import (
    ShapeStyle,
    compose_text_geometry,
    geometry_flags,
    height_fixed,
    shape_style,
    width_fixed,
)

_HAS_APPKIT = True
try:  # the shaping paths need the installed pyobjc AppKit bridge
    import AppKit  # noqa: F401
except Exception:  # noqa: BLE001
    _HAS_APPKIT = False

needs_appkit = pytest.mark.skipif(not _HAS_APPKIT, reason="pyobjc AppKit not installed")

# A long line so the flags==1 wrap produces more than one line (real shaping).
_WRAP = "Hello world this is a long enough line to wrap inside a fixed width box here"


# --------------------------------------------------------------------------
# Synthetic text-box builder (geometry at super.super.geometry, storage owned).
# --------------------------------------------------------------------------
def _geom(x, y, w, h, flags, angle=0.0):
    return {"position": {"x": x, "y": y}, "size": {"width": w, "height": h},
            "flags": flags, "angle": angle}


def _textbox(objects, ident, *, flags, x=0.0, y=0.0, w=0.0, h=0.0, nw=0.0, nh=0.0,
             font="AzoSans-Regular", size=70.0, text="Hi", amount=0.8):
    objects[f"{ident}-c"] = {"_pbtype": "TSWP.CharacterStyleArchive",
                             "charProperties": {"fontName": font, "fontSize": size}}
    objects[f"{ident}-p"] = {"_pbtype": "TSWP.ParagraphStyleArchive",
                             "paraProperties": {"lineSpacing": {"amount": amount},
                                                "alignment": "TATvalue2"}}
    objects[f"{ident}-st"] = {
        "_pbtype": "TSWP.StorageArchive", "text": [text],
        "tableCharStyle": {"entries": [{"characterIndex": 0,
                                        "object": {"identifier": f"{ident}-c"}}]},
        "tableParaStyle": {"entries": [{"characterIndex": 0,
                                        "object": {"identifier": f"{ident}-p"}}]},
    }
    objects[ident] = {
        "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
        "ownedStorage": {"identifier": f"{ident}-st"},
        "super": {"pathsource": {"bezierPathSource": {"naturalSize": {"width": nw, "height": nh}}},
                  "super": {"geometry": _geom(x, y, w, h, flags)}},
    }
    return {"id": ident, "kind": "text", "kindIndex": 0, "text": text}


# --------------------------------------------------------------------------
# flags bit meaning (empirically 0x1 = width fixed, 0x2 = height fixed).
# --------------------------------------------------------------------------
def test_flag_bit_helpers():
    assert (width_fixed(0), height_fixed(0)) == (False, False)
    assert (width_fixed(1), height_fixed(1)) == (True, False)
    assert (width_fixed(3), height_fixed(3)) == (True, True)
    assert geometry_flags({"flags": 3}) == 3
    assert geometry_flags({}) == 0


# --------------------------------------------------------------------------
# Mode dispatch — flags==3 is the frame, EXACT, no shaping (so no AppKit needed).
# --------------------------------------------------------------------------
def test_flags3_uses_frame_exact_no_shaping():
    objects: dict = {}
    rec = _textbox(objects, "t3", flags=3, x=100.0, y=50.0, w=200.0, h=120.0, nw=200.0, nh=120.0)
    tg = compose_text_geometry(rec, objects, {})
    assert (tg.x, tg.y, tg.w, tg.h) == (100.0, 50.0, 200.0, 120.0)
    assert tg.geom_source == "frame"
    assert tg.reason is None  # frame path is font-independent, always vouched


def test_flags2_height_fixed_also_uses_frame():
    # bit1 set (height authored) -> frame rule regardless of the width bit.
    objects: dict = {}
    rec = _textbox(objects, "t2", flags=2, x=10.0, y=20.0, w=300.0, h=80.0, nw=300.0, nh=80.0)
    tg = compose_text_geometry(rec, objects, {})
    assert (tg.x, tg.y, tg.w, tg.h) == (10.0, 20.0, 300.0, 80.0)
    assert tg.geom_source == "frame"


# --------------------------------------------------------------------------
# flags==1 — fixed width + auto height. The anchor FIX: y = top (not y - h/2).
# --------------------------------------------------------------------------
@needs_appkit
def test_flags1_anchor_is_top_and_width_is_natural():
    objects: dict = {}
    rec = _textbox(objects, "t1", flags=1, x=100.0, y=50.0, nw=300.0, text=_WRAP)
    tg = compose_text_geometry(rec, objects, {})
    assert tg.x == 100.0            # left is the frame x, exact
    assert tg.y == 50.0            # TOP — the fix (not y - h/2)
    assert tg.w == 300.0           # naturalSize.width, exact
    assert tg.h > 0.0              # shaped height
    assert tg.geom_source == "shaped-height"
    assert tg.reason is None       # AzoSans is installed on the calibration host


@needs_appkit
def test_flags1_wraps_more_than_one_line():
    # A narrow box forces the long text to wrap, so shaped height exceeds one line.
    objects: dict = {}
    narrow = _textbox(objects, "narrow", flags=1, x=0.0, y=0.0, nw=200.0, text=_WRAP)
    wide = _textbox(objects, "wide", flags=1, x=0.0, y=0.0, nw=2000.0, text=_WRAP)
    hn = compose_text_geometry(narrow, {**objects}, {}).h
    hw = compose_text_geometry(wide, {**objects}, {}).h
    assert hn > hw  # narrower box -> more wrapped lines -> taller


# --------------------------------------------------------------------------
# flags==0 — auto width + auto height, CENTRE anchor.
# --------------------------------------------------------------------------
@needs_appkit
def test_flags0_centre_anchor():
    objects: dict = {}
    rec = _textbox(objects, "t0", flags=0, x=1000.0, y=500.0, text="Centered")
    tg = compose_text_geometry(rec, objects, {})
    assert tg.w > 0.0 and tg.h > 0.0
    # position is the centre anchor: x = anchor - w/2, y = anchor - h/2.
    assert tg.x == pytest.approx(1000.0 - tg.w / 2.0)
    assert tg.y == pytest.approx(500.0 - tg.h / 2.0)
    assert tg.geom_source == "shaped-both"


# --------------------------------------------------------------------------
# Font-missing guard — the top accuracy risk.
# --------------------------------------------------------------------------
@needs_appkit
def test_font_missing_marks_unvouched():
    objects: dict = {}
    rec = _textbox(objects, "tm", flags=1, x=0.0, y=0.0, nw=300.0,
                   font="NoSuchFontFamily-XYZ", text=_WRAP)
    tg = compose_text_geometry(rec, objects, {})
    assert tg.reason == "font-missing"  # substitute-font metrics -> not trusted
    assert tg.w == 300.0 and tg.h > 0.0  # still emits best-effort geometry


@needs_appkit
def test_installed_font_is_vouched():
    objects: dict = {}
    rec = _textbox(objects, "ok", flags=1, x=0.0, y=0.0, nw=300.0,
                   font="Helvetica", text=_WRAP)
    assert compose_text_geometry(rec, objects, {}).reason is None


# --------------------------------------------------------------------------
# No resolvable style -> best-effort naturalSize + unvouched, per mode anchor.
# --------------------------------------------------------------------------
def test_no_style_falls_back_and_flags():
    objects = {"bare": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
                        "super": {"pathsource": {"bezierPathSource":
                                  {"naturalSize": {"width": 300.0, "height": 88.0}}},
                                  "super": {"geometry": _geom(100.0, 50.0, 0.0, 0.0, 1)}}}}
    rec = {"id": "bare", "kind": "text", "kindIndex": 0, "text": "x"}
    tg = compose_text_geometry(rec, objects, {})
    assert tg.reason == "font-missing"          # cannot shape -> unvouched
    assert (tg.x, tg.y, tg.w, tg.h) == (100.0, 50.0, 300.0, 88.0)  # flags==1 top anchor


def test_shape_style_from_box():
    objects: dict = {}
    rec = _textbox(objects, "s", flags=1, nw=300.0, font="ArgentCF-RegularItalic",
                   size=96.0, amount=0.7)
    st = shape_style(objects[rec["id"]], objects, {})
    assert isinstance(st, ShapeStyle)
    assert st.font_name == "ArgentCF-RegularItalic"
    assert st.size == 96.0
    assert st.line_multiple == 0.7
    assert st.alignment == "TATvalue2"
