"""Offline surgical geometry-write tests (obed_edom.iwa_write).

Everything here runs WITHOUT Keynote. The value-clean / read-back tests operate on a
tiny but REAL ``.key``: synthetic IWA members are serialized through
``keynote_parser.codec.IWAFile`` (the same codec the patcher rewrites), so the
member-rewrite, the value-clean self-check, and the offline compose read-back are
all exercised for real. ``_complete`` fills the structural archives' proto-required
fields (KN.Show/SlideNode/Slide) so the deck round-trips; the drawable archives
carry only the geometry the composition rules read. The pure addressing/delta math
(deleteHides bridge, reconcile base, per-class field builders) is unit-tested
directly with no deck at all.
"""
from __future__ import annotations

import copy
import io
import re
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from keynote_parser.codec import IWAFile, import_version  # noqa: E402

from obed_edom import iwa_write  # noqa: E402
from obed_edom.iwa_geometry import compose_geometry  # noqa: E402
from obed_edom.iwa_runs import _load_deck  # noqa: E402
from obed_edom.iwa_write import (  # noqa: E402
    PatchResult,
    _apply_geom_fields,
    _masked_image_fields,
    _shape_fields,
    _text_fields,
    bridge_kind_index,
    expected_base_counts,
    line_inverse,
    patch_slide_geometry,
)
from obed_edom.offline_inspect import _line_endpoints  # noqa: E402

_ID_NAME_MAP, _, _ = import_version()
_INV_ID = {c.DESCRIPTOR.full_name: t for t, c in _ID_NAME_MAP.items()}
_INV_CLS = {c.DESCRIPTOR.full_name: c for t, c in _ID_NAME_MAP.items()}
_ARCHIVE_INFO = "TSP.ArchiveInfo"
_MESSAGE_INFO = "TSP.MessageInfo"


# --------------------------------------------------------------------------
# Synthetic REAL-.key builder.
# --------------------------------------------------------------------------
def _scalar_default(field):
    ct = field.cpp_type
    if ct in (1, 2, 3, 4):  # int/uint 32/64
        return 0
    if ct in (5, 6):  # double/float
        return 0.0
    if ct == 7:  # bool
        return False
    if ct == 8:  # enum
        return field.enum_type.values[0].number
    if ct == 9:  # string
        return ""
    return {}


def _fill_path(d, msg_cls, dotted):
    parts = dotted.split(".")
    desc = msg_cls.DESCRIPTOR
    for i, part in enumerate(parts):
        field = desc.fields_by_name[part]
        if i == len(parts) - 1:
            if field.message_type is not None:
                d[part] = d.get(part) or {}
            else:
                d.setdefault(part, _scalar_default(field))
        else:
            d = d.setdefault(part, {})
            desc = field.message_type


def _archive_dict(ident, pbtype, obj):
    o = dict(obj)
    o["_pbtype"] = pbtype
    return {
        "header": {
            "_pbtype": _ARCHIVE_INFO,
            "identifier": ident,
            "messageInfos": [{"_pbtype": _MESSAGE_INFO, "type": _INV_ID[pbtype], "identifier": ident}],
        },
        "objects": [o],
    }


def _complete(pbtype, obj):
    """Fill an archive object's proto-required fields until it serializes."""
    cls = _INV_CLS[pbtype]
    obj = copy.deepcopy(obj)
    for _ in range(60):
        try:
            IWAFile.from_dict({"chunks": [{"archives": [_archive_dict(1, pbtype, obj)]}]}).to_buffer()
            return obj
        except Exception as exc:  # noqa: BLE001 — the message names the missing fields
            match = re.search(r"missing required fields: ([^\n']+)", str(exc))
            if not match:
                raise
            for name in match.group(1).split(","):
                _fill_path(obj, cls, name.strip())
    raise RuntimeError("too many required fields to fill")


def _arch(ident, pbtype, obj):
    return _archive_dict(ident, pbtype, _complete(pbtype, obj))


def _member(archives):
    return IWAFile.from_dict({"chunks": [{"archives": archives}]}).to_buffer()


