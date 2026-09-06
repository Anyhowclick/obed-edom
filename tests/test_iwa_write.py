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

Per class: shape writes geometry.size AND naturalSize (Keynote lays out from
naturalSize). Line length goes in both geometry.size.width and naturalSize.width.
Group is translation only when the spec lacks w/h; given both, a uniform scale
(spec size / child-union size) also writes the group's own w/h and rescales every
descendant's local geometry — an unscalable descendant misses the whole group.
Text y is a centre delta off the reported frame. Masked-image crop is
axis-aligned only; rotated masks miss rather than mis-place.

In-place O_TRUNC preserves inode + com.apple.macl; a new file is refused by
sandboxed Keynote. Positional addressing refuses the slide on reconcile_counts
mismatch. obj_diffs < len(edits) is a no-op rewrite; obj_diffs > len(edits) is
collateral and fails.
"""
from __future__ import annotations

import copy
import io
import re
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from keynote_parser.codec import IWAFile, import_version  # noqa: E402

from obed_edom import iwa_builds, iwa_write  # noqa: E402
from obed_edom.iwa_builds import deck_builds  # noqa: E402
from obed_edom.iwa_geometry import _frame_rect, _geom_dict, _xywha, compose_geometry  # noqa: E402
from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: E402
from obed_edom.remap_keynote import restore_source_builds  # noqa: E402
from obed_edom.iwa_write import (  # noqa: E402
    OfflineWriteCorrupted,
    OfflineWriteRefused,
    PatchResult,
    _apply_geom_fields,
    _group_child_scale_ops,
    _group_fields,
    _is_identity_mask,
    _masked_media_fields,
    _natural_unwritable,
    _natural_writable,
    _patch_member,
    _rewrite_members,
    _shape_fields,
    _slide_edits,
    _text_fields,
    bridge_kind_index,
    bridge_specs_kindindex,
    expected_base_counts,
    line_inverse,
    patch_slide_builds,
    patch_deck_geometry,
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


# Real coordinates off ids 20554069/20541783 (naturalSize (165.52277, 23)): thirds-spaced
# bezier controls plus an exact-naturalSize endpoint node, and one (0,0) origin node.
_EDITABLE_NODES = [
    {"type": "bezier", "nodePoint": {"x": 0.0, "y": 0.0},
     "inControlPoint": {"x": 0.0, "y": 0.0}, "outControlPoint": {"x": 13.793564, "y": 23.0}},
    {"type": "bezier", "nodePoint": {"x": 41.38069, "y": 23.0},
     "inControlPoint": {"x": 27.587128, "y": 23.0}, "outControlPoint": {"x": 62.071037, "y": 23.0}},
    {"type": "bezier", "nodePoint": {"x": 165.52277, "y": 23.0},
     "inControlPoint": {"x": 165.52277, "y": 23.0}, "outControlPoint": {"x": 165.52277, "y": 23.0}},
]


def _shape_super(x, y, w, h, *, nw=None, nh=None, line=False, kind="bezier"):
    nat = {"width": nw if nw is not None else w, "height": nh if nh is not None else h}
    if kind == "scalar":
        ps = {"scalarPathSource": {"type": "kTSDRoundedRectangle", "scalar": 2.3926985, "naturalSize": nat}}
    elif kind == "editable":
        ps = {"editableBezierPathSource": {
            "naturalSize": nat,
            "subpaths": [{"closed": True, "nodes": copy.deepcopy(_EDITABLE_NODES)}],
        }}
    else:
        bez = {"naturalSize": nat}
        if line:
            bez["path"] = {"elements": [
                {"type": "moveTo", "points": [{"x": 0.0, "y": 0.0}]},
                {"type": "lineTo", "points": [{"x": 1.0, "y": 0.0}]},
            ]}
        ps = {"bezierPathSource": bez}
    return {"pathsource": ps, "super": _geom(x, y, w, h)}


def _mask_super(x, y, w, h, *, nw=None, nh=None, angle=0.0):
    nat = {"width": nw if nw is not None else w, "height": nh if nh is not None else h}
    return {"pathsource": {"bezierPathSource": {"naturalSize": nat}}, "super": _geom(x, y, w, h, angle)}


def _build_deck(path, *, shapes=(200,), extra_drawables=("line", "text", "image", "group")):
    """Write a one-slide .key with a configurable drawable set to ``path``.

    Default set: one shape (id 200), a line (210), a fixed-height text box (220 +
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
        # Fixed (non-sentinel) stored width AND height: a stored w==0.0 or h==0.0 is a
        # hard miss to the AppleScript fallback (Fix 2), and this deck exercises the
        # offline text writer.
        slide_member.append(_arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)}))
        zorder.append(220)
    if "image" in extra_drawables:
        # IDENTITY mask (mask == image frame, no crop): mask at (0,0,120,60) is the whole
        # image, so image_pos + mask_pos == image_pos (300,100), size == mask size (120,60).
        slide_member.append(_arch(231, "TSD.MaskArchive", _mask_super(0, 0, 120, 60)))
        slide_member.append(_arch(230, "TSD.ImageArchive",
                                  {"mask": {"identifier": 231}, "super": _geom(300, 100, 120, 60),
                                   "originalSize": {"width": 120.0, "height": 60.0}}))
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


def _build_cropped_mask_deck(path):
    """One masked image whose mask is a REAL crop (mask size < image size): the
    identity-mask write must refuse this rather than guess a redistribution."""
    mask = _arch(231, "TSD.MaskArchive", _mask_super(5, 5, 80, 40))
    img = _arch(230, "TSD.ImageArchive",
                {"mask": {"identifier": 231}, "super": _geom(300, 100, 120, 60),
                 "originalSize": {"width": 120.0, "height": 60.0}})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 230}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, img, mask]))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "synth.key")


def _composed(path):
    objects, _idf, _fi = _load_deck(path)
    return {(r["kind"], r["kindIndex"]): r for r in compose_geometry(objects["100"], objects)}


def _build_two_slide_deck(path):
    """Two content slides, each in its OWN exclusive Index/Slide-*.iwa member: slide 1
    (archive 101, shape 300) and slide 2 (archive 102, shape 400)."""
    shape1 = _arch(300, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(10, 20, 100, 50)})
    slide1 = _arch(101, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 300}]})
    shape2 = _arch(400, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(30, 40, 80, 60)})
    slide2 = _arch(102, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 400}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]}})
    node1 = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False})
    node2 = _arch(11, "KN.SlideNodeArchive", {"slide": {"identifier": 102}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node1, node2]))
        z.writestr("Index/Slide-101.iwa", _member([slide1, shape1]))
        z.writestr("Index/Slide-102.iwa", _member([slide2, shape2]))
    path.write_bytes(buf.getvalue())
    return path


def _build_shared_member_deck(path):
    """Two slide NODES pointing at the SAME slide archive (101) -> same target member,
    for the member-collision refusal test."""
    shape1 = _arch(300, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(10, 20, 100, 50)})
    slide1 = _arch(101, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 300}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]}})
    node1 = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False})
    node2 = _arch(11, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node1, node2]))
        z.writestr("Index/Slide-101.iwa", _member([slide1, shape1]))
    path.write_bytes(buf.getvalue())
    return path


def _build_effect(effect, animation_type="In"):
    return {
        "animationAttributes": {
            "animationType": animation_type,
            "effect": effect,
            "duration": 0.5,
            "direction": 0,
            "delay": 0.0,
            "randomNumberSeed": 1,
            "writingDirectionIsRtl": False,
        },
    }


def _transition_dict(effect, duration):
    return {
        "attributes": {
            "animationAttributes": {
                "animationType": "Transition",
                "effect": effect,
                "duration": duration,
                "delay": 0.5,
                "isAutomatic": False,
                "randomNumberSeed": 1,
                "writingDirectionIsRtl": False,
            },
            "customMagicMoveFadeUnmatchedObjects": True,
            "customTimingCurve": "TransitionCustomAttributesTimingCurveTypeEaseInEaseOut",
            "customTextDeliveryType": "TransitionCustomAttributesTextDeliveryTypeByObject",
        }
    }


