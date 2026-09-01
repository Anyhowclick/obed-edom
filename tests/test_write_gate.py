"""Pure-logic tests for the A/B write gate (``scripts.write_gate_ab``).

Everything here runs WITHOUT Keynote. The §Gate-compare comparator, the byte-reveal and
the cross-slide locality diff all operate on decoded ``objects`` maps (id -> archive
object) — the same shape ``iwa_runs._load_deck`` returns — so a synthetic deck is just a
dict built in-memory (no IWA serialization needed for the comparator, mirroring
``tests/test_iwa_write.py``'s synthetic-deck spirit at a lighter level). The cross-slide
diff needs real bytes, so those tests build tiny zip files.
"""
from __future__ import annotations

import copy
import io
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from scripts.write_gate_ab import (  # noqa: E402
    build_aprime_applescript,
    build_reported,
    build_reported_offline,
    byte_reveal,
    changed_members,
    check_preconditions,
    compare_signature,
    compare_slides,
    group_child_scale_report,
    id_match_rate,
    load_specs_sidecar,
    match_units,
    positional_crosscheck,
    slide_has_resized_image,
    slide_units,
    specs_hide_count,
    text_autosize_shapes,
    write_specs_sidecar,
)


# --------------------------------------------------------------------------
# In-memory synthetic deck builders (objects map, no serialization).
# --------------------------------------------------------------------------
def _geom(x, y, w, h, angle=0.0, hflip=False, vflip=False):
    g = {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}, "angle": angle}
    if hflip:
        g["horizontalFlip"] = True
    if vflip:
        g["verticalFlip"] = True
    return {"geometry": g}


def _shape(x, y, w, h, **kw):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False,
            "super": {"pathsource": {"bezierPathSource": {"naturalSize": {"width": w, "height": h}}},
                      "super": _geom(x, y, w, h, **kw)}}


def _line(x, y, length, angle=0.0):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False,
            "super": {"pathsource": {"bezierPathSource": {
                "naturalSize": {"width": length, "height": 0.0},
                "path": {"elements": [{"type": "moveTo", "points": [{"x": 0.0, "y": 0.0}]},
                                      {"type": "lineTo", "points": [{"x": 1.0, "y": 0.0}]}]}}},
                      "super": _geom(x, y, length, 0.0, angle=angle)}}


def _image(x, y, w, h, mask_id=None):
    o = {"_pbtype": "TSD.ImageArchive", "super": _geom(x, y, w, h)}
    if mask_id is not None:
        o["mask"] = {"identifier": mask_id}
    return o


def _mask(x, y, w, h, angle=0.0):
    return {"_pbtype": "TSD.MaskArchive", "super": _geom(x, y, w, h, angle=angle)}


def _group(x, y, child_ids):
    return {"_pbtype": "TSD.GroupArchive", "super": _geom(x, y, 0.0, 0.0),
            "children": [{"identifier": c} for c in child_ids]}


def _deck(drawable_ids, extra):
    """One-slide objects map: show/node/slide scaffold + the given drawables/children."""
    objects = {
        "2": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "10"}]}},
        "10": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "100"}, "isSkipped": False},
        "100": {"_pbtype": "KN.SlideArchive",
                "drawablesZOrder": [{"identifier": i} for i in drawable_ids]},
    }
    objects.update(extra)
    return objects


# --------------------------------------------------------------------------
# Preconditions.
# --------------------------------------------------------------------------
def test_slide_has_resized_image():
    assert slide_has_resized_image([{"kind": "image", "w": 160.0}])
    assert slide_has_resized_image([{"kind": "movie", "h": 80.0}])
    assert not slide_has_resized_image([{"kind": "image"}])  # no w/h
    assert not slide_has_resized_image([{"kind": "shape", "w": 10.0}])  # wrong kind


def test_check_preconditions():
    good = [{"slide": 9, "kind": "image", "w": 160.0, "h": 80.0}]
    assert check_preconditions(good, set(), 9) == []
    assert check_preconditions(good, {9}, 9)  # reuse slide -> error
    assert check_preconditions([], set(), 9)  # no transforms -> error
    assert check_preconditions([{"slide": 9, "kind": "shape", "w": 1.0}], set(), 9)  # no image


