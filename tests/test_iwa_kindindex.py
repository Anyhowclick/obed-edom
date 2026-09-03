"""Tests for offline (kind, kindIndex) reconstruction (obed_edom.iwa_kindindex).

The classification / ordering / guard logic is pure and exercised WITHOUT keynote-parser
by building synthetic IWA drawable dicts. A local-only integration test reproduces the
addressing on a real deck and diffs it against that deck's cached exact-bytes JXA payload
when the deck, the parser, and the cached payload are all present.

KIND_ORDER is the same six kinds, same order as inspect_keynote.js collectItems
(text, image, shape, movie, group, line). Tables/charts are omitted because JXA
never enumerates them.

Membership: isTextBox drives textItems; shapes = not-textbox or custom path;
a custom-path text box is a dual. A line is an open two-point bezier or a zero
natural dimension — multi-point freeforms stay shapes.

reconcile_counts is cardinality-only. text/shape/line/movie order is verified;
image/group order is inferred from the z-order walk and still needs composed
geometry before a write. Empty title/body placeholders JXA appends last are not
in drawablesZOrder (TEXT_PLACEHOLDER_SLACK). Full slide 73 is a filled/variation
box listed in both textItems and shapes — the count guard falls back on it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from obed_edom.iwa_kindindex import (
    _is_line,
    deck_kind_counts,
    derive_deck_kind_index,
    derive_kind_index,
    derived_kind_counts,
    kind_counts_from_records,
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
# deck_kind_counts — real (tiny synthetic) .key, two slides with distinct shape counts.
# --------------------------------------------------------------------------
def _build_two_slide_real_deck(path):
    """Slide 1: one shape. Slide 2: two shapes. Minimal real IWA round-trip via keynote_parser."""
    import io
    import re
    import zipfile

    from keynote_parser.codec import IWAFile, import_version

    id_name_map, _, _ = import_version()
    inv_id = {c.DESCRIPTOR.full_name: t for t, c in id_name_map.items()}
    inv_cls = {c.DESCRIPTOR.full_name: c for t, c in id_name_map.items()}

    def scalar_default(field):
        ct = field.cpp_type
        if ct in (1, 2, 3, 4):
            return 0
        if ct in (5, 6):
            return 0.0
        if ct == 7:
            return False
        if ct == 8:
            return field.enum_type.values[0].number
        if ct == 9:
            return ""
        return {}

    def fill_path(d, msg_cls, dotted):
        parts = dotted.split(".")
        desc = msg_cls.DESCRIPTOR
        for i, part in enumerate(parts):
            field = desc.fields_by_name[part]
            if i == len(parts) - 1:
                if field.message_type is not None:
                    d[part] = d.get(part) or {}
                else:
                    d.setdefault(part, scalar_default(field))
            else:
                d = d.setdefault(part, {})
                desc = field.message_type

    def archive_dict(ident, pbtype, obj):
        o = dict(obj)
        o["_pbtype"] = pbtype
        return {"header": {"_pbtype": "TSP.ArchiveInfo", "identifier": ident,
                           "messageInfos": [{"_pbtype": "TSP.MessageInfo", "type": inv_id[pbtype], "identifier": ident}]},
                "objects": [o]}

    def complete(pbtype, obj):
        cls = inv_cls[pbtype]
        for _ in range(60):
            try:
                IWAFile.from_dict({"chunks": [{"archives": [archive_dict(1, pbtype, obj)]}]}).to_buffer()
                return obj
            except Exception as exc:  # noqa: BLE001 — the message names the missing fields
                match = re.search(r"missing required fields: ([^\n']+)", str(exc))
                if not match:
                    raise
                for name in match.group(1).split(","):
                    fill_path(obj, cls, name.strip())
        raise RuntimeError("too many required fields to fill")

    def arch(ident, pbtype, obj):
        return archive_dict(ident, pbtype, complete(pbtype, dict(obj)))

    def member(archives):
        return IWAFile.from_dict({"chunks": [{"archives": archives}]}).to_buffer()

    def shape(ident, x):
        bez = {"naturalSize": {"width": 10.0, "height": 10.0}}
        sup = {"pathsource": {"bezierPathSource": bez},
               "super": {"geometry": {"position": {"x": x, "y": 0.0}, "size": {"width": 10.0, "height": 10.0}, "angle": 0.0}}}
        return arch(ident, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": sup})

    slide1 = arch(101, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 200}]})
    slide2 = arch(102, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 210}, {"identifier": 211}]})
    show = arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]}})
    node1 = arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False})
    node2 = arch(11, "KN.SlideNodeArchive", {"slide": {"identifier": 102}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", member([show, node1, node2]))
        z.writestr("Index/Slide-101.iwa", member([slide1, shape(200, 0.0)]))
        z.writestr("Index/Slide-102.iwa", member([slide2, shape(210, 0.0), shape(211, 20.0)]))
    path.write_bytes(buf.getvalue())
    return path


def test_deck_kind_counts_is_one_based(tmp_path):
    pytest.importorskip("keynote_parser")
    deck = _build_two_slide_real_deck(tmp_path / "counts.key")
    counts = deck_kind_counts(deck)
    assert set(counts) == {1, 2}  # 1-based, not 0-based like derive_deck_kind_index
    assert counts[1] == {"shape": 1}
    assert counts[2] == {"shape": 2}


def test_deck_kind_counts_matches_derived_per_slide(tmp_path):
    pytest.importorskip("keynote_parser")
    deck = _build_two_slide_real_deck(tmp_path / "counts2.key")
    counts = deck_kind_counts(deck)
    derived = derive_deck_kind_index(deck)  # 0-based
    expected = {idx + 1: recs for idx, recs in derived.items()}
    assert counts == kind_counts_from_records(expected)


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