def _build_builds_deck(path):
    """Two slides, each in its OWN exclusive member (real Keynote layout): a text box,
    an image and a group, plus KN.BuildArchive/KN.BuildChunkArchive objects and a
    ``transition`` on the SlideArchive -- everything ``patch_slide_builds`` touches.

    Slide 100: text 220 ("Hello"), image 230 (photo-500.png), group 250 (child 251,
    "CHC Arao"); builds 900/901/902 target them 1:1; chunks 910/911/912; transition
    none/1.0 (a pure inline dict, no nested reference).
    Slide 101: text 320 ("World"), image 330 (photo-501.jpg), group 350 (child 351,
    "Total Churches"); builds 903/904 target the text/image only; chunks 913/914;
    transition dissolve/0.5.
    """
    text220 = _arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)})
    storage221 = _arch(221, "TSWP.StorageArchive", {"text": ["Hello"]})
    image230 = _arch(230, "TSD.ImageArchive", {"data": {"identifier": 500}, "super": _geom(300, 100, 120, 60), "originalSize": {"width": 120.0, "height": 60.0}})
    child251 = _arch(251, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 252}, "super": _shape_super(0, 0, 30, 30)})
    storage252 = _arch(252, "TSWP.StorageArchive", {"text": ["CHC Arao"]})
    group250 = _arch(250, "TSD.GroupArchive", {"super": _geom(500, 500, 30, 30), "children": [{"identifier": 251}]})
    build900 = _arch(900, "KN.BuildArchive", {"drawable": {"identifier": 220}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:dissolve"), "chunkIdSeed": 1})
    build901 = _arch(901, "KN.BuildArchive", {"drawable": {"identifier": 230}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:wipe-iris"), "chunkIdSeed": 1})
    build902 = _arch(902, "KN.BuildArchive", {"drawable": {"identifier": 250}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:bc-zoom-big"), "chunkIdSeed": 1})
    chunk910 = _arch(910, "KN.BuildChunkArchive", {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "1", "upper": "1"}})
    chunk911 = _arch(911, "KN.BuildChunkArchive", {"build": {"identifier": 901}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "2", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "2", "upper": "1"}})
    chunk912 = _arch(912, "KN.BuildChunkArchive", {"build": {"identifier": 902}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "3", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "3", "upper": "1"}})
    slide100 = _arch(
        100,
        "KN.SlideArchive",
        {
            "drawablesZOrder": [{"identifier": 220}, {"identifier": 230}, {"identifier": 250}],
            "builds": [{"identifier": 900}, {"identifier": 901}, {"identifier": 902}],
            "buildChunks": [{"identifier": 910}, {"identifier": 911}, {"identifier": 912}],
            "transition": _transition_dict("none", 1.0),
        },
    )

    text320 = _arch(320, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 321}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)})
    storage321 = _arch(321, "TSWP.StorageArchive", {"text": ["World"]})
    image330 = _arch(330, "TSD.ImageArchive", {"data": {"identifier": 501}, "super": _geom(300, 100, 120, 60), "originalSize": {"width": 120.0, "height": 60.0}})
    child351 = _arch(351, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 352}, "super": _shape_super(0, 0, 30, 30)})
    storage352 = _arch(352, "TSWP.StorageArchive", {"text": ["Total Churches"]})
    group350 = _arch(350, "TSD.GroupArchive", {"super": _geom(500, 500, 30, 30), "children": [{"identifier": 351}]})
    build903 = _arch(903, "KN.BuildArchive", {"drawable": {"identifier": 320}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:dissolve"), "chunkIdSeed": 1})
    build904 = _arch(904, "KN.BuildArchive", {"drawable": {"identifier": 330}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:wipe-iris"), "chunkIdSeed": 1})
    chunk913 = _arch(913, "KN.BuildChunkArchive", {"build": {"identifier": 903}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "4", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "4", "upper": "1"}})
    chunk914 = _arch(914, "KN.BuildChunkArchive", {"build": {"identifier": 904}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "5", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "5", "upper": "1"}})
    slide101 = _arch(
        101,
        "KN.SlideArchive",
        {
            "drawablesZOrder": [{"identifier": 320}, {"identifier": 330}, {"identifier": 350}],
            "builds": [{"identifier": 903}, {"identifier": 904}],
            "buildChunks": [{"identifier": 913}, {"identifier": 914}],
            "transition": _transition_dict("apple:dissolve", 0.5),
        },
    )

    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]}})
    node1 = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    node2 = _arch(11, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node1, node2]))
        z.writestr(
            "Index/Slide-100.iwa",
            _member([slide100, text220, storage221, image230, child251, storage252, group250,
                      build900, build901, build902, chunk910, chunk911, chunk912]),
        )
        z.writestr(
            "Index/Slide-101.iwa",
            _member([slide101, text320, storage321, image330, child351, storage352, group350,
                      build903, build904, chunk913, chunk914]),
        )
        z.writestr("Data/photo-500.png", b"\x89PNG-fake-500")
        z.writestr("Data/photo-501.jpg", b"\xff\xd8-fake-501")
    path.write_bytes(buf.getvalue())
    return path


def _build_builds_shared_member_deck(path):
    """Two SlideArchives (100, 101), each with its own build/chunk/transition, in
    the SAME member (Index/Slide-100.iwa) -- the multi-slide-in-one-member path."""
    text220 = _arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)})
    storage221 = _arch(221, "TSWP.StorageArchive", {"text": ["Hello"]})
    build900 = _arch(900, "KN.BuildArchive", {"drawable": {"identifier": 220}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:dissolve"), "chunkIdSeed": 1})
    chunk910 = _arch(910, "KN.BuildChunkArchive", {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "1", "upper": "1"}})
    slide100 = _arch(100, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 220}],
        "builds": [{"identifier": 900}],
        "buildChunks": [{"identifier": 910}],
        "transition": _transition_dict("none", 1.0),
    })

    text320 = _arch(320, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 321}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)})
    storage321 = _arch(321, "TSWP.StorageArchive", {"text": ["World"]})
    build901 = _arch(901, "KN.BuildArchive", {"drawable": {"identifier": 320}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:wipe-iris"), "chunkIdSeed": 1})
    chunk911 = _arch(911, "KN.BuildChunkArchive", {"build": {"identifier": 901}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "2", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "2", "upper": "1"}})
    slide101 = _arch(101, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 320}],
        "builds": [{"identifier": 901}],
        "buildChunks": [{"identifier": 911}],
        "transition": _transition_dict("apple:dissolve", 0.5),
    })

    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]}})
    node1 = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    node2 = _arch(11, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node1, node2]))
        z.writestr(
            "Index/Slide-100.iwa",
            _member([slide100, text220, storage221, build900, chunk910,
                      slide101, text320, storage321, build901, chunk911]),
        )
    path.write_bytes(buf.getvalue())
    return path


def _build_multi_chunk_deck(path):
    """One slide, one build with TWO chunks; the member's archive order is the
    REVERSE of the slide's own buildChunks order -- proves chunkIds follow the
    latter, not decode order."""
    text220 = _arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)})
    storage221 = _arch(221, "TSWP.StorageArchive", {"text": ["Hello"]})
    build900 = _arch(900, "KN.BuildArchive", {"drawable": {"identifier": 220}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:dissolve"), "chunkIdSeed": 1})
    chunk_a = _arch(950, "KN.BuildChunkArchive", {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "1", "upper": "1"}})
    chunk_b = _arch(951, "KN.BuildChunkArchive", {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 2}, "buildId": {"lower": "1", "upper": "1"}})
    slide100 = _arch(100, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 220}],
        "builds": [{"identifier": 900}],
        "buildChunks": [{"identifier": 951}, {"identifier": 950}],  # B before A
    })
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        # Archive order in the member is A then B -- the REVERSE of buildChunks above.
        z.writestr("Index/Slide-100.iwa", _member([slide100, text220, storage221, build900, chunk_a, chunk_b]))
    path.write_bytes(buf.getvalue())
    return path


def _build_orphan_chunk_deck(path):
    """One slide, one build with TWO chunk archives referencing it, but the slide's
    OWN buildChunks names only one -- the other is an orphan that must be DROPPED,
    not appended after the real ones."""
    text220 = _arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(700, 374, 200, 60, nw=200, nh=60)})
    storage221 = _arch(221, "TSWP.StorageArchive", {"text": ["Hello"]})
    build900 = _arch(900, "KN.BuildArchive", {"drawable": {"identifier": 220}, "delivery": "All at Once", "duration": 0.0, "attributes": _build_effect("apple:dissolve"), "chunkIdSeed": 1})
    chunk_listed = _arch(950, "KN.BuildChunkArchive", {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 1}, "buildId": {"lower": "1", "upper": "1"}})
    chunk_orphan = _arch(951, "KN.BuildChunkArchive", {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": True, "referent": True, "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 2}, "buildId": {"lower": "1", "upper": "1"}})
    slide100 = _arch(100, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 220}],
        "builds": [{"identifier": 900}],
        "buildChunks": [{"identifier": 950}],  # 951 exists in the member but is not listed here
    })
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide100, text220, storage221, build900, chunk_listed, chunk_orphan]))
    path.write_bytes(buf.getvalue())
    return path


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


def test_bridge_specs_kindindex_shifts_survivors_above_a_deleted_hide():
    # A hide at image[0] shifts every higher same-kind survivor down by one; other kinds
    # and survivors below the hide are untouched. Mirrors the patcher's _resolve_positional.
    specs = [
        {"kind": "image", "kindIndex": 0, "role": "hide"},
        {"kind": "image", "kindIndex": 1, "role": "map"},
        {"kind": "image", "kindIndex": 2, "role": "map"},
        {"kind": "line", "kindIndex": 0, "role": "line"},
    ]
    bridged = bridge_specs_kindindex(specs)
    by = {(b["kind"], b["role"]): b["kindIndex"] for b in bridged}
    assert by[("image", "hide")] == 0  # hide spec left as-is (skipped by the AS body)
    assert by[("image", "map")] in (0, 1)  # the two survivors bridged 1->0, 2->1
    assert sorted(b["kindIndex"] for b in bridged if b["role"] == "map") == [0, 1]
    assert by[("line", "line")] == 0  # unrelated kind untouched


def test_bridge_specs_kindindex_noop_when_hides_sit_above_all_survivors():
    # Slide-9 shape: the deleted hides are the TOP two image indices, so no survivor shifts.
    specs = [
        {"kind": "image", "kindIndex": i, "role": "map"} for i in range(3)
    ] + [
        {"kind": "image", "kindIndex": 3, "role": "hide"},
        {"kind": "image", "kindIndex": 4, "role": "hide"},
    ]
    bridged = bridge_specs_kindindex(specs)
    assert [b["kindIndex"] for b in bridged] == [s["kindIndex"] for s in specs]


def test_bridge_specs_kindindex_noop_without_hides():
    specs = [{"kind": "image", "kindIndex": 5, "role": "map"}]
    assert bridge_specs_kindindex(specs) is specs  # returned unchanged, no copy


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


def test_text_fields_autosize_height_never_writes_size_h():
    # stored h == 0.0 is the AUTOSIZE sentinel (iwa_geometry.py's `th == 0.0`) -- writing
    # size_h here would freeze the box into a fixed-height frame (a real defect).
    rec = {"id": "20539608", "kind": "text", "kindIndex": 0}
    stored = (700.0, 374.0, 2327.5, 0.0, 0.0)
    reported = [700.0, 344.0, 1140.0, 0.0]
    spec = {"kind": "text", "kindIndex": 0, "x": 760.0, "y": 404.0, "w": 1139.88, "h": 43.0}
    (obj_id, fields), = _text_fields(rec, spec, reported, stored)
    assert obj_id == "20539608"
    assert "pos_x" in fields and "pos_y" in fields
    assert "size_w" in fields  # width is the wrap width, not the autosize sentinel
    assert "size_h" not in fields  # NEVER write size_h when stored h is the sentinel


def test_text_fields_fixed_height_still_writes_size_h():
    rec = {"id": "9", "kind": "text", "kindIndex": 0}
    stored = (700.0, 374.0, 200.0, 60.0, 0.0)  # non-zero stored h: a real fixed-frame box
    reported = [700.0, 344.0, 200.0, 60.0]
    spec = {"kind": "text", "kindIndex": 0, "x": 760.0, "y": 404.0, "w": 250.0, "h": 90.0}
    (_obj_id, fields), = _text_fields(rec, spec, reported, stored)
    assert fields["size_h"] == pytest.approx(60.0 + (90.0 - 60.0))
    assert fields["size_w"] == pytest.approx(200.0 + (250.0 - 200.0))