def _geom(x, y, w, h, angle=0.0):
    return {"geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}, "angle": angle}}


def _shape_super(x, y, w, h, *, nw=None, nh=None, line=False):
    bez = {"naturalSize": {"width": nw if nw is not None else w, "height": nh if nh is not None else h}}
    if line:
        bez["path"] = {"elements": [
            {"type": "moveTo", "points": [{"x": 0.0, "y": 0.0}]},
            {"type": "lineTo", "points": [{"x": 1.0, "y": 0.0}]},
        ]}
    return {"pathsource": {"bezierPathSource": bez}, "super": _geom(x, y, w, h)}


def _build_deck(path, *, shapes=(200,), extra_drawables=("line", "text", "image", "group")):
    """Write a one-slide .key with a configurable drawable set to ``path``.

    Default set: one shape (id 200), a line (210), an autosize text box (220 +
    storage 221), a masked image (230 + mask 231), and a group (250 + child 251).
    ``shapes`` lets a test add extra bare shapes (ids given) for the bridge test.
    """
    slide_member = []
    zorder = []
    for sid in shapes:
        slide_member.append(_arch(sid, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(10, 20, 100, 50)}))
        zorder.append(sid)
    if "line" in extra_drawables:
        slide_member.append(_arch(210, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 140, 0, nw=140, nh=0, line=True)}))
        zorder.append(210)
    if "text" in extra_drawables:
        slide_member.append(_arch(221, "TSWP.StorageArchive", {"text": ["Hello"]}))
        slide_member.append(_arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(700, 374, 0, 0, nw=200, nh=60)}))
        zorder.append(220)
    if "image" in extra_drawables:
        slide_member.append(_arch(231, "TSD.MaskArchive", {"super": _geom(5, 5, 80, 40)}))
        slide_member.append(_arch(230, "TSD.ImageArchive", {"mask": {"identifier": 231}, "super": _geom(300, 100, 120, 60)}))
        zorder.append(230)
    if "group" in extra_drawables:
        slide_member.append(_arch(251, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 30, 30)}))
        slide_member.append(_arch(250, "TSD.GroupArchive", {"super": _geom(500, 500, 0, 0), "children": [{"identifier": 251}]}))
        zorder.append(250)
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": i} for i in zorder]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *slide_member]))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "synth.key")


def _composed(path):
    objects, _idf, _fi = _load_deck(path)
    return {(r["kind"], r["kindIndex"]): r for r in compose_geometry(objects["100"], objects)}


# --------------------------------------------------------------------------
# Pure math: line inverse, deleteHides bridge, reconcile base.
# --------------------------------------------------------------------------
def test_line_inverse_round_trips_through_line_endpoints():
    # A horizontal template line: line_inverse produces the frame that composes back
    # to the requested endpoints (the whole line write contract, no deck needed).
    obj = {"super": _shape_super(0, 0, 100, 0, nw=100, nh=0, line=True)}
    px, py, length, angle = line_inverse(obj, [10.0, 20.0], [40.0, 60.0])
    obj["super"]["super"]["geometry"] = {"position": {"x": px, "y": py}, "size": {"width": length, "height": 0.0}, "angle": angle}
    start, end = _line_endpoints(obj)
    assert start == pytest.approx([10.0, 20.0])
    assert end == pytest.approx([40.0, 60.0])


def test_bridge_kind_index_subtracts_lower_same_kind_hides():
    hides = [
        {"kind": "shape", "kindIndex": 0, "role": "hide"},
        {"kind": "shape", "kindIndex": 3, "role": "hide"},
        {"kind": "image", "kindIndex": 1, "role": "hide"},  # other kind: no effect
    ]
    # wall shape 5: two lower shape-hides (indexes 0 and 3) => saved index 3.
    assert bridge_kind_index("shape", 5, hides) == 3
    # wall shape 1: only the index-0 hide is lower => saved 0.
    assert bridge_kind_index("shape", 1, hides) == 0
    # image untouched by shape hides (only its own index-1 hide would count).
    assert bridge_kind_index("image", 2, hides) == 1


def test_expected_base_counts_subtracts_hide_specs_per_kind():
    source = {"shape": 4, "image": 3, "text": 2}
    specs = [
        {"kind": "shape", "kindIndex": 0, "role": "hide"},
        {"kind": "shape", "kindIndex": 1, "role": "hide"},
        {"kind": "image", "kindIndex": 0, "role": "hide"},
        {"kind": "text", "kindIndex": 0, "role": "other"},  # not a hide
    ]
    assert expected_base_counts(source, specs) == {"shape": 2, "image": 2, "text": 2}