def test_build_reported_keys_soft_classes_by_kind_index():
    payload = {"slides": [{"number": 9, "items": [
        {"kind": "image", "x": 10, "y": 20, "w": 30, "h": 40},
        {"kind": "image", "x": 50, "y": 60, "w": 70, "h": 80},
        {"kind": "group", "x": 1, "y": 2, "w": 3, "h": 4},
        {"kind": "shape", "x": 9, "y": 9, "w": 9, "h": 9},  # hard class: skipped
    ]}]}
    reported = build_reported(payload, 9)
    assert reported[("image", 0)] == [10.0, 20.0, 30.0, 40.0]
    assert reported[("image", 1)] == [50.0, 60.0, 70.0, 80.0]
    assert reported[("group", 0)] == [1.0, 2.0, 3.0, 4.0]
    assert ("shape", 0) not in reported


# --------------------------------------------------------------------------
# §Gate-compare — identical decks pass; a real move fails.
# --------------------------------------------------------------------------
def _rich_deck():
    return _deck(
        ["200", "210", "230", "250"],
        {"200": _shape(10, 20, 100, 50),
         "210": _line(0, 0, 140, angle=0.0),
         "230": _image(300, 100, 120, 60, mask_id="231"),
         "231": _mask(5, 5, 80, 40),
         "250": _group(500, 500, ["251", "252"]),
         "251": _shape(0, 0, 30, 30),
         "252": _shape(60, 60, 40, 40)},
    )


def test_identical_decks_pass():
    a = _rich_deck()
    b = copy.deepcopy(a)
    report = compare_slides(a, b, 1)
    assert report["pass"]
    assert all(c["pass"] for c in report["per_class"].values())
    assert not report["unmatched_a"] and not report["unmatched_b"]


def test_shifted_shape_fails_with_right_delta():
    a = _rich_deck()
    b = copy.deepcopy(a)
    b["200"]["super"]["super"]["geometry"]["position"]["x"] += 5.0
    report = compare_slides(a, b, 1)
    assert not report["pass"]
    assert not report["per_class"]["shape"]["pass"]
    assert report["per_class"]["shape"]["worst"] == pytest.approx(5.0)
    # the other classes are untouched.
    assert report["per_class"]["line"]["pass"]
    assert report["per_class"]["image"]["pass"]


def test_tolerance_band():
    a = _rich_deck()
    # 1.5px < 2px tolerance -> PASS.
    b = copy.deepcopy(a)
    b["200"]["super"]["super"]["geometry"]["position"]["y"] += 1.5
    assert compare_slides(a, b, 1)["per_class"]["shape"]["pass"]
    # 3px > 2px -> FAIL.
    c = copy.deepcopy(a)
    c["200"]["super"]["super"]["geometry"]["position"]["y"] += 3.0
    assert not compare_slides(a, c, 1)["per_class"]["shape"]["pass"]


def test_flip_is_caught():
    a = _rich_deck()
    b = copy.deepcopy(a)
    b["200"]["super"]["super"]["geometry"]["horizontalFlip"] = True
    report = compare_slides(a, b, 1)
    assert not report["per_class"]["shape"]["pass"]
    assert any("flips" in r for f in report["per_class"]["shape"]["fails"] for r in f["reasons"])


# --------------------------------------------------------------------------
# Same-kind swap: the (kind, kindIndex) match is NOT a multiset.
# --------------------------------------------------------------------------
def test_same_kind_swap_caught_not_hidden_by_multiset():
    # A: shape0 @ (10,20), shape1 @ (400,300). B has DIFFERENT ids (so matching falls to
    # the positional (kind, kindIndex) fallback) with the two geometries SWAPPED. A naive
    # multiset of frames would call this identical; the positional compare must not.
    a = _deck(["200", "201"], {"200": _shape(10, 20, 100, 50), "201": _shape(400, 300, 100, 50)})
    b = _deck(["300", "301"], {"300": _shape(400, 300, 100, 50), "301": _shape(10, 20, 100, 50)})
    report = compare_slides(a, b, 1)
    assert not report["pass"]
    assert not report["per_class"]["shape"]["pass"]
    # both indices moved by the swap distance.
    assert report["per_class"]["shape"]["worst"] == pytest.approx(390.0)