def test_text_fields_zero_width_never_writes_size_w():
    # A stored width of 0.0 is the autosize sentinel too -- it has no delta base AND no
    # writable frame (naturalSize.width would go stale exactly like height), so it must
    # never be written, not even the target outright.
    rec = {"id": "1", "kind": "text", "kindIndex": 0}
    stored = (297.0, 292.0, 0.0, 0.0, 0.0)
    reported = [1188.0, 1168.0, 452.0, 136.0]
    spec = {"kind": "text", "kindIndex": 0, "w": 113.0}
    result = _text_fields(rec, spec, reported, stored)
    assert result == []


def test_text_fields_nonzero_width_keeps_delta_and_writes_natural_w():
    rec = {"id": "1", "kind": "text", "kindIndex": 0}
    stored = (700.0, 374.0, 200.0, 60.0, 0.0)
    reported = [700.0, 344.0, 200.0, 60.0]  # reported width == stored width: zero delta
    spec = {"kind": "text", "kindIndex": 0, "w": 250.0}
    (_obj_id, fields), = _text_fields(rec, spec, reported, stored)
    assert fields["size_w"] == pytest.approx(250.0) and fields["natural_w"] == pytest.approx(250.0)


def test_text_fields_fixed_height_also_writes_natural_h():
    rec = {"id": "9", "kind": "text", "kindIndex": 0}
    stored = (700.0, 374.0, 200.0, 60.0, 0.0)
    reported = [700.0, 344.0, 200.0, 60.0]
    spec = {"kind": "text", "kindIndex": 0, "x": 760.0, "y": 404.0, "w": 250.0, "h": 90.0}
    (_obj_id, fields), = _text_fields(rec, spec, reported, stored)
    assert fields["size_h"] == fields["natural_h"] == pytest.approx(90.0)


def test_shape_fields_size_writes_geometry_and_naturalsize():
    rec = {"id": "5", "kind": "shape", "kindIndex": 0}
    spec = {"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 300.0, "h": 120.0}
    stored = (0.0, 0.0, 300.0, 120.0, 0.0)
    (_id, fields), = _shape_fields(rec, spec, stored)
    assert fields["size_w"] == 300.0 and fields["natural_w"] == 300.0
    assert fields["size_h"] == 120.0 and fields["natural_h"] == 120.0
    assert fields["pos_x"] == 60.0 and fields["pos_y"] == 70.0


def test_shape_fields_rotation_anchor_matches_slide59_image_17832898():
    rec = {"id": "17832898", "kind": "image", "kindIndex": 0}
    spec = {"kind": "image", "kindIndex": 0, "x": -8304.0, "y": 0.0, "w": 14244.0, "h": 10636.0}
    stored = (0.0, 0.0, 14244.0, 10636.0, 332.5)
    (_id, fields), = _shape_fields(rec, spec, stored)
    assert fields["pos_x"] == pytest.approx(-6653.129720920795, abs=1e-6)
    assert fields["pos_y"] == pytest.approx(2687.6972343016932, abs=1e-6)


def test_shape_fields_rotation_anchor_matches_slide57_shape_17431696():
    rec = {"id": "17431696", "kind": "shape", "kindIndex": 0}
    spec = {"kind": "shape", "kindIndex": 0, "x": 363.0, "y": 286.0, "w": 17.0, "h": 17.0}
    stored = (0.0, 0.0, 17.0, 17.0, 242.44)
    (_id, fields), = _shape_fields(rec, spec, stored)
    assert fields["pos_x"] == pytest.approx(365.9682343429508, abs=1e-6)
    assert fields["pos_y"] == pytest.approx(288.9682343429508, abs=1e-6)


@pytest.mark.parametrize("angle,w,h,x,y", [
    (332.5, 14244.0, 10636.0, -8304.0, 0.0),
    (242.44, 17.0, 17.0, 363.0, 286.0),
    (90.0, 100.0, 50.0, 10.0, 20.0),
    (0.0, 100.0, 50.0, 10.0, 20.0),
])
def test_shape_fields_rotation_round_trips_through_frame_rect(angle, w, h, x, y):
    rec = {"id": "1", "kind": "shape", "kindIndex": 0}
    spec = {"kind": "shape", "kindIndex": 0, "x": x, "y": y, "w": w, "h": h}
    stored = (0.0, 0.0, w, h, angle)
    (_id, fields), = _shape_fields(rec, spec, stored)
    geom = {"position": {"x": fields["pos_x"], "y": fields["pos_y"]},
            "size": {"width": w, "height": h}, "angle": angle}
    x0, y0, _w0, _h0 = _frame_rect(geom)
    assert x0 == pytest.approx(x, abs=1e-6)
    assert y0 == pytest.approx(y, abs=1e-6)


def test_shape_fields_sub_eps_angle_gets_no_correction():
    rec = {"id": "1", "kind": "image", "kindIndex": 0}
    spec = {"kind": "image", "kindIndex": 0, "x": -8304.0, "y": 0.0}
    stored = (0.0, 0.0, 14244.0, 10636.0, 0.005)
    (_id, fields), = _shape_fields(rec, spec, stored)
    assert fields["pos_x"] == -8304.0
    assert fields["pos_y"] == 0.0


def test_shape_fields_uses_stored_size_when_spec_omits_wh():
    rec = {"id": "1", "kind": "shape", "kindIndex": 0}
    spec = {"kind": "shape", "kindIndex": 0, "x": 10.0, "y": 20.0}
    stored = (0.0, 0.0, 100.0, 50.0, 90.0)
    (_id, fields), = _shape_fields(rec, spec, stored)
    assert fields["pos_x"] == pytest.approx(10.0 - 25.0, abs=1e-6)
    assert fields["pos_y"] == pytest.approx(20.0 + 25.0, abs=1e-6)
    assert "size_w" not in fields and "size_h" not in fields


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
# _natural_writable / _natural_unwritable / _write_natural_size (universal
# path-natural finder): scalar, editableBezier, callout/connectionLine, image/movie.
# --------------------------------------------------------------------------
def test_natural_writable_scalar_path_source():
    obj = {"super": _shape_super(0, 0, 100, 50, kind="scalar")}
    assert _natural_writable(obj, both_axes=True) is True
    assert _natural_writable(obj, both_axes=False) is True  # plain kind: axis count irrelevant


def test_apply_geom_fields_scalar_writes_naturalsize_and_leaves_scalar():
    # ANISOTROPIC resize (ratios 4.0009 vs 4.0243, well past the 1e-3 uniform tolerance):
    # naturalSize still writes, but `scalar` is left untouched.
    obj = {"super": _shape_super(0, 0, 100, 50, nw=52.238213, nh=11.679036, kind="scalar")}
    _apply_geom_fields(obj, {"natural_w": 209.0, "natural_h": 47.0})
    sps = obj["super"]["pathsource"]["scalarPathSource"]
    ns = sps["naturalSize"]
    assert (ns["width"], ns["height"]) == pytest.approx((209.0, 47.0))
    assert sps["scalar"] == 2.3926985  # anisotropic: scalar NOT rescaled


def test_apply_geom_fields_scalar_scales_scalar_under_uniform_resize():
    # UNIFORM resize (ratio 4.0012 on both axes, mask 20557359's measured deck evidence):
    # `scalar` scales WITH naturalSize.
    obj = {"super": _shape_super(0, 0, 100, 50, nw=69.72262, nh=78.727066, kind="scalar")}
    obj["super"]["pathsource"]["scalarPathSource"]["scalar"] = 47.236244
    _apply_geom_fields(obj, {"natural_w": 278.9717, "natural_h": 315.0})
    sps = obj["super"]["pathsource"]["scalarPathSource"]
    ns = sps["naturalSize"]
    assert (ns["width"], ns["height"]) == pytest.approx((278.9717, 315.0))
    assert sps["scalar"] == pytest.approx(189.0, abs=0.05)


def test_apply_geom_fields_editable_bezier_scales_nodes_about_origin():
    obj = {"super": _shape_super(0, 0, 165.52277, 23.0, kind="editable")}
    _apply_geom_fields(obj, {"natural_w": 662.0, "natural_h": 92.0})
    sub = obj["super"]["pathsource"]["editableBezierPathSource"]
    ns = sub["naturalSize"]
    assert (ns["width"], ns["height"]) == pytest.approx((662.0, 92.0))
    nodes = sub["subpaths"][0]["nodes"]
    assert nodes[0]["nodePoint"]["x"] == pytest.approx(0.0, abs=1e-3)  # (0,0) stays (0,0)
    assert nodes[0]["nodePoint"]["y"] == pytest.approx(0.0, abs=1e-3)
    assert nodes[0]["outControlPoint"]["x"] == pytest.approx(55.166666, abs=1e-3)
    assert nodes[1]["nodePoint"]["x"] == pytest.approx(165.5, abs=1e-3)
    assert nodes[1]["inControlPoint"]["x"] == pytest.approx(110.333332, abs=1e-3)
    assert nodes[1]["outControlPoint"]["x"] == pytest.approx(248.25, abs=1e-3)
    assert nodes[2]["nodePoint"]["x"] == pytest.approx(662.0, abs=1e-3)
    for node in nodes[1:]:
        for key in ("nodePoint", "inControlPoint", "outControlPoint"):
            assert node[key]["y"] == pytest.approx(92.0, abs=1e-3)


def test_apply_geom_fields_editable_bezier_needs_both_axes():
    obj = {"super": _shape_super(0, 0, 165.52277, 23.0, kind="editable")}
    before = copy.deepcopy(obj)
    _apply_geom_fields(obj, {"natural_w": 662.0})  # natural_h missing
    assert obj == before  # nodes and naturalSize untouched


def test_natural_writable_editable_bezier_degenerate_naturalsize_is_false():
    obj = {"super": _shape_super(0, 0, 165.52277, 23.0, nw=0.0, nh=23.0, kind="editable")}
    assert _natural_writable(obj, both_axes=True) is False


def test_natural_writable_callout_and_connection_line_are_false():
    callout = {"super": {"pathsource": {"calloutPathSource": {}}, "super": _geom(0, 0, 10, 10)}}
    connline = {"super": {"pathsource": {"connectionLinePathSource": {}}, "super": _geom(0, 0, 10, 10)}}
    assert _natural_writable(callout, both_axes=True) is False
    assert _natural_writable(connline, both_axes=True) is False


def test_natural_writable_missing_pathsource_and_originalsize_is_false():
    obj = {"super": _geom(0, 0, 10, 10)}
    assert _natural_writable(obj, both_axes=True) is False
    assert _natural_writable(obj, both_axes=False) is False


def test_natural_writable_point_path_source():
    obj = {"super": {"pathsource": {"pointPathSource": {"naturalSize": {"width": 10.0, "height": 10.0}}},
                     "super": _geom(0, 0, 10, 10)}}
    assert _natural_writable(obj, both_axes=True) is True
    assert _natural_writable(obj, both_axes=False) is True  # plain kind: axis count irrelevant


def test_apply_geom_fields_image_writes_originalsize_not_media_naturalsize():
    obj = {"originalSize": {"width": 120.0, "height": 60.0},
           "naturalSize": {"width": 7680.0, "height": 1080.0},  # media pixel size: untouched
           "super": _geom(300, 100, 120, 60)}
    _apply_geom_fields(obj, {"pos_x": 1.0, "natural_w": 200.0, "natural_h": 100.0})
    assert obj["originalSize"] == pytest.approx({"width": 200.0, "height": 100.0})
    assert obj["naturalSize"] == {"width": 7680.0, "height": 1080.0}


def test_apply_geom_fields_movie_originalsize():
    obj = {"originalSize": {"width": 960.0, "height": 540.0}, "super": _geom(0, 0, 960, 540)}
    _apply_geom_fields(obj, {"natural_w": 3532.07, "natural_h": 1986.79})
    assert obj["originalSize"] == pytest.approx({"width": 3532.07, "height": 1986.79})


# --------------------------------------------------------------------------
# Hard-miss gate: a shape whose path source can't carry a render-derived size
# (callout) never mis-writes; a position-only spec is unaffected.
# --------------------------------------------------------------------------
def _build_unwritable_shape_deck(path):
    """One shape (id 500) whose path source is a CALLOUT -- no writable render-derived
    size (`_natural_writable` is False)."""
    shape = _arch(500, "TSWP.ShapeInfoArchive",
                  {"isTextBox": False, "super": {"pathsource": {"calloutPathSource": {}},
                                                 "super": _geom(10, 20, 100, 50)}})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 500}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, shape]))
    path.write_bytes(buf.getvalue())
    return path


