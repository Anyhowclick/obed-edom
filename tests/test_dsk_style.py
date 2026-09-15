"""Offline tests for ``obed_edom.dsk_style.write_styles`` (no Keynote).

Synthetic ``Index/DocumentStylesheet.iwa`` built with ``test_iwa_write``'s ``_arch``/
``_member`` helpers: two verse-badge paragraph styles (40/60 pt, kAllCaps/cyan/
AzoSans-Bold), one point-column badge style (52.66 pt, same predicate but excluded
size), a plain kNoCaps paragraph style (must be skipped), and the named "SuperScript"
character style (the verse-number colour target).
"""
from __future__ import annotations

import copy
import io
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from keynote_parser.codec import IWAFile  # noqa: E402

from obed_edom.iwa_runs import _load_deck, resolve_style  # noqa: E402
from test_iwa_write import _arch, _member  # noqa: E402

from obed_edom.dsk_style import (  # noqa: E402
    CYAN,
    GOLD_YELLOW,
    OfflineWriteRefused,
    StyleSpec,
    WHITE,
    write_styles,
)

_CYAN_COLOR = {"model": "rgb", "r": CYAN[0], "g": CYAN[1], "b": CYAN[2], "a": 1.0, "rgbspace": "srgb"}
_WHITE_COLOR = {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"}


def _para(ident, *, font_size, capitalization="kAllCaps", font_name="AzoSans-Bold",
         color=None, tsd_fill=True, name=None):
    cp = {"fontName": font_name, "capitalization": capitalization, "fontSize": float(font_size)}
    if color is not None:
        cp["fontColor"] = dict(color)
        if tsd_fill:
            cp["tsdFill"] = {"color": dict(color)}
    obj = {"charProperties": cp}
    if name is not None:
        obj["super"] = {"name": name}
    return _arch(ident, "TSWP.ParagraphStyleArchive", obj)


def _charstyle_arch(ident, *, name, color=None, tsd_fill=True):
    cp = {}
    if color is not None:
        cp["fontColor"] = dict(color)
        if tsd_fill:
            cp["tsdFill"] = {"color": dict(color)}
    return _arch(ident, "TSWP.CharacterStyleArchive", {"charProperties": cp, "super": {"name": name}})


def _build_stylesheet(path, *, archives, extra_members=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/DocumentStylesheet.iwa", _member(list(archives)))
        for name, members in extra_members:
            z.writestr(name, _member(list(members)))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    archives = [
        _para("10", font_size=40.0, color=_CYAN_COLOR),  # verse badge
        _para("11", font_size=60.0, color=_CYAN_COLOR),  # verse badge
        _para("12", font_size=52.66, color=_CYAN_COLOR),  # point-column badge (excluded size)
        _para("13", font_size=45.0, capitalization="kNoCaps", color=_CYAN_COLOR),  # already kNoCaps: skipped
        _charstyle_arch("14", name="SuperScript", color=_CYAN_COLOR),
        _charstyle_arch("15", name="Yellow Bold", color={"model": "rgb", "r": 0.99942404, "g": 0.9855537,
                                                          "b": 0.0, "a": 1.0, "rgbspace": "srgb"}),
    ]
    return _build_stylesheet(tmp_path / "synth.key", archives=archives)


def test_verse_badges_whitened_and_kNoCaps(deck, tmp_path):
    out = tmp_path / "out.key"
    result = write_styles(deck, out_path=out)

    assert result.applied == 4  # 2 verse badges + 1 point-column + 1 superscript
    assert result.edited_ids["10"] == "verse_badge"
    assert result.edited_ids["11"] == "verse_badge"
    assert result.edited_ids["12"] == "point_column_badge"
    assert result.edited_ids["14"] == "superscript"
    assert result.members == ["Index/DocumentStylesheet.iwa"]

    objects, _id_to_file, _fi = _load_deck(out)
    cache = {}
    for sid in ("10", "11"):
        resolved = resolve_style(sid, objects, cache)
        assert resolved["color"] == [255, 255, 255]
        assert resolved["capitalization"] == "kNoCaps"


def test_point_column_badge_keeps_cyan_only_caps_cleared(deck, tmp_path):
    out = tmp_path / "out.key"
    write_styles(deck, out_path=out)
    objects, _id_to_file, _fi = _load_deck(out)
    resolved = resolve_style("12", objects, {})
    assert resolved["capitalization"] == "kNoCaps"
    assert resolved["color"] == [0, 253, 255]  # cyan, unchanged


def test_kNoCaps_style_untouched(deck, tmp_path):
    out = tmp_path / "out.key"
    write_styles(deck, out_path=out)
    objects, _id_to_file, _fi = _load_deck(out)
    resolved = resolve_style("13", objects, {})
    assert resolved["capitalization"] == "kNoCaps"
    assert resolved["color"] == [0, 253, 255]  # cyan, unchanged (never a badge candidate)


def test_superscript_recoloured_gold(deck, tmp_path):
    out = tmp_path / "out.key"
    write_styles(deck, out_path=out)
    objects, _id_to_file, _fi = _load_deck(out)
    resolved = resolve_style("14", objects, {})
    assert resolved["color"] == [round(c * 255) for c in GOLD_YELLOW]


def test_dual_field_write_pinned_literally(deck, tmp_path):
    out = tmp_path / "out.key"
    write_styles(deck, out_path=out)
    objects, _id_to_file, _fi = _load_deck(out)
    cp = objects["10"]["charProperties"]
    assert (cp["fontColor"]["r"], cp["fontColor"]["g"], cp["fontColor"]["b"]) == (1.0, 1.0, 1.0)
    assert (cp["tsdFill"]["color"]["r"], cp["tsdFill"]["color"]["g"], cp["tsdFill"]["color"]["b"]) == (1.0, 1.0, 1.0)


def test_other_archives_are_copied_verbatim(deck, tmp_path):
    out = tmp_path / "out.key"
    write_styles(deck, out_path=out)
    objects, _id_to_file, _fi = _load_deck(out)
    assert objects["15"]["super"]["name"] == "Yellow Bold"
    resolved = resolve_style("15", objects, {})
    assert resolved["color"] == [round(0.99942404 * 255), round(0.9855537 * 255), 0]


def test_member_isolation(deck, tmp_path):
    out = tmp_path / "out.key"
    write_styles(deck, out_path=out)
    with zipfile.ZipFile(deck) as zin, zipfile.ZipFile(out) as zout:
        assert zin.namelist() == zout.namelist()
        for name in zin.namelist():
            if name == "Index/DocumentStylesheet.iwa":
                assert zin.read(name) != zout.read(name)
            else:
                assert zin.read(name) == zout.read(name)


def test_refuses_when_zero_badge_styles_match(tmp_path):
    archives = [_charstyle_arch("14", name="SuperScript", color=_CYAN_COLOR)]
    deck = _build_stylesheet(tmp_path / "nomatch.key", archives=archives)
    before = deck.read_bytes()
    out = tmp_path / "out.key"
    with pytest.raises(OfflineWriteRefused, match="zero verse-badge styles"):
        write_styles(deck, out_path=out)
    assert deck.read_bytes() == before
    assert not out.exists()


def test_refuses_candidate_without_tsdFill(tmp_path):
    archives = [
        _para("10", font_size=40.0, color=_CYAN_COLOR, tsd_fill=False),
    ]
    deck = _build_stylesheet(tmp_path / "notsd.key", archives=archives)
    before = deck.read_bytes()
    out = tmp_path / "out.key"
    with pytest.raises(OfflineWriteRefused, match="tsdFill"):
        write_styles(deck, out_path=out)
    assert deck.read_bytes() == before
    assert not out.exists()


def test_refuses_undecodable_stylesheet_member(tmp_path):
    deck = tmp_path / "bad.key"
    with zipfile.ZipFile(deck, "w") as z:
        z.writestr("Index/DocumentStylesheet.iwa", b"not an iwa file")
    out = tmp_path / "out.key"
    with pytest.raises(OfflineWriteRefused, match="undecodable"):
        write_styles(deck, out_path=out)
    assert not out.exists()


_R13_DECK = Path("~/Desktop/dsk-d4-work/out-r13/Sermon_PK_DSK.refused.key").expanduser()
_R13_TMP_DIR = Path("~/Desktop/dsk-d4-work/tmp-style").expanduser()


@pytest.mark.skipif(not _R13_DECK.exists(), reason="r13 deck not present on this machine")
def test_r13_deck_role_table_matches_gold_after_patch():
    """Plan section 1.4/§5: patch a copy of the r13 deck (Keynote-openable scratch
    location, deleted after) and check the resolved run table for ordinal 4
    (Genesis 11) and its verse number matches the gold columns of section 1.1 --
    white kNoCaps badge, gold-yellow superscript verse number -- while a
    point-column badge elsewhere in the deck (if present) keeps cyan.
    """
    from obed_edom.iwa_runs import slide_order, storage_runs
    from obed_edom.offline_inspect import _storage_of

    _R13_TMP_DIR.mkdir(parents=True, exist_ok=True)
    patched = _R13_TMP_DIR / "style_patch_test.key"
    try:
        result = write_styles(_R13_DECK, out_path=patched)
        assert result.applied > 0

        objects, _id_to_file, _fi = _load_deck(patched)
        order = slide_order(objects)
        slide_id, _skipped = order[3]  # ordinal 4
        slide = objects[slide_id]
        cache: dict = {}
        found_badge = False
        found_superscript = False
        for ref in slide.get("drawablesZOrder") or []:
            obj = objects.get(str(ref.get("identifier")))
            if not obj or obj.get("_pbtype") != "TSWP.ShapeInfoArchive":
                continue
            storage = _storage_of(obj, objects)
            if storage is None:
                continue
            for run in storage_runs(storage, objects, cache):
                if run["text"].strip() == "Genesis 11":
                    assert run["color"] == [255, 255, 255]
                    assert run["capitalization"] == "kNoCaps"
                    found_badge = True
                if run.get("superscript") == "kSuperscript" and run["color"] is not None:
                    assert run["color"] == [round(c * 255) for c in GOLD_YELLOW]
                    found_superscript = True
        assert found_badge, "ordinal 4 badge run 'Genesis 11' not found post-patch"
        assert found_superscript, "ordinal 4 superscript verse-number run not found post-patch"
    finally:
        patched.unlink(missing_ok=True)


def test_custom_spec_overrides_defaults(deck, tmp_path):
    out = tmp_path / "out.key"
    spec = StyleSpec(badge_color=(0.5, 0.5, 0.5), badge_caps="kNoCaps", verse_number_color=(1.0, 0.0, 0.0))
    write_styles(deck, out_path=out, spec=spec)
    objects, _id_to_file, _fi = _load_deck(out)
    resolved = resolve_style("10", objects, {})
    assert resolved["color"] == [128, 128, 128]
    resolved_ss = resolve_style("14", objects, {})
    assert resolved_ss["color"] == [255, 0, 0]