def test_positional_crosscheck_flags_coincident_image_swap():
    a = slide_units(_deck(["230", "232"],
                          {"230": _image(0, 0, 50, 50, "231"), "231": _mask(0, 0, 50, 50),
                           "232": _image(400, 400, 50, 50, "233"), "233": _mask(0, 0, 50, 50)}), 1)
    # B lists the same two images in swapped z-order (kindIndex flipped vs geometry).
    b = slide_units(_deck(["232", "230"],
                          {"230": _image(0, 0, 50, 50, "231"), "231": _mask(0, 0, 50, 50),
                           "232": _image(400, 400, 50, 50, "233"), "233": _mask(0, 0, 50, 50)}), 1)
    notes = positional_crosscheck(a, b)
    assert "image" in notes and "swap" in notes["image"]


# --------------------------------------------------------------------------
# Group: a child moved while the union is unchanged is caught by the children compare.
# --------------------------------------------------------------------------
def test_group_child_moved_union_unchanged_is_caught():
    # 3 children span (0,0)-(100,100); the MIDDLE one is not on any extreme, so moving it
    # inside the box leaves _group_union identical — only the recursive child compare sees it.
    extra = {"250": _group(0, 0, ["251", "252", "253"]),
             "251": _shape(0, 0, 10, 10), "252": _shape(40, 40, 10, 10), "253": _shape(90, 90, 10, 10)}
    a = _deck(["250"], extra)
    b = copy.deepcopy(a)
    b["252"]["super"]["super"]["geometry"]["position"] = {"x": 45.0, "y": 45.0}
    report = compare_slides(a, b, 1)
    # the group's own union unit is unchanged...
    assert report["per_class"]["group"]["pass"]
    # ...but the moved child is caught (child units land under the "child" class).
    assert not report["per_class"]["child"]["pass"]
    assert report["per_class"]["child"]["worst"] == pytest.approx(5.0)
    assert not report["pass"]


# --------------------------------------------------------------------------
# Masked crop compare uses the COMPOSED rect, not the raw image fields.
# --------------------------------------------------------------------------
def test_masked_crop_uses_composed_rect_not_raw_size():
    # A and B share the same mask (so the same composed crop) but the raw image
    # geometry.size differs wildly. The crop compare must PASS (composed rect identical)
    # while the raw size shows up as a SEPARATE crop-visibility failure.
    a = _deck(["230"], {"230": _image(300, 100, 120, 60, "231"), "231": _mask(5, 5, 80, 40)})
    b = _deck(["230"], {"230": _image(300, 100, 999, 999, "231"), "231": _mask(5, 5, 80, 40)})
    pairs, _ua, _ub = match_units(slide_units(a, 1), slide_units(b, 1))
    (ua, ub, _how), = pairs
    ok, worst, reasons = compare_signature(ua["sig"], ub["sig"])
    assert worst == pytest.approx(0.0)  # composed crop rect identical
    assert not ok and any("raw image size" in r for r in reasons)  # raw size flagged separately


def test_masked_crop_move_fails():
    # Moving the mask moves the composed crop -> the masked class fails on position.
    a = _deck(["230"], {"230": _image(300, 100, 120, 60, "231"), "231": _mask(5, 5, 80, 40)})
    b = copy.deepcopy(a)
    b["231"]["super"]["geometry"]["position"]["x"] += 10.0
    report = compare_slides(a, b, 1)
    assert not report["per_class"]["image"]["pass"]
    assert report["per_class"]["image"]["worst"] == pytest.approx(10.0)


# --------------------------------------------------------------------------
# byte-reveal: which raw geometry fields differ, per class.
# --------------------------------------------------------------------------
def test_byte_reveal_reports_mutated_fields_per_class():
    a = _rich_deck()
    b = copy.deepcopy(a)
    # simulate an AS "set size" on the masked image (image geometry.size changes).
    b["230"]["super"]["geometry"]["size"] = {"width": 200.0, "height": 100.0}
    # and a position nudge on the shape.
    b["200"]["super"]["super"]["geometry"]["position"]["x"] += 7.0
    pairs, _ua, _ub = match_units(slide_units(a, 1), slide_units(b, 1))
    reveal = byte_reveal(a, b, pairs)
    assert set(reveal["image"]) == {"size_w", "size_h"}
    assert set(reveal["shape"]) == {"pos_x"}
    assert "line" not in reveal  # untouched