def test_shape_fields_position_only_spec_never_hard_misses_on_unwritable_pathsource(tmp_path):
    deck = _build_unwritable_shape_deck(tmp_path / "unwritable.key")
    specs = [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert not res.refused and res.missed == 0 and res.applied == 1
    after = _composed(deck)
    assert [after[("shape", 0)][k] for k in "xy"] == pytest.approx([60.0, 70.0])


def test_shape_resize_on_unwritable_pathsource_hard_misses(tmp_path):
    deck = _build_unwritable_shape_deck(tmp_path / "unwritable.key")
    original = deck.read_bytes()
    specs = [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 200.0, "h": 90.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.missed == 1 and res.applied == 0
    assert res.missed_specs == specs
    assert deck.read_bytes() == original


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


def test_masked_image_identity_mask_writes_image_and_mask(deck):
    # The fixture's mask is an IDENTITY window (mask == image frame, no crop): the mask
    # is scaled+repositioned to the target size, the image moves/scales with it, and both
    # naturalSize/originalSize track the write. Read-back == target crop.
    specs = [{"kind": "image", "kindIndex": 0, "x": 400.0, "y": 200.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.applied and not res.refused and res.value_clean and res.header_diffs == 0
    # image write touches BOTH the image archive and the mask archive.
    assert set(res.edited_ids) == {"230", "231"}
    after = _composed(deck)
    assert [after[("image", 0)][k] for k in "xywh"] == pytest.approx([400.0, 200.0, 160.0, 80.0])
    objects, _idf, _fi = _load_deck(deck)
    mask_ns = objects["231"]["pathsource"]["bezierPathSource"]["naturalSize"]
    assert (mask_ns["width"], mask_ns["height"]) == pytest.approx((160.0, 80.0))
    img_original = objects["230"]["originalSize"]
    assert (img_original["width"], img_original["height"]) == pytest.approx((160.0, 80.0))


def test_masked_image_cropped_mask_hard_misses(tmp_path):
    # A real crop (mask smaller than the image) is not an identity window: refuse rather
    # than guess a redistribution. Deck left byte-identical.
    deck = _build_cropped_mask_deck(tmp_path / "cropped.key")
    original = deck.read_bytes()
    specs = [{"kind": "image", "kindIndex": 0, "x": 400.0, "y": 200.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.missed == 1 and res.applied == 0
    assert res.missed_specs == specs
    assert deck.read_bytes() == original


def test_masked_media_identity_predicate_production_cases():
    # Production spot-checks (frame w/h, mask x/y/w/h), all axis-aligned (angle 0).
    assert _is_identity_mask(3840.0, 1080.0, 0.0, 0.0, 0.0, 3840.0, 1080.0, 0.0) is True
    assert _is_identity_mask(80.01, 80.0, 0.0, 0.0, -0.0, 80.0, 80.0, 0.0) is True
    assert _is_identity_mask(2365.92, 1194.79, 0.0, 0.0, -20.37, 2365.92, 1150.0, 0.0) is False
    assert _is_identity_mask(619.43, 931.77, 0.0, 164.04, 226.5, 278.97, 315.0, 0.0) is False


def test_is_identity_mask_boundaries():
    # tol = min(1px, 0.5% of frame): a 3840px-wide frame hits the 1px bound (0.5% is looser).
    assert _is_identity_mask(3840.0, 1080.0, 0.0, 0.9, 0.0, 3840.0, 1080.0, 0.0) is True
    assert _is_identity_mask(3840.0, 1080.0, 0.0, 1.1, 0.0, 3840.0, 1080.0, 0.0) is False
    # An 11.8px-wide icon hits the 0.5% bound instead (0.5% of 11.8 = 0.059, tighter than 1px).
    assert _is_identity_mask(11.8, 20.9, 0.0, 0.05, 0.0, 11.8, 20.9, 0.0) is True
    assert _is_identity_mask(11.8, 20.9, 0.0, 0.07, 0.0, 11.8, 20.9, 0.0) is False


def test_value_clean_allows_noop_edit_below_edit_count(deck):
    # A no-op masked-image edit: spec == the CURRENT composed crop (the identity fixture's
    # own frame, 300,100,120,60) with scale 1.0, so the written mask+image values EQUAL the
    # stored ones and neither archive's bytes change. Two archives are in the edit set
    # (230,231) but obj_diffs is 0 (< len(edits)). The relaxed self-check
    # (obj_diffs <= len(edits)) must still call this value-clean — the OLD `==` check would
    # have spuriously failed it.
    specs = [{"kind": "image", "kindIndex": 0, "x": 300.0, "y": 100.0, "w": 120.0, "h": 60.0,
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


@pytest.mark.parametrize("img_angle,mask_angle", [(90.0, 0.0), (0.0, 45.0)])
def test_rotated_masked_image_missed_not_written(tmp_path, img_angle, mask_angle):
    # A rotated image or mask is never an identity window (_is_identity_mask requires
    # both unrotated): hard miss, deck left untouched.
    deck = _build_rotated_mask_deck(tmp_path / "rot.key", img_angle=img_angle, mask_angle=mask_angle)
    original = deck.read_bytes()
    specs = [{"kind": "image", "kindIndex": 0, "x": 400.0, "y": 200.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.missed == 1 and res.applied == 0
    assert res.missed_specs == specs
    assert deck.read_bytes() == original  # rotated masked image left untouched


# --------------------------------------------------------------------------
# Group child scaling: own frame (_group_fields) + descendant walk
# (_group_child_scale_ops), pure-function level.
# --------------------------------------------------------------------------
def test_group_fields_pure_translation_when_size_not_scaled():
    # sx=sy=1, write_size=False must degenerate to the old translation-only rule.
    rec = {"id": "250"}
    stored = (500.0, 500.0, 30.0, 30.0, 0.0)
    reported = [500.0, 500.0, 30.0, 30.0]
    spec = {"x": 540.0, "y": 560.0}
    (obj_id, fields), = _group_fields(rec, spec, reported, stored, 1.0, 1.0, False)
    assert obj_id == "250"
    assert fields == {"pos_x": 540.0, "pos_y": 560.0}


def test_group_fields_scaled_moves_origin_and_writes_own_size():
    rec = {"id": "250"}
    stored = (500.0, 500.0, 30.0, 30.0, 0.0)
    reported = [480.0, 490.0, 15.0, 10.0]  # child-union denominator, not stored size
    spec = {"x": 540.0, "y": 560.0, "w": 60.0, "h": 40.0}
    sx, sy = 60.0 / 15.0, 40.0 / 10.0
    (obj_id, fields), = _group_fields(rec, spec, reported, stored, sx, sy, True)
    assert obj_id == "250"
    assert fields["pos_x"] == pytest.approx(540.0 + (500.0 - 480.0) * sx)
    assert fields["pos_y"] == pytest.approx(560.0 + (500.0 - 490.0) * sy)
    assert fields["size_w"] == pytest.approx(30.0 * sx)
    assert fields["size_h"] == pytest.approx(30.0 * sy)


def test_group_child_scale_ops_scales_leaves_and_nested_group():
    objects = {
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "super": _shape_super(10, 20, 100, 50)},
        "2": {"_pbtype": "TSWP.ShapeInfoArchive", "super": _shape_super(200, 30, 40, 40)},
        "3": {"_pbtype": "TSD.GroupArchive", "super": _geom(50, 60, 0, 0),
              "children": [{"identifier": 4}]},
        "4": {"_pbtype": "TSWP.ShapeInfoArchive", "super": _shape_super(5, 5, 20, 20)},
    }
    group = {"super": _geom(0, 0, 0, 0),
             "children": [{"identifier": 1}, {"identifier": 2}, {"identifier": 3}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 3.0, {}, "member")
    assert ok
    by_id = dict(ops)
    assert by_id["1"] == {"pos_x": 20.0, "pos_y": 60.0, "size_w": 200.0, "size_h": 150.0,
                          "natural_w": 200.0, "natural_h": 150.0}
    assert by_id["2"]["pos_x"] == 400.0 and by_id["2"]["pos_y"] == 90.0
    # nested group's own frame scaled once, about the top group's origin.
    assert by_id["3"] == {"pos_x": 100.0, "pos_y": 180.0, "size_w": 0.0, "size_h": 0.0}
    # nested leaf's LOCAL (parent-relative) position takes the SAME (sx,sy) — no
    # compounding across nesting levels.
    assert by_id["4"]["pos_x"] == 10.0 and by_id["4"]["pos_y"] == 15.0
    assert by_id["4"]["size_w"] == 40.0 and by_id["4"]["size_h"] == 60.0


def test_group_child_scale_ops_masked_child_writes_mask_naturalsize():
    objects = {
        "5": {"_pbtype": "TSD.ImageArchive", "mask": {"identifier": "6"}, "super": _geom(10, 10, 80, 40),
              "originalSize": {"width": 80.0, "height": 40.0}},
        "6": {"_pbtype": "TSD.MaskArchive", **_mask_super(2, 2, 60, 30)},
    }
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 5}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 2.0, {"5": "M", "6": "M"}, "M")
    assert ok
    by_id = dict(ops)
    assert by_id["6"] == {"pos_x": 4.0, "pos_y": 4.0, "size_w": 120.0, "size_h": 60.0,
                          "natural_w": 120.0, "natural_h": 60.0}
    assert by_id["5"]["pos_x"] == 20.0 and by_id["5"]["pos_y"] == 20.0
    assert by_id["5"]["size_w"] == 160.0 and by_id["5"]["size_h"] == 80.0
    assert by_id["5"]["natural_w"] == 160.0 and by_id["5"]["natural_h"] == 80.0


def test_group_child_scale_ops_unwritable_leaf_refuses_whole_group():
    # A callout-path leaf has no writable render-derived size: the WHOLE group is refused
    # rather than scale it while leaving its naturalSize stale.
    objects = {
        "1": {"_pbtype": "TSWP.ShapeInfoArchive",
              "super": {"pathsource": {"calloutPathSource": {}}, "super": _geom(10, 20, 100, 50)}},
    }
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 1}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 2.0, {}, "member")
    assert ops == [] and not ok


@pytest.mark.parametrize("img_angle,mask_angle", [(90.0, 0.0), (0.0, 45.0)])
def test_group_child_scale_ops_refuses_rotated_masked_child(img_angle, mask_angle):
    objects = {
        "5": {"_pbtype": "TSD.ImageArchive", "mask": {"identifier": "6"},
              "super": _geom(10, 10, 80, 40, angle=img_angle)},
        "6": {"_pbtype": "TSD.MaskArchive", "super": _geom(2, 2, 60, 30, angle=mask_angle)},
    }
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 5}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 2.0, {"5": "M", "6": "M"}, "M")
    assert not ok and ops == []


def test_group_child_scale_ops_rotated_leaf_uniform_ok_anisotropic_refused():
    # A rotated NON-masked leaf: fine under a uniform scale (rotation commutes), but an
    # anisotropic scale would shear it (angle isn't settable) → refuse the whole group.
    objects = {"1": {"_pbtype": "TSWP.ShapeInfoArchive",
                     "super": _shape_super(10, 20, 100, 50)}}
    objects["1"]["super"]["super"]["geometry"]["angle"] = 30.0
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 1}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 2.0, {}, "member")
    assert ok and dict(ops)["1"]["size_w"] == 200.0  # uniform: scaled
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 3.0, {}, "member")
    assert not ok and ops == []  # anisotropic + rotated: whole-group miss


def test_group_child_scale_ops_refuses_cross_member_mask():
    objects = {
        "5": {"_pbtype": "TSD.ImageArchive", "mask": {"identifier": "6"}, "super": _geom(10, 10, 80, 40)},
        "6": {"_pbtype": "TSD.MaskArchive", "super": _geom(2, 2, 60, 30)},
    }
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 5}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 2.0, {"5": "M", "6": "OTHER"}, "M")
    assert not ok and ops == []


