"""Tests for offline (kind, kindIndex) reconstruction (obed_edom.iwa_kindindex).

The classification / ordering / guard logic is pure and exercised WITHOUT keynote-parser
by building synthetic IWA drawable dicts. A local-only integration test reproduces the
addressing on a real deck and diffs it against that deck's cached exact-bytes JXA payload
when the deck, the parser, and the cached payload are all present.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from obed_edom.iwa_kindindex import (
    _is_line,
    derive_deck_kind_index,
    derive_kind_index,
    derived_kind_counts,
    reconcile_counts,
)

MAP_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Map_Extracted_Wall_1st.key")
FULL_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key")


# --------------------------------------------------------------------------
# Synthetic IWA drawable builders.
# --------------------------------------------------------------------------
def _shape(objects, ident, *, x=0.0, y=0.0, w=10.0, h=10.0, is_textbox=False,
           text="", line=False, custom=False):
    """A TSWP.ShapeInfoArchive with geometry at super.super.geometry, registered in objects."""
    if line:
        bez = {"naturalSize": {"width": w, "height": 0.0},
               "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}]}}
        pathsource = {"bezierPathSource": bez}
    elif custom:
        pathsource = {"editableBezierPathSource": {"path": {"elements": [{"type": "moveTo"}]}}}
    else:  # default rectangle
        bez = {"naturalSize": {"width": w, "height": h},
               "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}, {"type": "lineTo"},
                                     {"type": "lineTo"}, {"type": "closeSubpath"}, {"type": "moveTo"}]}}
        pathsource = {"bezierPathSource": bez}
    obj = {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "isTextBox": is_textbox,
        "super": {"pathsource": pathsource,
                  "super": {"geometry": {"position": {"x": x, "y": y},
                                         "size": {"width": w, "height": h}}}},
    }
    if text:
        storage_id = f"{ident}-storage"
        objects[storage_id] = {"_pbtype": "TSWP.StorageArchive", "text": [text]}
        obj["ownedStorage"] = {"identifier": storage_id}
    objects[ident] = obj
    return ident


def _simple(objects, ident, pbtype, *, x=0.0, y=0.0, w=10.0, h=10.0):
    objects[ident] = {"_pbtype": pbtype,
                      "super": {"geometry": {"position": {"x": x, "y": y},
                                             "size": {"width": w, "height": h}}}}
    return ident


def _slide(*ids):
    return {"_pbtype": "KN.SlideArchive",
            "drawablesZOrder": [{"identifier": i} for i in ids]}


# --------------------------------------------------------------------------
# Classification.
# --------------------------------------------------------------------------
def test_plain_text_box_is_text_only():
    objects = {}
    tid = _shape(objects, "t", is_textbox=True, text="Hello")
    recs = derive_kind_index(_slide(tid), objects)
    assert [r["kind"] for r in recs] == ["text"]


def test_bare_shape_is_shape_only():
    objects = {}
    sid = _shape(objects, "s", is_textbox=False)
    recs = derive_kind_index(_slide(sid), objects)
    assert [r["kind"] for r in recs] == ["shape"]


def test_text_bearing_non_textbox_is_shape_only_not_dual():
    # A "UPG"/"CHC" label: carries text but isTextBox=False -> shapes ONLY (ground truth).
    objects = {}
    sid = _shape(objects, "lbl", is_textbox=False, text="UPG")
    recs = derive_kind_index(_slide(sid), objects)
    assert [r["kind"] for r in recs] == ["shape"]


def test_custom_path_text_box_is_dual():
    # A shape drawn then given text (custom/editable path): text AND shape.
    objects = {}
    did = _shape(objects, "d", is_textbox=True, text="Title", custom=True)
    recs = derive_kind_index(_slide(did), objects)
    kinds = sorted(r["kind"] for r in recs)
    assert kinds == ["shape", "text"]
    shape_rec = next(r for r in recs if r["kind"] == "shape")
    assert shape_rec["duplicateOf"] == {"kind": "text", "kindIndex": 0}


def test_single_segment_bezier_is_a_line():
    objects = {}
    lid = _shape(objects, "ln", line=True, w=380.0)
    recs = derive_kind_index(_slide(lid), objects)
    assert [r["kind"] for r in recs] == ["line"]


def _bez(obj):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"bezierPathSource": obj}}}


def test_is_line_naturalsize_zero_branch():
    # Zero-dimension naturalSize alone marks a line (elements not [moveTo,lineTo]).
    obj = _bez({"naturalSize": {"width": 200.0, "height": 0.0},
                "path": {"elements": [{"type": "moveTo"}, {"type": "curveTo"}]}})
    assert _is_line(obj) is True


def test_is_line_two_element_branch():
    # A single open [moveTo, lineTo] marks a line even with a non-zero naturalSize.
    obj = _bez({"naturalSize": {"width": 200.0, "height": 5.0},
                "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}]}})
    assert _is_line(obj) is True


def test_is_line_rejects_closed_rectangle():
    obj = _bez({"naturalSize": {"width": 200.0, "height": 50.0},
                "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}, {"type": "lineTo"},
                                      {"type": "lineTo"}, {"type": "closeSubpath"}, {"type": "moveTo"}]}})
    assert _is_line(obj) is False


def test_no_phantom_table_chart_kinds():
    # collectItems never collects tables/charts, so derive must not emit them either.
    objects = {}
    tbl = _simple(objects, "tbl", "TST.TableInfoArchive")
    cht = _simple(objects, "cht", "TSCH.ChartArchive")
    recs = derive_kind_index(_slide(tbl, cht), objects)
    assert recs == []


def test_pbtype_kinds():
    objects = {}
    img = _simple(objects, "i", "TSD.ImageArchive")
    mov = _simple(objects, "m", "TSD.MovieArchive")
    grp = _simple(objects, "g", "TSD.GroupArchive")
    recs = derive_kind_index(_slide(img, mov, grp), objects)
    assert {r["id"]: r["kind"] for r in recs} == {"i": "image", "m": "movie", "g": "group"}


# --------------------------------------------------------------------------
# Ordering — kindIndex is the z-order rank WITHIN each kind.
# --------------------------------------------------------------------------
def test_kindindex_is_per_kind_rank_in_zorder():
    objects = {}
    # z-order: text0, image0, text1, shape0, image1, text2
    ids = [
        _shape(objects, "t0", is_textbox=True, text="a"),
        _simple(objects, "i0", "TSD.ImageArchive"),
        _shape(objects, "t1", is_textbox=True, text="b"),
        _shape(objects, "s0", is_textbox=False),
        _simple(objects, "i1", "TSD.ImageArchive"),
        _shape(objects, "t2", is_textbox=True, text="c"),
    ]
    recs = derive_kind_index(_slide(*ids), objects)
    by_id = {r["id"]: r for r in recs}
    assert (by_id["t0"]["kindIndex"], by_id["t1"]["kindIndex"], by_id["t2"]["kindIndex"]) == (0, 1, 2)
    assert (by_id["i0"]["kindIndex"], by_id["i1"]["kindIndex"]) == (0, 1)
    assert by_id["s0"]["kindIndex"] == 0
    # emitted grouped by KIND_ORDER: all text, then all image, then shape
    assert [r["kind"] for r in recs] == ["text", "text", "text", "image", "image", "shape"]


def test_missing_and_unknown_drawables_are_skipped():
    objects = {}
    tid = _shape(objects, "t", is_textbox=True, text="x")
    objects["ph"] = {"_pbtype": "KN.PlaceholderArchive"}  # not a drawable kind
    recs = derive_kind_index(_slide(tid, "ph", "does-not-exist"), objects)
    assert [r["kind"] for r in recs] == ["text"]


# --------------------------------------------------------------------------
# The count guard.
# --------------------------------------------------------------------------
def test_reconcile_counts_clean_match():
    assert reconcile_counts({"text": 5, "shape": 3}, {"text": 5, "shape": 3}) == []


def test_reconcile_tolerates_trailing_text_placeholders():
    # Keynote appends up to 2 empty placeholders derive omits.
    assert reconcile_counts({"text": 5}, {"text": 7}) == []
    assert reconcile_counts({"text": 5}, {"text": 8}) == ["text"]  # beyond slack


def test_reconcile_flags_real_shape_mismatch():
    assert reconcile_counts({"shape": 1}, {"shape": 3}) == ["shape"]


def test_reconcile_flags_missing_kind():
    assert reconcile_counts({"text": 2}, {"text": 2, "line": 4}) == ["line"]


def test_derived_kind_counts():
    objects = {}
    ids = [_shape(objects, "t0", is_textbox=True, text="a"),
           _shape(objects, "s0", is_textbox=False),
           _simple(objects, "i0", "TSD.ImageArchive")]
    assert derived_kind_counts(derive_kind_index(_slide(*ids), objects)) == {
        "text": 1, "shape": 1, "image": 1}


# --------------------------------------------------------------------------
# Local integration — reproduce a real deck's addressing vs its cached JXA payload.
# --------------------------------------------------------------------------
def _cached_exact_payload(deck: Path):
    try:
        from obed_edom.baseline import deck_digest, inspect_cache_path
    except Exception:  # pragma: no cover
        return None
    try:
        path = inspect_cache_path(deck_digest(deck))
    except Exception:  # pragma: no cover
        return None
    return json.loads(path.read_text()) if path.is_file() else None


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_integration_map_deck_reconstructs_addressing():
    pytest.importorskip("keynote_parser")
    payload = _cached_exact_payload(MAP_DECK)
    if payload is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    from obed_edom.iwa_runs import _normalize_text

    derived = derive_deck_kind_index(MAP_DECK)
    pslides = {s["index"]: s for s in payload.get("slides") or []}
    count_mismatches, text_order_bad = [], 0
    for idx, recs in derived.items():
        jitems = (pslides.get(idx) or {}).get("items") or []
        jcounts: dict[str, int] = {}
        for it in jitems:
            jcounts[it["kind"]] = jcounts.get(it["kind"], 0) + 1
        bad = reconcile_counts(derived_kind_counts(recs), jcounts)
        if bad:
            count_mismatches.append((idx, bad))
        # text ordering by content (the reliable per-object key)
        jtext = sorted((it for it in jitems if it["kind"] == "text"), key=lambda it: it["kindIndex"])
        dtext = sorted((r for r in recs if r["kind"] == "text"), key=lambda r: r["kindIndex"])
        for j, d in zip(jtext, dtext):
            if _normalize_text(j.get("text") or "") != _normalize_text(d.get("text") or ""):
                text_order_bad += 1
    # The Map deck reconstructs exactly: no count mismatch, no text mis-order.
    assert count_mismatches == []
    assert text_order_bad == 0


@pytest.mark.skipif(not FULL_DECK.exists(), reason="local gold deck only")
def test_integration_full_deck_guard_trips_on_dual_slide():
    """The guard's whole justification: on the one residual slide (a filled/variation
    text box JXA lists in both text and shape), reconcile_counts must flag it — and be
    clean on every other slide. This is the only test that watches the guard fall back."""
    pytest.importorskip("keynote_parser")
    payload = _cached_exact_payload(FULL_DECK)
    if payload is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    derived = derive_deck_kind_index(FULL_DECK)
    pslides = {s["index"]: s for s in payload.get("slides") or []}
    flagged = []
    for idx, recs in derived.items():
        jitems = (pslides.get(idx) or {}).get("items") or []
        jcounts: dict[str, int] = {}
        for it in jitems:
            jcounts[it["kind"]] = jcounts.get(it["kind"], 0) + 1
        if reconcile_counts(derived_kind_counts(recs), jcounts):
            flagged.append(idx)
    # Exactly the known dual slide trips the guard; everything else reconciles.
    assert flagged == [73], f"expected only slide 73 to fall back, got {flagged}"