# --------------------------------------------------------------------------
# Cross-slide locality: only the patched member's bytes differ.
# --------------------------------------------------------------------------
def _zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_changed_members_reports_only_the_edited_member(tmp_path):
    a = tmp_path / "a.key"
    b = tmp_path / "b.key"
    a.write_bytes(_zip_bytes({"Index/Document.iwa": b"doc",
                              "Index/Slide-9.iwa": b"nine",
                              "Index/Slide-8.iwa": b"eight"}))
    b.write_bytes(_zip_bytes({"Index/Document.iwa": b"doc",
                              "Index/Slide-9.iwa": b"NINE-patched",
                              "Index/Slide-8.iwa": b"eight"}))
    assert changed_members(a, b) == {"Index/Slide-9.iwa"}


def test_text_autosize_shapes_carveout():
    # Normal shapes have a real extent -> nothing to carve out.
    assert text_autosize_shapes(slide_units(_rich_deck(), 1)) == []
    # A shape whose FRAME height is 0 (autosize tell) but whose naturalSize is non-zero
    # (so it is not a line) is flagged for carve-out.
    autosize_shape = {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False,
                      "super": {"pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 50.0}}},
                                "super": _geom(10, 20, 100, 0)}}
    flagged = text_autosize_shapes(slide_units(_deck(["200"], {"200": autosize_shape}), 1))
    assert len(flagged) == 1 and flagged[0]["kind"] == "shape"


def test_changed_members_flags_added_or_removed_member(tmp_path):
    a = tmp_path / "a.key"
    b = tmp_path / "b.key"
    a.write_bytes(_zip_bytes({"Index/Document.iwa": b"doc"}))
    b.write_bytes(_zip_bytes({"Index/Document.iwa": b"doc", "Index/Extra.iwa": b"x"}))
    assert changed_members(a, b) == {"Index/Extra.iwa"}


# --------------------------------------------------------------------------
# ID-match rate: A' and B share B-pre's ids, so id-match must be ~100%; a
# different-id pairing FELL BACK to positional and the whole result is UNTRUSTED.
# --------------------------------------------------------------------------
def test_id_match_rate_and_id_stable_flag():
    a = _rich_deck()
    # Same ids on both sides -> every pair matches by id -> rate 1.0, id-stable.
    same = compare_slides(a, copy.deepcopy(a), 1)
    assert same["id_match_rate"] == pytest.approx(1.0)
    assert same["id_stable"] and same["pass"]
    # id_match_rate is a pure function of the pairs' `how`.
    pairs, _ua, _ub = match_units(slide_units(a, 1), slide_units(a, 1))
    assert id_match_rate(pairs) == pytest.approx(1.0)


def test_positional_fallback_is_untrusted_even_when_geometry_matches():
    # DIFFERENT ids but IDENTICAL geometry: the positional fallback would call this a
    # clean pass, but the gate must mark it UNTRUSTED (id_stable False) and force pass
    # False, because A' is supposed to share B-pre's ids.
    a = _deck(["200", "201"], {"200": _shape(10, 20, 100, 50), "201": _shape(400, 300, 60, 60)})
    b = _deck(["300", "301"], {"300": _shape(10, 20, 100, 50), "301": _shape(400, 300, 60, 60)})
    report = compare_slides(a, b, 1)
    assert report["id_match_rate"] == pytest.approx(0.0)
    assert not report["id_stable"]
    assert not report["pass"]  # untrusted -> never green
    # every per-class geometry compare individually matched...
    assert all(c["pass"] for c in report["per_class"].values())
    # ...yet the overall gate is RED purely because it fell back to positional.


# --------------------------------------------------------------------------
# Group-child transform measurement (A'/B child size ratios, id-matched).
# --------------------------------------------------------------------------
def _group_scale_decks(a_child_sizes, b_child_sizes):
    """Two decks sharing ids: a group with children sized per the given lists."""
    def mk(sizes):
        extra = {"250": _group(0, 0, ["251", "252"])}
        for cid, (w, h) in zip(("251", "252"), sizes):
            extra[cid] = _shape(0, 0, w, h)
        return _deck(["250"], extra)
    return mk(a_child_sizes), mk(b_child_sizes)