# --------------------------------------------------------------------------
# Group child scaling: end-to-end through patch_slide_geometry.
# --------------------------------------------------------------------------
def _build_nested_group_deck(path):
    """group 250 (own frame == child union 500,500,80,65): leaves 251/252 plus
    nested group 253 (own leaf 254)."""
    leaf251 = _arch(251, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 30, 30)})
    leaf252 = _arch(252, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(60, 0, 20, 20)})
    leaf254 = _arch(254, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(5, 5, 10, 10)})
    nested = _arch(253, "TSD.GroupArchive", {"super": _geom(0, 50, 0, 0), "children": [{"identifier": 254}]})
    group = _arch(250, "TSD.GroupArchive", {"super": _geom(500, 500, 80, 65),
                  "children": [{"identifier": 251}, {"identifier": 252}, {"identifier": 253}]})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 250}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, group, leaf251, leaf252, nested, leaf254]))
    path.write_bytes(buf.getvalue())
    return path


def test_group_children_scaled_end_to_end(tmp_path):
    deck = _build_nested_group_deck(tmp_path / "nested.key")
    specs = [{"kind": "group", "kindIndex": 0, "x": 500.0, "y": 500.0, "w": 160.0, "h": 130.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert not res.refused and res.missed == 0
    assert res.applied == 5  # group + 2 leaves + nested group + its leaf
    assert res.value_clean and res.header_diffs == 0
    assert set(res.edited_ids) == {"250", "251", "252", "253", "254"}

    objects, _idf, _fi = _load_deck(deck)

    def xywh(oid):
        return _xywha(_geom_dict(objects[oid]))[:4]

    assert xywh("250") == pytest.approx((500.0, 500.0, 160.0, 130.0))
    assert xywh("251") == pytest.approx((0.0, 0.0, 60.0, 60.0))
    assert xywh("252") == pytest.approx((120.0, 0.0, 40.0, 40.0))
    assert xywh("253") == pytest.approx((0.0, 100.0, 0.0, 0.0))
    assert xywh("254") == pytest.approx((10.0, 10.0, 20.0, 20.0))


def test_group_zero_reported_size_falls_back_to_translation(deck):
    # rep w/h == 0 must not divide-by-zero; the guard falls back to pure
    # translation (no size/child writes), same as a spec lacking w/h.
    before = _composed(deck)
    specs = [{"kind": "group", "kindIndex": 0, "x": 540.0, "y": 560.0, "w": 100.0, "h": 100.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs, reported={("group", 0): [500.0, 500.0, 0.0, 0.0]})
    assert not res.refused and res.missed == 0
    assert set(res.edited_ids) == {"250"}  # only the group itself; no child scaled
    after = _composed(deck)
    assert [after[("group", 0)][k] for k in "xy"] == pytest.approx([540.0, 560.0])
    assert [after[("group", 0)][k] for k in "wh"] == pytest.approx(
        [before[("group", 0)]["w"], before[("group", 0)]["h"]]
    )


def _build_masked_group_deck(path, *, img_angle=0.0, mask_angle=0.0):
    mask = _arch(261, "TSD.MaskArchive", {"super": _geom(2, 2, 60, 30, angle=mask_angle)})
    img = _arch(260, "TSD.ImageArchive", {"mask": {"identifier": 261}, "super": _geom(10, 10, 80, 40, angle=img_angle)})
    group = _arch(250, "TSD.GroupArchive", {"super": _geom(500, 500, 80, 40), "children": [{"identifier": 260}]})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 250}]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, group, img, mask]))
    path.write_bytes(buf.getvalue())
    return path


def test_group_with_rotated_masked_child_misses_whole_group(tmp_path):
    deck = _build_masked_group_deck(tmp_path / "rotgrp.key", img_angle=90.0)
    original = deck.read_bytes()
    specs = [{"kind": "group", "kindIndex": 0, "x": 500.0, "y": 500.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.missed == 1 and res.applied == 0
    assert res.missed_specs == specs
    assert deck.read_bytes() == original  # unscalable child: whole group left untouched


# --------------------------------------------------------------------------
# Deck-level: patch_deck_geometry — one rewrite, per-slide refusal isolation,
# extra_member_edits, member-collision refusal, missed_specs.
# --------------------------------------------------------------------------
def test_patch_deck_geometry_one_rewrite_touches_only_edited_members(tmp_path):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    ino_before = deck.stat().st_ino
    with zipfile.ZipFile(deck) as z:
        doc_before = z.read("Index/Document.iwa")
        s1_before = z.read("Index/Slide-101.iwa")
        s2_before = z.read("Index/Slide-102.iwa")

    specs = {
        1: [{"kind": "shape", "kindIndex": 0, "x": 111.0, "y": 222.0, "role": "other"}],
        2: [{"kind": "shape", "kindIndex": 0, "x": 333.0, "y": 444.0, "role": "other"}],
    }
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert results[1].applied == 1 and not results[1].refused
    assert results[2].applied == 1 and not results[2].refused

    assert deck.stat().st_ino == ino_before  # in-place O_TRUNC, same inode
    with zipfile.ZipFile(deck) as z:
        assert z.read("Index/Document.iwa") == doc_before  # untouched member byte-identical
        assert z.read("Index/Slide-101.iwa") != s1_before
        assert z.read("Index/Slide-102.iwa") != s2_before

    objects, _idf, _fi = _load_deck(deck)
    after1 = {(r["kind"], r["kindIndex"]): r for r in compose_geometry(objects["101"], objects)}
    after2 = {(r["kind"], r["kindIndex"]): r for r in compose_geometry(objects["102"], objects)}
    assert [after1[("shape", 0)][k] for k in "xy"] == pytest.approx([111.0, 222.0])
    assert [after2[("shape", 0)][k] for k in "xy"] == pytest.approx([333.0, 444.0])


def test_patch_deck_geometry_refusal_isolates_one_slide(tmp_path):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    with zipfile.ZipFile(deck) as z:
        s1_before = z.read("Index/Slide-101.iwa")

    specs = {
        1: [{"kind": "shape", "kindIndex": 0, "x": 111.0, "y": 222.0, "role": "other"}],
        2: [{"kind": "shape", "kindIndex": 0, "x": 333.0, "y": 444.0, "role": "other"}],
    }
    source_counts = {1: {"shape": 5}, 2: {"shape": 1}}  # slide 1 mismatched, slide 2 matches
    results = patch_deck_geometry(deck, specs, source_counts_by_slide=source_counts, require_reconcile=True)
    assert results[1].refused and "reconcile" in (results[1].reason or "")
    assert not results[2].refused and results[2].applied == 1

    with zipfile.ZipFile(deck) as z:
        assert z.read("Index/Slide-101.iwa") == s1_before  # refused slide's member untouched


def test_patch_deck_geometry_accepts_extra_member_edits(tmp_path):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    new_doc_bytes = b"FAKE-STYLESHEET-BYTES"
    specs = {1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}]}
    results = patch_deck_geometry(deck, specs, require_reconcile=False,
                                  extra_member_edits={"Index/Document.iwa": new_doc_bytes})
    assert not results[1].refused
    assert results[0].applied == 1 and results[0].edited_ids == ["Index/Document.iwa"]
    with zipfile.ZipFile(deck) as z:
        assert z.read("Index/Document.iwa") == new_doc_bytes


