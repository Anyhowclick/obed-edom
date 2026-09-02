"""Tests for the offline mode-aware text-geometry shaper (obed_edom.iwa_text_shape).

The mode dispatch, the flags==1 vertical-anchor fix and the font-missing guard are
exercised on synthetic IWA archive dicts (no keynote-parser, no Keynote). The AppKit
text engine is a real dependency of the shaping paths, so tests that actually shape
are skipped when the ``AppKit`` pyobjc bridge is not importable (e.g. off macOS);
the frame-mode and no-style paths need no AppKit and always run.

geometry.flags: 0x1 width fixed, 0x2 height fixed. flags==1 is top-anchored
(x,y=frame; w=naturalSize.width; h=shaped). flags==0 is centre-anchored
(x,y = anchor − size/2) and is gated autowidth-soft. Height = layout*m + b*size;
wrap at width − 2*TEXT_INSET. Do not set paragraph indents on NSParagraphStyle —
wrap-width arithmetic already subtracts them.

ArgentCF is SINGLE_LINE_ONLY (slope under-determined). Mixed-run boxes are
approximated from the leading run (accepted residual). Wiring: a vouched box's
geom_source must sit outside offline_inspect.SOFT_GEOM_SOURCES; an unvouched box
must never be autosize-soft.
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
             font="AzoSans-Regular", size=70.0, text="Hi", amount=0.8, mode=None,
             bold=False, italic=False, left_indent=0.0, right_indent=0.0):
    char_props = {"fontName": font, "fontSize": size}
    if bold:
        char_props["bold"] = True
    if italic:
        char_props["italic"] = True
    objects[f"{ident}-c"] = {"_pbtype": "TSWP.CharacterStyleArchive",
                             "charProperties": char_props}
    line_spacing = {"amount": amount}
    if mode is not None:
        line_spacing["mode"] = mode
    para_props = {"lineSpacing": line_spacing, "alignment": "TATvalue2"}
    if left_indent:
        para_props["leftIndent"] = left_indent
    if right_indent:
        para_props["rightIndent"] = right_indent
    objects[f"{ident}-p"] = {"_pbtype": "TSWP.ParagraphStyleArchive",
                             "paraProperties": para_props}
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
def test_calibrated_installed_font_is_vouched():
    # AzoSans is installed on the calibration host AND in HEIGHT_MODEL -> vouched.
    objects: dict = {}
    rec = _textbox(objects, "ok", flags=1, x=0.0, y=0.0, nw=300.0,
                   font="AzoSans-Regular", text=_WRAP)
    assert compose_text_geometry(rec, objects, {}).reason is None


# --------------------------------------------------------------------------
# Gate B1 — an installed-but-UNCALIBRATED font (no HEIGHT_MODEL entry) gates.
# --------------------------------------------------------------------------
@needs_appkit
def test_installed_uncalibrated_font_gates():
    # Helvetica is installed (so NOT font-missing) but absent from HEIGHT_MODEL.
    objects: dict = {}
    rec = _textbox(objects, "unc", flags=1, x=0.0, y=0.0, nw=300.0,
                   font="Helvetica", text=_WRAP)
    tg = compose_text_geometry(rec, objects, {})
    assert tg.reason == "uncalibrated-font"
    assert tg.w == 300.0 and tg.h > 0.0  # still emits best-effort geometry


# --------------------------------------------------------------------------
# Gate B3 — a flags==0 (auto-width) box is always gated autowidth-soft.
# --------------------------------------------------------------------------
@needs_appkit
def test_flags0_is_gated_autowidth_soft():
    objects: dict = {}
    rec = _textbox(objects, "aw", flags=0, x=1000.0, y=500.0, font="AzoSans-Regular",
                   text="Centered")
    assert compose_text_geometry(rec, objects, {}).reason == "autowidth-soft"


# --------------------------------------------------------------------------
# Gate B4 — a non-relative lineSpacing.mode gates (defensive; 0 occur on GW/DSK).
# --------------------------------------------------------------------------
@needs_appkit
def test_linespacing_mode_gates():
    objects: dict = {}
    rec = _textbox(objects, "ls", flags=1, x=0.0, y=0.0, nw=300.0,
                   font="AzoSans-Regular", text=_WRAP, mode=1)
    assert compose_text_geometry(rec, objects, {}).reason == "linespacing-mode"


# --------------------------------------------------------------------------
# Gate B2 — an ArgentCF (single-line-only calibrated) MULTI-line box gates;
# a single-line ArgentCF box still vouches.
# --------------------------------------------------------------------------
@needs_appkit
def test_argentcf_multiline_gates_but_singleline_vouches():
    objects: dict = {}
    multi = _textbox(objects, "am", flags=1, x=0.0, y=0.0, nw=200.0,
                     font="ArgentCF-Regular", text=_WRAP)  # narrow -> wraps
    assert compose_text_geometry(multi, objects, {}).reason == "uncalibrated-multiline"
    single = _textbox(objects, "as", flags=1, x=0.0, y=0.0, nw=4000.0,
                      font="ArgentCF-Regular", text="Short line")  # wide -> one line
    assert compose_text_geometry(single, {**objects}, {}).reason is None


# --------------------------------------------------------------------------
# Gap D — a left/right indent narrows the wrap width, so the box shapes TALLER.
# --------------------------------------------------------------------------
@needs_appkit
def test_indent_increases_shaped_height():
    objects: dict = {}
    plain = _textbox(objects, "ip", flags=1, x=0.0, y=0.0, nw=600.0,
                     font="AzoSans-Regular", text=_WRAP)
    indented = _textbox(objects, "ii", flags=1, x=0.0, y=0.0, nw=600.0,
                        font="AzoSans-Regular", text=_WRAP,
                        left_indent=120.0, right_indent=120.0)
    hp = compose_text_geometry(plain, {**objects}, {}).h
    hi = compose_text_geometry(indented, {**objects}, {}).h
    assert hi > hp  # narrower wrap -> more lines -> taller


# --------------------------------------------------------------------------
# Gap C — bold/italic traits: applied when the font has the face, verified.
# --------------------------------------------------------------------------
@needs_appkit
def test_bold_trait_applied_when_face_exists():
    from AppKit import NSBoldFontMask, NSFontManager

    from obed_edom.iwa_text_shape import _ns_font

    # Helvetica has a real bold face; the request is satisfiable (trait_bad False)
    # and the returned font actually carries the bold trait.
    font, missing, trait_bad = _ns_font("Helvetica", 40.0, bold=True, italic=False)
    assert missing is False and trait_bad is False
    assert NSFontManager.sharedFontManager().traitsOfFont_(font) & NSBoldFontMask
    # Requesting bold on an already-bold face applies nothing (idempotent, family kept).
    font2, _m, trait_bad2 = _ns_font("Helvetica-Bold", 40.0, bold=True, italic=False)
    assert trait_bad2 is False
    assert font2.familyName() == "Helvetica"


@needs_appkit
def test_trait_unsatisfiable_gates(monkeypatch):
    # An unsynthesizable bold/italic (AppKit would change family / drop the trait) is
    # rare with real fonts, so force `_ns_font` to report trait_bad and assert the gate
    # maps it to `trait-unsatisfiable`. Uses a calibrated+installed family so the earlier
    # font-missing / uncalibrated-font gates do not pre-empt this branch.
    import obed_edom.iwa_text_shape as mod

    def fake_ns_font(font_name, size, bold=False, italic=False):
        from AppKit import NSFont  # noqa: PLC0415
        f = NSFont.fontWithName_size_(font_name, size) or NSFont.systemFontOfSize_(size)
        return (f, False, True)  # installed (not missing), but trait unsatisfiable

    monkeypatch.setattr(mod, "_ns_font", fake_ns_font)
    objects: dict = {}
    rec = _textbox(objects, "tb", flags=1, x=0.0, y=0.0, nw=300.0,
                   font="AzoSans-Regular", text=_WRAP, bold=True)
    assert compose_text_geometry(rec, objects, {}).reason == "trait-unsatisfiable"


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