# --------------------------------------------------------------------------
# Field builders (soft-class delta math with an INJECTED reported double).
# --------------------------------------------------------------------------
def test_text_fields_x_absolute_y_delta_on_stored_centre():
    rec = {"id": "9", "kind": "text", "kindIndex": 0}
    stored = (700.0, 374.0, 200.0, 60.0, 0.0)  # stored y is the vertical centre
    reported = [700.0, 344.0, 200.0, 60.0]  # injected pre-patch top-left frame
    spec = {"kind": "text", "kindIndex": 0, "x": 760.0, "y": 404.0}
    (obj_id, fields), = _text_fields(rec, spec, reported, stored)
    assert obj_id == "9"
    assert fields["pos_x"] == 760.0  # x is exact absolute
    # y delta = 404 - 344 = 60, applied to the stored centre 374 => 434.
    assert fields["pos_y"] == pytest.approx(434.0)
    assert "size_w" not in fields and "size_h" not in fields  # no reported w/h delta asked


def test_shape_fields_size_writes_geometry_and_naturalsize():
    rec = {"id": "5", "kind": "shape", "kindIndex": 0}
    spec = {"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 300.0, "h": 120.0}
    (_id, fields), = _shape_fields(rec, spec)
    assert fields["size_w"] == 300.0 and fields["natural_w"] == 300.0
    assert fields["size_h"] == 120.0 and fields["natural_h"] == 120.0
    assert fields["pos_x"] == 60.0 and fields["pos_y"] == 70.0


def test_apply_geom_fields_mutates_geometry_and_naturalsize():
    obj = {"super": _shape_super(10, 20, 100, 50)}
    _apply_geom_fields(obj, {"pos_x": 1.0, "pos_y": 2.0, "size_w": 3.0, "size_h": 4.0,
                             "angle": 5.0, "natural_w": 6.0, "natural_h": 7.0})
    geom = obj["super"]["super"]["geometry"]
    assert (geom["position"]["x"], geom["position"]["y"]) == (1.0, 2.0)
    assert (geom["size"]["width"], geom["size"]["height"]) == (3.0, 4.0)
    assert geom["angle"] == 5.0
    ns = obj["super"]["pathsource"]["bezierPathSource"]["naturalSize"]
    assert (ns["width"], ns["height"]) == (6.0, 7.0)


# --------------------------------------------------------------------------
# Value-clean member rewrite + offline read-back on the real synthetic deck.
# --------------------------------------------------------------------------
def test_shape_line_text_group_writes_value_clean_and_read_back(deck):
    before = _composed(deck)
    specs = [
        {"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 300.0, "h": 120.0, "role": "other"},
        {"kind": "line", "kindIndex": 0, "start": [150.0, 420.0], "end": [560.0, 560.0], "role": "other"},
        {"kind": "text", "kindIndex": 0, "x": 760.0, "y": 404.0, "role": "other"},
        {"kind": "group", "kindIndex": 0, "x": 540.0, "y": 560.0, "role": "other"},
    ]
    res = patch_slide_geometry(deck, 1, specs)
    assert isinstance(res, PatchResult)
    assert res.applied == 4 and res.missed == 0 and not res.refused
    assert res.value_clean and res.header_diffs == 0
    assert res.obj_diffs == len(res.edited_ids) == 4
    assert res.target_member == "Index/Slide-100.iwa"

    after = _composed(deck)
    # shape: position + size land absolutely.
    assert [after[("shape", 0)][k] for k in "xywh"] == pytest.approx([60.0, 70.0, 300.0, 120.0])
    # line: endpoints reproduce exactly.
    objects, _idf, _fi = _load_deck(deck)
    start, end = _line_endpoints(objects["210"])
    assert start == pytest.approx([150.0, 420.0]) and end == pytest.approx([560.0, 560.0])
    # text: x absolute, y delta on the stored centre (composed top = 404).
    assert after[("text", 0)]["x"] == pytest.approx(760.0)
    assert after[("text", 0)]["y"] == pytest.approx(404.0)
    # group: pure translation of +40/+60; its w/h is untouched.
    assert [after[("group", 0)][k] for k in "xy"] == pytest.approx([540.0, 560.0])
    assert [after[("group", 0)][k] for k in "wh"] == pytest.approx(
        [before[("group", 0)]["w"], before[("group", 0)]["h"]]
    )


def test_masked_image_mask_and_size_write_value_clean(deck):
    # TENTATIVE masked-image rule (deferred to the lead's live byte-reveal): the mask
    # is moved+sized so the composed crop lands at target, value-clean; the image
    # geometry.size is scaled too (the unverified bit). Read-back == target crop.
    specs = [{"kind": "image", "kindIndex": 0, "x": 400.0, "y": 200.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.applied and not res.refused and res.value_clean and res.header_diffs == 0
    # image write touches BOTH the image archive and the mask archive.
    assert set(res.edited_ids) == {"230", "231"}
    after = _composed(deck)
    assert [after[("image", 0)][k] for k in "xywh"] == pytest.approx([400.0, 200.0, 160.0, 80.0])


def test_value_clean_allows_noop_edit_below_edit_count(deck):
    # A no-op masked-image edit: spec == the CURRENT composed crop (305,105,80,40) with
    # crop ratio 1.0, so the written mask+image values EQUAL the stored ones and neither
    # archive's bytes change. Two archives are in the edit set (230,231) but obj_diffs is
    # 0 (< len(edits)). The relaxed self-check (obj_diffs <= len(edits)) must still call
    # this value-clean — the OLD `==` check would have spuriously failed it.
    specs = [{"kind": "image", "kindIndex": 0, "x": 305.0, "y": 105.0, "w": 80.0, "h": 40.0,
              "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert not res.refused
    assert set(res.edited_ids) == {"230", "231"}
    assert res.obj_diffs == 0 < len(res.edited_ids)  # no-op: fewer diffs than edits
    assert res.header_diffs == 0
    assert res.value_clean  # relaxed check: obj_diffs <= len(edits) and no header change


def test_value_clean_boundary_real_edit_is_clean(deck):
    # A genuine single-archive edit sits at the boundary obj_diffs == len(edits) == 1
    # (one archive changed, one in the edit set) -> still value-clean. The relaxation
    # only widened the ACCEPTED band downward (no-op edits); the collateral direction
    # obj_diffs > len(edits) is unchanged and still fails.
    specs = [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.obj_diffs == 1 == len(res.edited_ids)
    assert res.value_clean and res.header_diffs == 0


def test_target_member_from_id_to_file(deck):
    # The target is the drawables' member, never the slide id's (here they coincide,
    # but the derivation is via id_to_file of a drawable).
    res = patch_slide_geometry(deck, 1, [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}])
    assert res.target_member == "Index/Slide-100.iwa"


# --------------------------------------------------------------------------
# Addressing gates.
# --------------------------------------------------------------------------
def test_reconcile_mismatch_refuses_without_writing(deck):
    original = deck.read_bytes()
    # Saved deck has shape count 1; claim a source base of 5 with no hides => mismatch.
    specs = [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs, source_counts={"shape": 5})
    assert res.refused and "reconcile" in (res.reason or "")
    assert res.applied == 0
    assert deck.read_bytes() == original  # nothing written


def test_reconcile_pass_when_base_matches(deck):
    # source shape=2 minus one shape hide == saved shape=1: gate passes, write applies.
    # The base must cover every kind the saved slide carries, else a kind with no
    # source count would read as 0 and (correctly) trip the gate.
    specs = [
        {"kind": "shape", "kindIndex": 0, "role": "hide"},
        {"kind": "shape", "kindIndex": 1, "x": 60.0, "y": 70.0, "role": "other"},
    ]
    source_counts = {"shape": 2, "line": 1, "text": 1, "image": 1, "group": 1}
    res = patch_slide_geometry(deck, 1, specs, source_counts=source_counts)
    assert not res.refused
    # wall shape 1 bridged past the deleted hide at 0 => saved shape 0 gets written.
    after = _composed(deck)
    assert [after[("shape", 0)][k] for k in "xy"] == pytest.approx([60.0, 70.0])


def test_out_of_range_slide_refused(deck):
    res = patch_slide_geometry(deck, 9, [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0}])
    assert res.refused and "out of range" in (res.reason or "")


# --------------------------------------------------------------------------
# Hardening 1: require_reconcile makes the reconcile gate MANDATORY.
# --------------------------------------------------------------------------
def test_require_reconcile_refuses_when_source_counts_missing(deck):
    original = deck.read_bytes()
    specs = [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs, require_reconcile=True)
    assert res.refused
    assert res.reason == "reconcile required but source_counts missing"
    assert res.applied == 0
    assert deck.read_bytes() == original  # nothing written


def test_require_reconcile_proceeds_when_source_counts_present(deck):
    # Armed with a matching base, the mandatory gate lets the write through.
    source_counts = {"shape": 1, "line": 1, "text": 1, "image": 1, "group": 1}
    specs = [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs, source_counts=source_counts, require_reconcile=True)
    assert not res.refused and res.applied == 1


# --------------------------------------------------------------------------
# Hardening 2: soft_fallbacks counts soft-class specs with no reported frame.
# --------------------------------------------------------------------------
def test_soft_fallbacks_counted_for_group_without_reported(deck):
    # group is a soft class: with no reported frame its delta falls back to the offline
    # composed frame, which must be COUNTED so the gate can insist on 0.
    specs = [{"kind": "group", "kindIndex": 0, "x": 540.0, "y": 560.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.applied == 1 and res.soft_fallbacks == 1


def test_soft_fallbacks_zero_when_reported_supplied(deck):
    before = _composed(deck)
    rep = [before[("group", 0)][k] for k in "xywh"]
    specs = [{"kind": "group", "kindIndex": 0, "x": 540.0, "y": 560.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs, reported={("group", 0): rep})
    assert res.applied == 1 and res.soft_fallbacks == 0


def test_soft_fallbacks_ignores_hard_classes(deck):
    # shape/line take absolute specs (no reported delta), so they never count as soft.
    specs = [
        {"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 300.0, "h": 120.0, "role": "other"},
        {"kind": "line", "kindIndex": 0, "start": [150.0, 420.0], "end": [560.0, 560.0], "role": "other"},
    ]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.applied == 2 and res.soft_fallbacks == 0


# --------------------------------------------------------------------------
# Hardening 3: rotated masked image / mask is a MISS, never mis-written.
# --------------------------------------------------------------------------
def _build_rotated_mask_deck(path, *, img_angle=0.0, mask_angle=0.0):
    mask = _arch(231, "TSD.MaskArchive", {"super": _geom(5, 5, 80, 40, angle=mask_angle)})
    img = _arch(230, "TSD.ImageArchive",
                {"mask": {"identifier": 231}, "super": _geom(300, 100, 120, 60, angle=img_angle)})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 230}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, img, mask]))
    path.write_bytes(buf.getvalue())
    return path


def test_masked_image_fields_refuses_rotated_image():
    mask = {"_pbtype": "TSD.MaskArchive", "super": _geom(5, 5, 80, 40, angle=0.0)}
    img = {"mask": {"identifier": 231}, "super": _geom(300, 100, 120, 60, angle=90.0)}
    ops, mask_id = _masked_image_fields(
        {"id": "230"}, img, {"231": mask}, {"x": 1.0, "y": 2.0, "w": 10.0, "h": 20.0}, [0, 0, 0, 0]
    )
    assert ops == [] and mask_id == "231"  # rotated: refuse the axis-aligned crop write


def test_masked_image_fields_refuses_rotated_mask():
    mask = {"_pbtype": "TSD.MaskArchive", "super": _geom(5, 5, 80, 40, angle=90.0)}
    img = {"mask": {"identifier": 231}, "super": _geom(300, 100, 120, 60, angle=0.0)}
    ops, mask_id = _masked_image_fields(
        {"id": "230"}, img, {"231": mask}, {"x": 1.0, "y": 2.0, "w": 10.0, "h": 20.0}, [0, 0, 0, 0]
    )
    assert ops == [] and mask_id == "231"


@pytest.mark.parametrize("img_angle,mask_angle", [(90.0, 0.0), (0.0, 45.0)])
def test_rotated_masked_image_missed_not_written(tmp_path, img_angle, mask_angle):
    deck = _build_rotated_mask_deck(tmp_path / "rot.key", img_angle=img_angle, mask_angle=mask_angle)
    original = deck.read_bytes()
    specs = [{"kind": "image", "kindIndex": 0, "x": 400.0, "y": 200.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.missed == 1 and res.applied == 0
    assert deck.read_bytes() == original  # rotated masked image left untouched