def test_patch_deck_geometry_rejects_extra_edit_colliding_with_a_slide_member(tmp_path):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    original = deck.read_bytes()
    specs = {1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}]}
    with pytest.raises(ValueError):
        patch_deck_geometry(deck, specs, require_reconcile=False,
                            extra_member_edits={"Index/Slide-101.iwa": b"whatever"})
    assert deck.read_bytes() == original  # raised before any write


def test_patch_deck_geometry_refuses_slides_sharing_a_member(tmp_path):
    deck = _build_shared_member_deck(tmp_path / "shared.key")
    specs = {
        1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}],
        2: [{"kind": "shape", "kindIndex": 0, "x": 9.0, "y": 9.0, "role": "other"}],
    }
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert not results[1].refused and results[1].applied == 1
    assert results[2].refused and "member shared with slide 1" in (results[2].reason or "")
    objects, _idf, _fi = _load_deck(deck)
    after = {(r["kind"], r["kindIndex"]): r for r in compose_geometry(objects["101"], objects)}
    assert [after[("shape", 0)][k] for k in "xy"] == pytest.approx([1.0, 2.0])  # earlier slide wins


def test_patch_deck_geometry_reports_missed_specs(deck):
    specs = {1: [
        {"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "role": "other"},
        {"kind": "shape", "kindIndex": 5, "x": 1.0, "y": 1.0, "role": "other"},  # unknown kindIndex
    ]}
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    res = results[1]
    assert not res.refused
    assert res.applied == 1 and res.missed == 1
    assert len(res.missed_specs) == 1 and res.missed_specs[0]["kindIndex"] == 5


def test_patch_slide_geometry_wrapper_matches_deck_path(tmp_path):
    d1 = _build_deck(tmp_path / "a.key")
    d2 = _build_deck(tmp_path / "b.key")
    specs = [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 300.0, "h": 120.0, "role": "other"}]
    res1 = patch_slide_geometry(d1, 1, specs)
    res2 = patch_deck_geometry(d2, {1: specs}, require_reconcile=False)[1]
    assert (res1.applied, res1.missed, res1.value_clean, res1.obj_diffs, res1.header_diffs) == \
           (res2.applied, res2.missed, res2.value_clean, res2.obj_diffs, res2.header_diffs)
    assert res1.edited_ids == res2.edited_ids and res1.target_member == res2.target_member
    assert d1.read_bytes() == d2.read_bytes()


# --------------------------------------------------------------------------
# _slide_edits is pure (no I/O); _rewrite_members is the sole write seam.
# --------------------------------------------------------------------------
def test_slide_edits_writes_nothing(deck):
    original = deck.read_bytes()
    objects, id_to_file, _fi = _load_deck(deck)
    order = slide_order(objects)
    specs = [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "w": 300.0, "h": 120.0, "role": "other"}]
    target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None and len(edits) == 1 and not missed_specs
    assert target_member == "Index/Slide-100.iwa"
    assert deck.read_bytes() == original  # pure: no I/O happened


def test_line_no_pathsource_hard_misses(monkeypatch):
    # `_is_line` classification (iwa_kindindex) only ever fires off a `bezierPathSource` --
    # a "plain" kind that is always natural-writable -- so a genuinely pathsource-less
    # "line" record can never arise through normal derivation. Force one via
    # `compose_geometry`'s own `derive_kind_index` call to pin the guard itself: line
    # writes natural_w only, and without a path source `_write_natural_size` has nowhere
    # to put it, so this must hard-miss rather than write geometry.size alone.
    objects = {
        "100": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "1"}]},
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False, "super": _geom(0, 0, 140, 0)},
    }
    fake_records = [{"kind": "line", "kindIndex": 0, "id": "1", "order": 0}]
    monkeypatch.setattr("obed_edom.iwa_geometry.derive_kind_index", lambda slide, objs: fake_records)
    order = [("100", False)]
    id_to_file = {"1": "M"}
    specs = [{"kind": "line", "kindIndex": 0, "w": 140.0, "role": "other"}]
    _target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None
    assert missed_specs == specs
    assert edits == {}


def test_text_editable_bezier_autosize_width_only_hard_misses():
    # An editableBezier text box's naturalSize can only be rescaled with BOTH axes (the
    # nodes need both ratios): a width-only autosize write (stored h == 0.0 sentinel, so
    # `wants_h` is False) is unwritable even with a well-formed naturalSize.
    objects = {
        "100": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "1"}]},
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(700, 374, 0, 0, nw=165.52277, nh=23.0, kind="editable")},
    }
    order = [("100", False)]
    id_to_file = {"1": "M"}
    specs = [{"kind": "text", "kindIndex": 0, "w": 113.0, "role": "other"}]
    _target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None
    assert missed_specs == specs
    assert edits == {}


def test_text_editable_bezier_fixed_height_only_hard_misses():
    # h-only spec on a FIXED-height (stored h != 0, not the autosize sentinel) editableBezier
    # text box: the old guard only keyed on spec["w"], so this slipped through and would have
    # written size_h with naturalSize left stale (`_write_natural_size` bails when natural_w
    # is absent from fields). Degenerate naturalSize width also independently makes this
    # unwritable -- the guard must catch it either way.
    objects = {
        "100": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "1"}]},
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(700, 374, 0, 23.0, nw=0.0, nh=23.0, kind="editable")},
    }
    order = [("100", False)]
    id_to_file = {"1": "M"}
    specs = [{"kind": "text", "kindIndex": 0, "h": 40.0, "role": "other"}]
    _target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None
    assert missed_specs == specs
    assert edits == {}


def test_autosize_height_text_hard_misses_to_the_fallback():
    # Stored height == 0.0 (the autosize sentinel): naturalSize.height is Keynote's
    # render cache and only a live write refreshes it, so this is a hard miss
    # regardless of what the spec asks for (here: x + w only, no h at all).
    objects = {
        "100": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "1"}]},
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(700, 374, 0.0, 0.0, nw=300.3, nh=83.0)},
    }
    order = [("100", False)]
    id_to_file = {"1": "M"}
    specs = [{"kind": "text", "kindIndex": 0, "w": 113.4, "x": 107.15, "role": "other"}]
    _target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None
    assert missed_specs == specs
    assert edits == {}


def test_autosize_width_text_hard_misses_to_the_fallback():
    # Symmetric with the height sentinel: stored width == 0.0 is Keynote's own render
    # cache too (naturalSize.width), and only a live write refreshes it -- a real stored
    # height alongside it must not let this slip through as a silent partial write.
    objects = {
        "100": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "1"}]},
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(700, 374, 0.0, 34.0, nw=300.3, nh=34.0)},
    }
    order = [("100", False)]
    id_to_file = {"1": "M"}
    specs = [{"kind": "text", "kindIndex": 0, "h": 34.0, "y": 391.0, "role": "other"}]
    _target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None
    assert missed_specs == specs
    assert edits == {}


def test_fixed_height_text_is_still_patched_offline():
    # Same family, but a real (non-sentinel) stored height: still patched offline.
    objects = {
        "100": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "1"}]},
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(700, 374, 113.4, 34.0, nw=113.4, nh=34.0)},
    }
    order = [("100", False)]
    id_to_file = {"1": "M"}
    specs = [{"kind": "text", "kindIndex": 0, "w": 113.4, "h": 34.0, "x": 107.15, "role": "other"}]
    _target_member, edits, _soft, missed_specs, refuse_reason = _slide_edits(
        1, specs, objects, id_to_file, order)
    assert refuse_reason is None
    assert missed_specs == []
    fields = next(iter(edits.values()))
    assert {"size_w", "natural_w", "size_h", "natural_h"} <= fields.keys()


def test_group_with_autosize_text_child_refuses_whole_group():
    # A group whose child is an autosize text box (either axis 0.0): Keynote must lay it
    # out live, so the whole group hard-misses, same policy as an unwritable pathsource.
    objects_h = {
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(10, 20, 100, 0.0)},
    }
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 1}]}
    ops, ok = _group_child_scale_ops(group, objects_h, 2.0, 2.0, {}, "member")
    assert ops == [] and not ok

    objects_w = {
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(10, 20, 0.0, 100)},
    }
    ops, ok = _group_child_scale_ops(group, objects_w, 2.0, 2.0, {}, "member")
    assert ops == [] and not ok


def test_group_with_fixed_height_text_child_still_scales():
    # Regression guard for the slide-19 card groups: a child text box with a real
    # stored height (not the autosize sentinel) keeps scaling offline.
    objects = {
        "1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
              "super": _shape_super(10, 20, 100, 40.0)},
    }
    group = {"super": _geom(0, 0, 0, 0), "children": [{"identifier": 1}]}
    ops, ok = _group_child_scale_ops(group, objects, 2.0, 2.0, {}, "member")
    assert ok
    assert dict(ops)["1"]["size_h"] == 80.0


def test_rewrite_refuses_when_disk_space_short(tmp_path, monkeypatch):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    original = deck.read_bytes()
    specs = {
        1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}],
        2: [{"kind": "shape", "kindIndex": 0, "x": 3.0, "y": 4.0, "role": "other"}],
    }
    fake_usage = shutil.disk_usage(tmp_path)._replace(free=0)
    monkeypatch.setattr(iwa_write.shutil, "disk_usage", lambda _path: fake_usage)
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert results and all(r.refused and (r.reason or "").startswith("rewrite failed:") for r in results.values())
    assert deck.read_bytes() == original
    assert not list(deck.parent.glob(f".{deck.name}.obedwrite.tmp"))


def test_rewrite_refuses_when_free_space_below_2x_deck(tmp_path, monkeypatch):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    original = deck.read_bytes()
    specs = {
        1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}],
        2: [{"kind": "shape", "kindIndex": 0, "x": 3.0, "y": 4.0, "role": "other"}],
    }
    free = int(deck.stat().st_size * 1.5)  # below the 2.1x requirement
    fake_usage = shutil.disk_usage(tmp_path)._replace(free=free)
    monkeypatch.setattr(iwa_write.shutil, "disk_usage", lambda _path: fake_usage)
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert results and all(r.refused and (r.reason or "").startswith("rewrite failed:") for r in results.values())
    assert deck.read_bytes() == original
    assert not list(deck.parent.glob(f".{deck.name}.obedwrite.tmp"))