def test_group_child_scale_uniform():
    # A' children are 2x B's children on both axes -> a clean uniform scale.
    a, b = _group_scale_decks([(30, 30), (40, 40)], [(15, 15), (20, 20)])
    pairs, _ua, _ub = match_units(slide_units(a, 1), slide_units(b, 1))
    scale = group_child_scale_report(pairs)
    assert len(scale) == 1
    (root, summary), = scale.items()
    assert root == ("top", "group", 0)
    assert summary["n"] == 2
    assert summary["sx_range"][0] == pytest.approx(2.0)
    assert summary["sx_range"][1] == pytest.approx(2.0)
    assert summary["uniform"]
    # all children matched by id.
    assert all(c["how"] == "id" for c in summary["children"])


def test_group_child_scale_non_uniform_flagged():
    # child 0 scales 2x in x but 1x in y (sx != sy) -> NOT a clean uniform scale.
    a, b = _group_scale_decks([(30, 15), (40, 40)], [(15, 15), (20, 20)])
    pairs, _ua, _ub = match_units(slide_units(a, 1), slide_units(b, 1))
    scale = group_child_scale_report(pairs)
    (_root, summary), = scale.items()
    assert not summary["uniform"]


# --------------------------------------------------------------------------
# Autosize carve-out is ENFORCED (not just warned): the shape is excluded from
# the compare even when its frame differs between A' and B.
# --------------------------------------------------------------------------
def _autosize_shape(x):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False,
            "super": {"pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 50.0}}},
                      "super": _geom(x, 20, 100, 0)}}


def test_autosize_carveout_enforced_in_compare():
    # An autosize shape (frame h==0) at DIFFERENT x on each side would fail a frame
    # compare; enforcement drops it from both sides, so the gate passes and lists it.
    a = _deck(["200"], {"200": _autosize_shape(10.0)})
    b = _deck(["200"], {"200": _autosize_shape(999.0)})
    report = compare_slides(a, b, 1)
    assert report["carved"] == ["200"]
    assert "shape" not in report["per_class"]  # carved out entirely
    assert report["pass"]  # nothing left to fail
    # A real (non-autosize) shape at a different x is NOT carved and DOES fail.
    a2 = _deck(["201"], {"201": _shape(10, 20, 100, 50)})
    b2 = _deck(["201"], {"201": _shape(999, 20, 100, 50)})
    report2 = compare_slides(a2, b2, 1)
    assert report2["carved"] == []
    assert not report2["per_class"]["shape"]["pass"]


# --------------------------------------------------------------------------
# Specs sidecar round-trip + offline reported + hide guard + A' scaffold.
# --------------------------------------------------------------------------
def test_specs_sidecar_round_trip(tmp_path):
    specs = [{"slide": 9, "kind": "image", "kindIndex": 0, "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}]
    counts = {"image": 5, "group": 2}
    path = tmp_path / "specs_slide9.json"
    write_specs_sidecar(path, slide_number=9, source="/w.key", template="/t.key",
                        specs=specs, source_counts=counts)
    loaded = load_specs_sidecar(path)
    assert loaded["slide"] == 9
    assert loaded["source"] == "/w.key" and loaded["template"] == "/t.key"
    assert loaded["specs"] == specs
    assert loaded["source_counts"] == counts


def test_build_reported_offline_composes_soft_frames():
    # A masked image + a group: both soft classes' composed frames come out offline.
    deck = _deck(["230", "250"],
                 {"230": _image(300, 100, 120, 60, "231"), "231": _mask(5, 5, 80, 40),
                  "250": _group(0, 0, ["251"]), "251": _shape(10, 20, 30, 40)})
    reported = build_reported_offline(deck, 1)
    # masked image composed crop = (image_pos + mask_pos, mask_size).
    assert reported[("image", 0)] == pytest.approx([305.0, 105.0, 80.0, 40.0])
    assert ("group", 0) in reported


def test_specs_hide_count():
    assert specs_hide_count([{"role": "hide"}, {"role": "other"}, {"role": "hide"}]) == 2
    assert specs_hide_count([{"role": "other"}]) == 0


def test_build_aprime_applescript_wraps_body():
    body = "with timeout of 3600 seconds\ntell slide 9\n  end tell\nend timeout"
    script = build_aprime_applescript("/tmp/x.key", body)
    assert body in script
    assert "open POSIX file" in script and "/tmp/x.key" in script
    assert "tell theDoc" in script and "save theDoc" in script
    assert "close theDoc saving yes" in script