def test_rewrite_proceeds_when_free_space_above_2x_deck(tmp_path, monkeypatch):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    specs = {1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}]}
    free = int(deck.stat().st_size * 2.5)  # above the 2.1x requirement
    fake_usage = shutil.disk_usage(tmp_path)._replace(free=free)
    monkeypatch.setattr(iwa_write.shutil, "disk_usage", lambda _path: fake_usage)
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert not results[1].refused and results[1].applied == 1
    objects, _idf, _fi = _load_deck(deck)
    after = {(r["kind"], r["kindIndex"]): r for r in compose_geometry(objects["101"], objects)}
    assert [after[("shape", 0)][k] for k in "xy"] == pytest.approx([1.0, 2.0])


def test_rewrite_leaves_no_temp_file_on_success(deck):
    specs = {1: [{"kind": "shape", "kindIndex": 0, "x": 60.0, "y": 70.0, "role": "other"}]}
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert not results[1].refused
    assert not list(deck.parent.glob(f".{deck.name}.obedwrite.tmp"))


def test_copy_back_failure_raises_offline_write_corrupted_not_refused(tmp_path, monkeypatch):
    # A failure AFTER the truncating open must never surface as a refused PatchResult —
    # the deck is genuinely truncated at that point, so it has to reach the caller.
    deck = _build_two_slide_deck(tmp_path / "two.key")
    specs = {1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}]}
    real_copyfileobj = shutil.copyfileobj

    def flaky(src, dst, length=16384):
        if getattr(dst, "name", None) == str(deck):  # the copy-back write, not a build-phase stream
            raise RuntimeError("disk yanked mid copy-back")
        return real_copyfileobj(src, dst, length)

    monkeypatch.setattr(iwa_write.shutil, "copyfileobj", flaky)
    with pytest.raises(OfflineWriteCorrupted):
        patch_deck_geometry(deck, specs, require_reconcile=False)
    assert list(deck.parent.glob(f".{deck.name}.obedwrite.tmp"))  # kept for manual recovery


def test_rewrite_build_phase_failure_leaves_deck_untouched(tmp_path, monkeypatch):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    original = deck.read_bytes()
    specs = {
        1: [{"kind": "shape", "kindIndex": 0, "x": 1.0, "y": 2.0, "role": "other"}],
        2: [{"kind": "shape", "kindIndex": 0, "x": 3.0, "y": 4.0, "role": "other"}],
    }

    def boom(self, *a, **k):
        raise RuntimeError("disk full mid zip build")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", boom)  # only the edited-member path uses it
    results = patch_deck_geometry(deck, specs, require_reconcile=False)
    assert results and all(r.refused and (r.reason or "").startswith("rewrite failed:") for r in results.values())
    assert deck.read_bytes() == original
    assert not list(deck.parent.glob(f".{deck.name}.obedwrite.tmp"))


def test_rewrite_members_streams_unedited_without_full_buffering_read(tmp_path, monkeypatch):
    # Pins that unedited members go through ZipFile.open (streaming), never the
    # whole-member-buffering ZipFile.read — the thing that made the old per-slide
    # io.BytesIO rewrite unusable at deck scale.
    deck = _build_two_slide_deck(tmp_path / "two.key")
    with zipfile.ZipFile(deck) as z, z.open("Index/Slide-101.iwa") as f:
        target_before = f.read()
    new_bytes = target_before + b"\x00"

    def boom(self, *a, **k):
        raise AssertionError("must not buffer via ZipFile.read")

    monkeypatch.setattr(zipfile.ZipFile, "read", boom)
    _rewrite_members(deck, {"Index/Slide-101.iwa": new_bytes})

    with zipfile.ZipFile(deck) as z:
        with z.open("Index/Slide-101.iwa") as f:
            assert f.read() == new_bytes
        with z.open("Index/Document.iwa") as f:
            assert f.read()  # unedited member still readable and intact


def test_rewrite_members_refuses_unknown_extra_member(tmp_path):
    deck = _build_two_slide_deck(tmp_path / "two.key")
    original = deck.read_bytes()
    with pytest.raises(OfflineWriteRefused):
        _rewrite_members(deck, {"Index/DoesNotExist.iwa": b"x"})
    assert deck.read_bytes() == original
    assert not list(deck.parent.glob(f".{deck.name}.obedwrite.tmp"))


def test_patch_deck_geometry_rejects_slide_zero(deck):
    with pytest.raises(ValueError):
        patch_deck_geometry(deck, {0: []})


# --------------------------------------------------------------------------
# BUG 1: a Keynote Data/* member name written as raw UTF-8 bytes with the
# UTF-8 flag (bit 11) CLEAR must round-trip byte-for-byte, not get re-encoded
# from Python's CP437 mis-decode of it.
# --------------------------------------------------------------------------
def _parse_central_directory(raw: bytes) -> list[tuple[bytes, int]]:
    """[(raw name bytes, flag_bits)] straight off the zip central directory —
    deliberately NOT ``ZipFile.namelist()``, which would hide the bug by
    re-decoding through the same CP437/UTF-8 path under test."""
    idx = raw.rfind(b"PK\x05\x06")
    eocd = struct.unpack(zipfile.structEndArchive, raw[idx:idx + zipfile.sizeEndCentDir])
    cd_size, cd_offset = eocd[5], eocd[6]
    cd = raw[cd_offset:cd_offset + cd_size]
    out: list[tuple[bytes, int]] = []
    p = 0
    while p < len(cd):
        fields = struct.unpack(zipfile.structCentralDir, cd[p:p + zipfile.sizeCentralDir])
        flag_bits = fields[5]
        nlen, elen, clen = fields[12], fields[13], fields[14]
        name = cd[p + zipfile.sizeCentralDir:p + zipfile.sizeCentralDir + nlen]
        out.append((name, flag_bits))
        p += zipfile.sizeCentralDir + nlen + elen + clen
    return out


def _build_raw_name_deck(path):
    """Three members: an ASCII one we'll edit, a Keynote-style raw-UTF-8/bit-11-clear
    NBSP name (mis-decodes to CP437 mojibake), and a genuinely UTF-8-flagged non-ASCII
    name. Built via a same-length ASCII placeholder + byte substitution so no entry's
    offsets shift — the standard zipfile writer cannot itself emit bit-11-clear
    non-ASCII names, which is exactly the shape Keynote produces and we must preserve.
    """
    raw_name = b"Data/14. CHLI\xc2\xa0SD-80670.jpg"  # real UTF-8 NBSP, bit 11 clear (Keynote-style)
    placeholder = b"Data/14. CHLIXXSD-80670.jpg"      # same byte length as raw_name
    assert len(placeholder) == len(raw_name)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Index/Slide-100.iwa", b"ASCII-EDITED-MEMBER-CONTENT")
        z.writestr(placeholder.decode("ascii"), b"FAKEJPEGBYTES")
        z.writestr("unicode-é.jpg", b"unicode content")  # genuinely UTF-8-flagged (bit 11 set)
    raw = path.read_bytes()
    assert raw.count(placeholder) == 2  # local header + central directory
    path.write_bytes(raw.replace(placeholder, raw_name))
    return path, raw_name


def test_rewrite_preserves_raw_member_name_bytes(tmp_path):
    deck, raw_name = _build_raw_name_deck(tmp_path / "rawname.key")
    with zipfile.ZipFile(deck) as z:
        # Confirm the setup actually reproduces Keynote's mis-decode signature.
        decoded = {zi.filename: zi.flag_bits for zi in z.infolist()}
    assert decoded[raw_name.decode("cp437")] == 0
    assert decoded["unicode-é.jpg"] & 0x800

    before = _parse_central_directory(deck.read_bytes())

    _rewrite_members(deck, {"Index/Slide-100.iwa": b"NEW-EDITED-CONTENT"})

    after = _parse_central_directory(deck.read_bytes())
    assert before == after  # every name's bytes AND flag bit 11 identical, including the edited one's neighbours
    with zipfile.ZipFile(deck) as z:
        assert z.read("Index/Slide-100.iwa") == b"NEW-EDITED-CONTENT"


B_PRE_DECK = Path("output/write-gate/B_pre.key")
SPECS_SIDECAR = Path("output/write-gate/specs_slide9.json")


@pytest.mark.skipif(not (B_PRE_DECK.exists() and SPECS_SIDECAR.exists()), reason="local write-gate bank only")
def test_rewrite_preserves_nbsp_member_names_on_real_deck(tmp_path):
    # Sanity run on the real banked deck (4 known NBSP Data/* members): patch slide 9
    # like the write-gate smoke does, then confirm those 4 members' raw CD bytes
    # (name + flag bit 11) are untouched by the rewrite of an unrelated Slide-*.iwa member.
    import json
    import subprocess

    from scripts.write_gate_ab import load_specs_sidecar

    copy = tmp_path / "bpre_copy.key"
    subprocess.run(["cp", "-c", str(B_PRE_DECK), str(copy)], check=True)
    try:
        with zipfile.ZipFile(copy) as z:
            nbsp_names = [zi.filename for zi in z.infolist()
                         if not zi.filename.isascii() and zi.flag_bits & 0x800 == 0]
        assert len(nbsp_names) == 4

        before = _parse_central_directory(copy.read_bytes())

        sidecar = load_specs_sidecar(SPECS_SIDECAR)
        specs9 = sidecar["specs"]  # patch_deck_geometry bridges internally
        res = patch_deck_geometry(
            copy, {9: specs9}, reported_by_slide=None,
            source_counts_by_slide={9: sidecar["source_counts"]}, require_reconcile=True,
        )[9]
        assert not res.refused

        after = _parse_central_directory(copy.read_bytes())
        assert before == after  # NBSP members' name bytes + flags untouched by the slide-9 edit
    finally:
        copy.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Narrowed soft_fallbacks: a full masked-image spec (x AND y given) never
# consults `reported`, so a missing reported entry must not count.
# --------------------------------------------------------------------------
def test_soft_fallbacks_not_counted_for_masked_image_with_full_spec(deck):
    specs = [{"kind": "image", "kindIndex": 0, "x": 400.0, "y": 200.0, "w": 160.0, "h": 80.0, "role": "other"}]
    res = patch_slide_geometry(deck, 1, specs)
    assert res.applied and not res.refused
    assert res.soft_fallbacks == 0


# --------------------------------------------------------------------------
# patch_slide_builds: surgical builds/buildChunks/transition rewrite (Part F).
# --------------------------------------------------------------------------
def test_patch_slide_builds_drops_the_unwanted_builds_and_leaves_the_rest(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    result = patch_slide_builds(deck, {"100": {"builds": ["901"], "buildChunks": ["911"], "transition": None}})
    assert not result["refused"]
    objects, _id_to_file, _file_ids = _load_deck(deck)
    assert objects["100"]["builds"] == [{"identifier": "901"}]
    assert objects["100"]["buildChunks"] == [{"identifier": "911"}]
    # The untouched slide keeps every one of its own builds.
    assert objects["101"]["builds"] == [{"identifier": "903"}, {"identifier": "904"}]


def test_patch_slide_builds_writes_the_source_transition_verbatim(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    new_transition = _transition_dict("apple:magic-move-implied-motion-path", 1.2)
    result = patch_slide_builds(
        deck,
        {"100": {"builds": ["900", "901", "902"], "buildChunks": ["910", "911", "912"], "transition": new_transition}},
    )
    assert not result["refused"]
    objects, _id_to_file, _file_ids = _load_deck(deck)
    assert objects["100"]["transition"] == new_transition


def test_patch_slide_builds_refuses_a_transition_holding_a_reference(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    referencing = {"attributes": {"customImage": {"identifier": "777"}}}
    result = patch_slide_builds(
        deck,
        {"100": {"builds": ["900"], "buildChunks": ["910"], "transition": referencing}},
    )
    assert result["refused"]
    assert deck.read_bytes() == before  # deck untouched


def test_patch_slide_builds_reorders_kept_builds_into_source_order(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    # An arbitrary (non-output, non-sorted) order: the write must preserve exactly
    # what it is given -- ordering the survivors by source index is plan_build_patch's
    # job (tested directly, no deck needed, in test_iwa_builds.py).
    result = patch_slide_builds(
        deck,
        {"100": {"builds": ["902", "900", "901"], "buildChunks": ["912", "910", "911"], "transition": None}},
    )
    assert not result["refused"]
    objects, _id_to_file, _file_ids = _load_deck(deck)
    assert objects["100"]["builds"] == [{"identifier": "902"}, {"identifier": "900"}, {"identifier": "901"}]
    assert objects["100"]["buildChunks"] == [{"identifier": "912"}, {"identifier": "910"}, {"identifier": "911"}]


def test_patch_slide_builds_value_clean_touches_only_the_slide_archives(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    with zipfile.ZipFile(deck) as z:
        before = {name: z.read(name) for name in z.namelist()}
    result = patch_slide_builds(deck, {"100": {"builds": ["901"], "buildChunks": ["911"], "transition": None}})
    assert not result["refused"]
    with zipfile.ZipFile(deck) as z:
        after = {name: z.read(name) for name in z.namelist()}
    assert set(before) == set(after)  # no member added or removed
    changed = [name for name in before if before[name] != after[name]]
    assert changed == ["Index/Slide-100.iwa"]


def test_patch_slide_builds_refuses_an_unknown_build_id(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    result = patch_slide_builds(deck, {"100": {"builds": ["99999"], "buildChunks": [], "transition": None}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_slide_builds_refuses_a_build_id_of_the_wrong_type(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    # "220" is a real object in the SAME member, but a TSWP.ShapeInfoArchive, not a build.
    result = patch_slide_builds(deck, {"100": {"builds": ["220"], "buildChunks": ["911"], "transition": None}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_slide_builds_refuses_a_build_id_from_another_member(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    # "903" is a real KN.BuildArchive, but lives in slide 101's member, not 100's.
    result = patch_slide_builds(deck, {"100": {"builds": ["903"], "buildChunks": ["911"], "transition": None}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_slide_builds_refuses_a_buildchunk_id_of_the_wrong_type(tmp_path):
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    result = patch_slide_builds(deck, {"100": {"builds": ["901"], "buildChunks": ["230"], "transition": None}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_slide_builds_patches_two_slides_sharing_one_member(tmp_path):
    deck = _build_builds_shared_member_deck(tmp_path / "shared_builds.key")
    result = patch_slide_builds(
        deck,
        {
            "100": {"builds": [], "buildChunks": [], "transition": None},
            "101": {"builds": [], "buildChunks": [], "transition": None},
        },
    )
    assert not result["refused"]
    objects, _id_to_file, _file_ids = _load_deck(deck)
    # An empty repeated field round-trips as absent, not `[]` -- both are "no builds".
    assert not objects["100"].get("builds")
    assert not objects["101"].get("builds")


def test_patch_slide_builds_self_check_gate_refuses_a_forced_collateral_edit(tmp_path, monkeypatch):
    """Wrap IWAFile.from_dict so the write ALSO mutates an untouched archive (901)
    in the same member -- the self-check gate must catch this and refuse, deck
    untouched, exactly as the live probe proved (`build_patch.py`)."""
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    real_from_dict = IWAFile.from_dict.__func__

    def _corrupting_from_dict(cls, data):
        mutated = copy.deepcopy(data)
        for ch in mutated["chunks"]:
            for arch in ch["archives"]:
                if str(arch["header"]["identifier"]) == "901":
                    arch["objects"][0]["duration"] = 999.0
        return real_from_dict(cls, mutated)

    monkeypatch.setattr(IWAFile, "from_dict", classmethod(_corrupting_from_dict))
    result = patch_slide_builds(deck, {"100": {"builds": ["901"], "buildChunks": ["911"], "transition": None}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_slide_builds_self_check_gate_refuses_a_forced_header_edit(tmp_path, monkeypatch):
    """Wrap IWAFile.from_dict so the write ALSO mutates the HEADER (not the objects)
    of an untouched archive (901) in the same member -- the self-check gate's
    header comparison must catch this on its own. Dropping that half of the gate
    left the whole suite green (G1)."""
    deck = _build_builds_deck(tmp_path / "builds.key")
    before = deck.read_bytes()
    real_from_dict = IWAFile.from_dict.__func__

    def _corrupting_from_dict(cls, data):
        mutated = copy.deepcopy(data)
        for ch in mutated["chunks"]:
            for arch in ch["archives"]:
                if str(arch["header"]["identifier"]) == "901":
                    arch["header"]["shouldMerge"] = True
        return real_from_dict(cls, mutated)

    monkeypatch.setattr(IWAFile, "from_dict", classmethod(_corrupting_from_dict))
    result = patch_slide_builds(deck, {"100": {"builds": ["901"], "buildChunks": ["911"], "transition": None}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_patch_slide_builds_no_op_write_for_one_slide_does_not_refuse_the_call(tmp_path):
    """A byte-identical no-op write for one slide in a shared member must not
    refuse the whole call: `changed` need only be a SUBSET of the intended slides,
    not equal to it (G5)."""
    deck = _build_builds_shared_member_deck(tmp_path / "shared_builds.key")
    result = patch_slide_builds(
        deck,
        {
            "100": {"builds": [], "buildChunks": [], "transition": None},  # a real change
            "101": {"builds": ["901"], "buildChunks": ["911"],
                     "transition": _transition_dict("apple:dissolve", 0.5)},  # byte-identical no-op
        },
    )
    assert not result["refused"]
    objects, _id_to_file, _file_ids = _load_deck(deck)
    assert not objects["100"].get("builds")
    assert objects["101"]["builds"] == [{"identifier": "901"}]


def test_deck_builds_orders_chunk_ids_by_the_slides_own_buildchunks_order(tmp_path):
    deck = _build_multi_chunk_deck(tmp_path / "chunks.key")
    by_number = deck_builds(deck)
    assert by_number[1]["builds"][0]["chunkIds"] == ["951", "950"]


def test_deck_builds_drops_a_chunk_not_listed_in_the_slides_own_buildchunks(tmp_path):
    """A KN.BuildChunkArchive that references the build but is absent from the
    slide's own buildChunks is dropped, not silently appended (G7)."""
    deck = _build_orphan_chunk_deck(tmp_path / "orphan.key")
    by_number = deck_builds(deck)
    assert by_number[1]["builds"][0]["chunkIds"] == ["950"]


# --------------------------------------------------------------------------
# restore_source_builds (remap_keynote.py): the production entry point.
# --------------------------------------------------------------------------
def test_restore_source_builds_with_no_reuse_slides_is_a_noop_that_still_verifies(tmp_path, monkeypatch):
    source = _build_builds_deck(tmp_path / "source.key")
    dest = _build_builds_deck(tmp_path / "dest.key")
    real_deck_builds = iwa_builds.deck_builds
    calls: list = []

    def counting_deck_builds(path, *, deck=None):
        calls.append(path)
        return real_deck_builds(path, deck=deck)

    monkeypatch.setattr(iwa_builds, "deck_builds", counting_deck_builds)
    messages = []
    result = restore_source_builds(dest, source, set(), messages.append)
    assert result == {
        "skipped": False, "kept": 0, "dropped": 0, "retimed": 0, "report": [], "shortfalls": [],
    }
    objects, _id_to_file, _file_ids = _load_deck(dest)
    assert objects["100"]["builds"] == [{"identifier": "900"}, {"identifier": "901"}, {"identifier": "902"}]
    assert any("Builds follow source: 0 kept, 0 dropped, 0 transition(s)" in m for m in messages)
    # No reuse slides -> `plans` is empty -> out_after reuses out_by_number instead of
    # paying an unconditional second dest decode (G3).
    assert len(calls) == 2


def test_restore_source_builds_excludes_a_skipped_transition_from_the_raise(tmp_path, monkeypatch):
    """A source transition of None, alongside a REAL build change on the same
    slide (a no-op plan would be refused by the self-check gate -- G5), must not
    raise: the report-side transitionSkipped exclusion (F1) must also apply on
    the raise side. Dropping the skipped-slide exclusion, or the WARNING `say`,
    left the suite green (G2)."""
    dest = _build_builds_deck(tmp_path / "dest.key")
    source = _build_builds_deck(tmp_path / "source.key")
    real_deck_builds = iwa_builds.deck_builds
    src_map = copy.deepcopy(real_deck_builds(source))
    src_map[1]["builds"] = [b for b in src_map[1]["builds"] if b["buildId"] == "900"]
    src_map[1]["transition"] = None

    def fake_deck_builds(path, *, deck=None):
        if Path(path).name == source.name:
            return copy.deepcopy(src_map)
        return real_deck_builds(path, deck=deck)

    monkeypatch.setattr(iwa_builds, "deck_builds", fake_deck_builds)
    messages = []
    result = restore_source_builds(dest, source, {1}, messages.append)
    assert result["skipped"] is False
    assert any("WARNING builds: slide 1 transition not restored (source has none)" in m for m in messages)
