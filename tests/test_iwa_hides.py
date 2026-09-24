"""Offline hide-deletion tests (obed_edom.iwa_hides.patch_deck_hides), no Keynote.

A synthetic but REAL .key is serialized through keynote_parser (the codec the writer
uses), with a ``TSP.PackageMetadata`` whose component tables (uuid entries,
dataReferences, externalReferences) are derived from the archive headers exactly as
Keynote keeps them (invariants I1-I6 of .agents/plans/pass1_hides_offline.plan.md).

Deck layout (default ``_build``):
- Index/DocumentStylesheet.iwa (component 950): stylesheet root 950, styles 900 (media),
  901 (shape), 902 (slide).
- Index/Document.iwa (component 2): show 2, slide nodes 10/11/12 -> slides 101/102/103.
- Index/Slide-101.iwa (slide 1): text 300 "Keep" (storage 310) survives; shape 301
  "Hide me" (storage 311); image 302 (data 50, mask 312); image 303 (data 51) survives;
  image 304 (data 51, shared with 303); image 305 (data 52, shared with slide 2's 400);
  group 306 with child text 320 (storage 321).
  Hides: shape 0, image 0, image 2, image 3, group 0.
- Index/Slide-102.iwa (slide 2): image 400 (data 52) survives; text 401 "Bye" (storage
  411); image 402 (data 53, shared with the template slide). Hides: text 0, image 1.
- Index/Slide-103.iwa (slide 3): text 500 "Stay" (storage 510) survives; image 501 (data
  54). Hide: image 0. Deleting 501 leaves style 900 unreferenced from that member, so
  the component's externalReferences entry for 900 must go.
- Index/TemplateSlide-600.iwa: template slide 600 with image 601 (data 53).
- Data/: 50 is non-ASCII with ZIP flag bit 11 clear (CP437 mojibake in namelist()).

Orphans after the default patch: 50 (only 302) and 54 (only 501). 51/52/53 are shared
with a survivor, another slide, or the template, and stay.
"""
from __future__ import annotations

import base64
import copy
import io
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from keynote_parser.codec import IWAFile  # noqa: E402

from obed_edom import iwa_hides, iwa_write  # noqa: E402
from obed_edom.iwa_hides import HidesResult, HidesWriteFailed, patch_deck_hides  # noqa: E402
from obed_edom.iwa_kindindex import deck_kind_counts  # noqa: E402
from obed_edom.iwa_write import (  # noqa: E402
    OfflineWriteCorrupted,
    OfflineWriteRefused,
    _RawNameZipInfo,
    _rewrite_members,
    patch_deck_geometry,
)
from obed_edom.offline_inspect import offline_wall_payload  # noqa: E402
from test_iwa_write import _arch, _geom, _member, _shape_super, _transition_dict  # noqa: E402

SHEET = "Index/DocumentStylesheet.iwa"
DOC = "Index/Document.iwa"
META = "Index/Metadata.iwa"
S1, S2, S3 = "Index/Slide-101.iwa", "Index/Slide-102.iwa", "Index/Slide-103.iwa"
TMPL = "Index/TemplateSlide-600.iwa"
PM_ID = 5
DMM_ID = 7

DATA_NAMES = {
    50: "Data/ümlaut-50.png",
    51: "Data/plain-51.png",
    52: "Data/shared-52.png",
    53: "Data/tmpl-53.png",
    54: "Data/solo-54.png",
}
RAW_BIT11_CLEAR = {50}

HIDES = {
    1: [
        {"role": "hide", "kind": "shape", "kindIndex": 0},
        {"role": "hide", "kind": "image", "kindIndex": 0},
        {"role": "hide", "kind": "image", "kindIndex": 2},
        {"role": "hide", "kind": "image", "kindIndex": 3},
        {"role": "hide", "kind": "group", "kindIndex": 0},
    ],
    2: [
        {"role": "hide", "kind": "text", "kindIndex": 0},
        {"role": "hide", "kind": "image", "kindIndex": 1},
    ],
    3: [{"role": "hide", "kind": "image", "kindIndex": 0}],
}
SUBTREE_1 = {"301", "311", "302", "312", "304", "305", "306", "320", "321"}
SUBTREE_2 = {"401", "411", "402"}
SUBTREE_3 = {"501"}


def _a(ident, pbtype, obj, refs=(), data=()):
    arch = _arch(ident, pbtype, obj)
    mi = arch["header"]["messageInfos"][0]
    mi.pop("identifier", None)
    if refs:
        mi["objectReferences"] = [str(r) for r in refs]
    if data:
        mi["dataReferences"] = [str(d) for d in data]
    return arch


def _text(ident, storage, text, *, textbox=True, style=901, parent=None, at=None, **extra):
    """A text/shape box with owned storage. ``parent`` is a body-only weak ref (Keynote
    never header-lists a drawable's parent)."""
    x, y = at if at is not None else ((ident % 100) * 10, 10)
    shape = _shape_super(x, y, 100, 40)
    if parent is not None:
        shape["super"]["parent"] = {"identifier": parent}
    obj = {"isTextBox": textbox, "ownedStorage": {"identifier": storage},
           "super": {"style": {"identifier": style}, **shape}, **extra}
    return [
        _a(ident, "TSWP.ShapeInfoArchive", obj, refs=[storage, style]),
        _a(storage, "TSWP.StorageArchive", {"text": [text]}),
    ]


def _image(ident, data, *, mask=None, style=900, at=None):
    x, y = at if at is not None else ((ident % 100) * 10, 0)
    obj = {"data": {"identifier": data}, "style": {"identifier": style}, "super": _geom(x, y, 50, 50)}
    refs = [style]
    if mask is not None:
        obj["mask"] = {"identifier": mask}
        refs.insert(0, mask)
    return _a(ident, "TSD.ImageArchive", obj, refs=refs, data=[data])


def _slide(ident, z, *, style=902):
    zl = [{"identifier": i} for i in z]
    return _a(ident, "KN.SlideArchive",
              {"style": {"identifier": style}, "drawablesZOrder": zl, "ownedDrawables": copy.deepcopy(zl)},
              refs=[style, *z])


def _members() -> dict[str, list[dict]]:
    return {
        SHEET: [
            _a(950, "TSS.StylesheetArchive",
               {"styles": [{"identifier": 900}, {"identifier": 901}, {"identifier": 902}]}, refs=[900, 901, 902]),
            _a(900, "TSD.MediaStyleArchive", {}),
            _a(901, "TSWP.ShapeStyleArchive", {}),
            _a(902, "KN.SlideStyleArchive", {}),
        ],
        DOC: [
            _a(2, "KN.ShowArchive",
               {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}, {"identifier": 12}]}},
               refs=[10, 11, 12, 13]),
            _a(10, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False}, refs=[101]),
            _a(11, "KN.SlideNodeArchive", {"slide": {"identifier": 102}, "isSkipped": False}, refs=[102]),
            _a(12, "KN.SlideNodeArchive", {"slide": {"identifier": 103}, "isSkipped": False}, refs=[103]),
            _a(13, "KN.SlideNodeArchive", {"slide": {"identifier": 600}, "isSkipped": False}, refs=[600]),
        ],
        S1: [
            _slide(101, [300, 301, 302, 303, 304, 305, 306]),
            *_text(300, 310, "Keep"),
            *_text(301, 311, "Hide me", textbox=False),
            _image(302, 50, mask=312),
            _a(312, "TSD.MaskArchive", {"super": {"parent": {"identifier": 302}}}, refs=[302]),
            _image(303, 51),
            _image(304, 51),
            _image(305, 52),
            _a(306, "TSD.GroupArchive", {"children": [{"identifier": 320}], "super": {}}, refs=[320]),
            *_text(320, 321, "G child", parent=306),
        ],
        S2: [
            _slide(102, [400, 401, 402]),
            _image(400, 52),
            *_text(401, 411, "Bye"),
            _image(402, 53),
        ],
        S3: [
            _slide(103, [500, 501]),
            *_text(500, 510, "Stay"),
            _image(501, 54),
        ],
        TMPL: [
            _slide(600, [601]),
            _image(601, 53),
        ],
    }


def _locator(member: str) -> tuple[str, str | None]:
    base = member.rsplit("/", 1)[-1][:-4]
    if "-" in base:
        return base.split("-", 1)[0], base
    return base, None


def _component_tables(members: dict[str, list[dict]]) -> list[dict]:
    """Keynote-shaped components derived straight from the archive headers."""
    member_of = {str(a["header"]["identifier"]): m for m, archs in members.items() for a in archs}
    root_of = {m: str(archs[0]["header"]["identifier"]) for m, archs in members.items()}
    comps = []
    for member, archs in members.items():
        preferred, locator = _locator(member)
        comp = {"identifier": root_of[member], "preferredLocator": preferred}
        if locator:
            comp["locator"] = locator
        uuids, data_refs, ext = [], {}, []
        for a in archs:
            aid = str(a["header"]["identifier"])
            uuids.append({"identifier": aid, "uuid": {"lower": aid, "upper": "7"}})
            for mi in a["header"]["messageInfos"]:
                counts: dict[str, int] = {}
                for d in mi.get("dataReferences") or []:
                    counts[d] = counts.get(d, 0) + 1
                for d, c in counts.items():
                    data_refs.setdefault(d, []).append({"objectIdentifier": aid, "count": c})
                for t in mi.get("objectReferences") or []:
                    tm = member_of.get(t)
                    if tm is None or tm == member:
                        continue
                    entry = {"componentIdentifier": root_of[tm]}
                    if t != root_of[tm]:
                        entry["objectIdentifier"] = t
                    if entry not in ext:
                        ext.append(entry)
        comp["objectUuidMapEntries"] = uuids
        if data_refs:
            comp["dataReferences"] = [{"dataIdentifier": d, "objectReferenceList": lst} for d, lst in data_refs.items()]
        if member.startswith("Index/Slide") or member.startswith("Index/Template"):
            ext.append({"componentIdentifier": "950", "isWeak": True})
        if ext:
            comp["externalReferences"] = ext
        comps.append(comp)
    return comps


def _build(path: Path, *, mutate=None, meta_mutate=None, data_names=None, dmm=()) -> Path:
    members = _members()
    if mutate:
        mutate(members)
    data_names = dict(DATA_NAMES if data_names is None else data_names)
    pm = {
        "lastObjectIdentifier": "1000",
        "components": _component_tables(members),
        "datas": [
            {"identifier": str(d), "digest": base64.b64encode(bytes([d]) * 20).decode(),
             "preferredFileName": name.rsplit("/", 1)[-1], "fileName": name.rsplit("/", 1)[-1]}
            for d, name in sorted(DATA_NAMES.items())
        ],
        "dataMetadataMap": {"identifier": DMM_ID},
    }
    if meta_mutate:
        meta_mutate(pm)
    dmm_obj = {"dataMetadataEntries": [{"dataIdentifier": str(d), "dataMetadata": {"identifier": 8}} for d in dmm]}
    meta = [_a(PM_ID, "TSP.PackageMetadata", pm, refs=[DMM_ID]), _a(DMM_ID, "TSP.DataMetadataMap", dmm_obj)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for member, archs in members.items():
            z.writestr(member, _member(archs))
        z.writestr(META, _member(meta))
        for d, name in sorted(data_names.items()):
            payload = bytes([d]) * 64
            if d in RAW_BIT11_CLEAR:
                info = _RawNameZipInfo(name.encode("utf-8").decode("cp437"))
                info._raw_name = name.encode("utf-8")
                z.writestr(info, payload)
            else:
                z.writestr(name, payload)
    path.write_bytes(buf.getvalue())
    return path


def _payload(path: Path) -> dict[int, list[dict]]:
    """The offline reader's payload items per slide, each carrying its source ``iwaId``/``iwaUuid``."""
    return {s["number"]: s["items"] for s in offline_wall_payload(path)["slides"]}


def _run(path: Path, hides=None, *, items=None, counts=None, **kw) -> HidesResult:
    hides = HIDES if hides is None else hides
    return patch_deck_hides(
        path, hides,
        source_counts_by_slide=deck_kind_counts(path) if counts is None else counts,
        items_by_slide=_payload(path) if items is None else items,
        **kw,
    )


def _raw_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _raw_name_bytes(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {zi.filename: zi.orig_filename.encode("cp437") if zi.flag_bits & 0x800 == 0 and not zi.filename.isascii()
                else zi.filename.encode("utf-8") for zi in zf.infolist()}


def _decoded(path: Path, member: str) -> dict[str, dict]:
    with zipfile.ZipFile(path) as zf:
        d = IWAFile.from_buffer(zf.read(member), member).to_dict()
    return {str(a["header"]["identifier"]): a for ch in d["chunks"] for a in ch["archives"]}


def _pm(path: Path) -> dict:
    return _decoded(path, META)[str(PM_ID)]["objects"][0]


def _comp(pm: dict, ident: str) -> dict:
    return next(c for c in pm["components"] if str(c["identifier"]) == ident)


def _z(path: Path, member: str, slide_id: str) -> tuple[list[str], list[str], list[str]]:
    arch = _decoded(path, member)[slide_id]
    obj = arch["objects"][0]
    return ([str(r["identifier"]) for r in obj.get("drawablesZOrder") or []],
            [str(r["identifier"]) for r in obj.get("ownedDrawables") or []],
            [str(r) for r in arch["header"]["messageInfos"][0].get("objectReferences") or []])


def _data_member_present(path: Path, data_id: int) -> bool:
    with zipfile.ZipFile(path) as zf:
        return any(n.endswith(f"-{data_id}.png") for n in
                   (x.encode("cp437").decode("utf-8") if not x.isascii() else x for x in zf.namelist()))


@pytest.fixture()
def deck(tmp_path):
    return _build(tmp_path / "hides.key")


# ---------------------------------------------------------------- B1-B4: happy path


def test_b1_shape_hide_deletes_drawable_storage_lists_header_uuid_and_tables(deck):
    before_pm = _pm(deck)
    res = _run(deck)
    assert not res.slides[1].refused, res.slides[1].reason
    assert res.slides[1].deleted == 5
    assert set(res.slides[1].removed_ids) == SUBTREE_1

    archs = _decoded(deck, S1)
    assert not (SUBTREE_1 & set(archs))
    assert {"300", "310", "303", "101"} <= set(archs)
    z, owned, header = _z(deck, S1, "101")
    assert z == ["300", "303"] and owned == z
    assert header == ["902", "300", "303"]

    comp = _comp(_pm(deck), "101")
    assert {e["identifier"] for e in comp["objectUuidMapEntries"]} == set(archs)
    data = {(e["dataIdentifier"], o["objectIdentifier"]) for e in comp["dataReferences"]
            for o in e["objectReferenceList"]}
    assert data == {("51", "303")}
    old_ext = _comp(before_pm, "101")["externalReferences"]
    assert comp["externalReferences"] == old_ext


def test_b1_external_reference_dropped_when_no_survivor_needs_it(deck):
    _run(deck)
    ext = _comp(_pm(deck), "103")["externalReferences"]
    assert {"componentIdentifier": "950", "objectIdentifier": "900"} not in ext
    assert {"componentIdentifier": "950", "objectIdentifier": "901"} in ext
    assert {"componentIdentifier": "950", "isWeak": True} in ext


def test_b2_image_and_mask_removed_shared_data_kept_orphan_purged(deck):
    res = _run(deck)
    archs = _decoded(deck, S1)
    assert "302" not in archs and "312" not in archs
    datas = {d["identifier"] for d in _pm(deck)["datas"]}
    assert datas == {"51", "52", "53"}
    assert not _data_member_present(deck, 50) and not _data_member_present(deck, 54)
    for kept in (51, 52, 53):
        assert _data_member_present(deck, kept)
    assert sorted(res.dropped_data) == sorted(
        [DATA_NAMES[50].encode("utf-8").decode("cp437"), DATA_NAMES[54]])


def test_b3_group_hide_removes_children(deck):
    _run(deck)
    archs = _decoded(deck, S1)
    assert not ({"306", "320", "321"} & set(archs))


def test_b4_untouched_members_byte_identical(deck):
    before = _raw_members(deck)
    names_before = _raw_name_bytes(deck)
    res = _run(deck)
    after = _raw_members(deck)
    touched = set(res.members) | set(res.dropped_data)
    assert set(res.members) == {S1, S2, S3, META}
    assert set(after) == set(before) - set(res.dropped_data)
    for name in set(before) - touched:
        assert after[name] == before[name], name
    names_after = _raw_name_bytes(deck)
    for name in names_after:
        assert names_after[name] == names_before[name]


def test_all_slides_patched_with_counts_and_reconcile(deck):
    res = _run(deck)
    assert {n: (s.refused, s.deleted) for n, s in res.slides.items()} == {1: (False, 5), 2: (False, 2), 3: (False, 1)}
    assert set(res.slides[2].removed_ids) == SUBTREE_2
    assert set(res.slides[3].removed_ids) == SUBTREE_3
    counts = deck_kind_counts(deck)
    assert counts[1] == {"text": 1, "image": 1}
    assert counts[2] == {"image": 1}
    assert counts[3] == {"text": 1}


def test_b13_metadata_survivors_keep_order_and_equal_recompute(deck):
    before = _pm(deck)
    res = _run(deck, verify=True)
    removed = set().union(*(set(s.removed_ids) for s in res.slides.values()))
    after = _pm(deck)
    for b, a in zip(before["components"], after["components"]):
        want_uuids = [e for e in b["objectUuidMapEntries"] if e["identifier"] not in removed]
        assert a["objectUuidMapEntries"] == want_uuids
    members = _members()
    for m in (S1, S2, S3):
        for aid in removed:
            members[m] = [x for x in members[m] if str(x["header"]["identifier"]) != aid]
    members[S1][0] = _slide(101, [300, 303])
    members[S2][0] = _slide(102, [400])
    members[S3][0] = _slide(103, [500])
    recomputed = {c["identifier"]: c for c in _component_tables(members)}
    for comp in after["components"]:
        want = recomputed[comp["identifier"]]
        assert comp.get("dataReferences") == want.get("dataReferences"), comp["identifier"]
        assert comp.get("externalReferences") == want.get("externalReferences"), comp["identifier"]


def test_verify_mode_passes(deck):
    res = _run(deck, verify=True)
    assert all(not s.refused for s in res.slides.values())


def test_no_hides_is_a_noop_without_decode(deck, monkeypatch):
    before = _raw_members(deck)
    monkeypatch.setattr(iwa_hides, "_load_model", lambda *_a, **_k: pytest.fail("decoded"))
    res = patch_deck_hides(deck, {1: []}, source_counts_by_slide={}, items_by_slide={})
    assert res.slides[1].deleted == 0 and not res.slides[1].refused and res.members == []
    assert _raw_members(deck) == before


# ---------------------------------------------------------------- B5/B12/B14: refusals


def _add(member, *archs):
    def mutate(members):
        members[member].extend(archs)
    return mutate


def _replace(member, ident, arch):
    def mutate(members):
        members[member] = [arch if str(a["header"]["identifier"]) == str(ident) else a for a in members[member]]
    return mutate


def _chain(*fns):
    def mutate(members):
        for fn in fns:
            fn(members)
    return mutate


def _build_ref(members):
    members[S1][0] = _a(101, "KN.SlideArchive", {
        **members[S1][0]["objects"][0], "builds": [{"identifier": 330}]}, refs=[902, 300, 301, 302, 303, 304, 305, 306, 330])
    members[S1].append(_a(330, "KN.BuildArchive", {"drawable": {"identifier": 301}, "delivery": "", "attributes": {}},
                          refs=[301]))


def _shared_mask(members):
    members[S1][0] = _slide(101, [300, 301, 302, 303, 304, 305, 306, 307])
    members[S1].append(_image(307, 53, mask=312))


def _connection_line(members):
    members[S1][0] = _slide(101, [300, 301, 302, 303, 304, 305, 306, 308])
    members[S1].append(_a(308, "TSD.ConnectionLineArchive",
                          {"connectedFrom": {"identifier": 301}, "super": {"super": {}}}, refs=[301]))


def _dual_target(members):
    obj = {"isTextBox": True, "ownedStorage": {"identifier": 411},
           "super": {"style": {"identifier": 901}, **_shape_super(0, 0, 50, 20, kind="editable")}}
    members[S2] = [a if str(a["header"]["identifier"]) != "401"
                   else _a(401, "TSWP.ShapeInfoArchive", obj, refs=[411, 901]) for a in members[S2]]


def _non_list_slide_field(members):
    obj = members[S1][0]["objects"][0]
    members[S1][0] = _a(101, "KN.SlideArchive", {**obj, "titlePlaceholder": {"identifier": 301}},
                        refs=[902, 300, 301, 302, 303, 304, 305, 306])


def _i1_violation(members):
    obj = members[S1][0]["objects"][0]
    members[S1][0] = _a(101, "KN.SlideArchive", obj, refs=[902, 300, 301, 302, 303, 304, 305])


def _i2_violation(members):
    obj = copy.deepcopy(members[S1][0]["objects"][0])
    obj["ownedDrawables"] = list(reversed(obj["ownedDrawables"]))
    members[S1][0] = _a(101, "KN.SlideArchive", obj, refs=[902, 300, 301, 302, 303, 304, 305, 306])


def _second_slide_in_member(members):
    members[S1].append(_slide(109, []))


def _cross_member_subtree(members):
    members[SHEET].append(_a(700, "TSWP.StorageArchive", {"text": ["elsewhere"]}))
    members[S1] = [a if str(a["header"]["identifier"]) != "301"
                   else _a(301, "TSWP.ShapeInfoArchive", a["objects"][0], refs=[311, 901, 700])
                   for a in members[S1]]


def _uuid_ref(members):
    node = copy.deepcopy(members[DOC][3]["objects"][0])
    node["templateSlideId"] = {"lower": "301", "upper": "7"}
    members[DOC][3] = _a(12, "KN.SlideNodeArchive", node, refs=[103])


def _mutate_comp(ident, fn):
    def meta_mutate(pm):
        fn(next(c for c in pm["components"] if str(c["identifier"]) == ident))
    return meta_mutate


def _i3_violation(comp):
    comp["dataReferences"][0]["objectReferenceList"][0]["count"] = 2


def _i4_violation(comp):
    comp["externalReferences"] = [e for e in comp["externalReferences"] if e.get("objectIdentifier") != "901"]


def _group_header_omits_child(members):
    members[S1] = [a if str(a["header"]["identifier"]) != "306"
                   else _a(306, "TSD.GroupArchive", a["objects"][0], refs=[]) for a in members[S1]]


def _move_to_sheet(*ids):
    """Move archives from the slide-1 member into the stylesheet member (cross-member ownership)."""
    def mutate(members):
        moved = [a for a in members[S1] if str(a["header"]["identifier"]) in ids]
        members[S1] = [a for a in members[S1] if str(a["header"]["identifier"]) not in ids]
        members[SHEET].extend(moved)
    return mutate


def _versioned(fields):
    def meta_mutate(pm):
        pm["versionedComponents"] = [{"identifier": "990", "preferredLocator": "Versioned", **fields}]
    return meta_mutate


def _foreign_ext_ref(comp):
    comp.setdefault("externalReferences", []).append(
        {"componentIdentifier": "101", "objectIdentifier": "301", "isWeak": True})


REFUSALS = {
    "build-ref": (1, dict(mutate=_build_ref), "330"),
    "shared-mask": (1, dict(mutate=_shared_mask), "307"),
    "connection-line": (1, dict(mutate=_connection_line), "308"),
    "dual-target": (2, dict(mutate=_dual_target), "dual"),
    "non-list-slide-field": (1, dict(mutate=_non_list_slide_field), "titlePlaceholder"),
    "i1": (1, dict(mutate=_i1_violation), "I1"),
    "i2": (1, dict(mutate=_i2_violation), "I2"),
    "same-component-ambiguous-id": (
        1, dict(meta_mutate=_mutate_comp("101", lambda c: c.update(ambiguousObjectIdentifiers=["301"]))), "ambiguous"),
    "body-ref-missing-from-header": (1, dict(mutate=_group_header_omits_child), "without a same-member header"),
    "owned-child-cross-member-missing-header": (
        1, dict(mutate=_chain(_group_header_omits_child, _move_to_sheet("320", "321"))), "owns 320"),
    "owned-storage-cross-member": (1, dict(mutate=_move_to_sheet("311")), "owns 311"),
    "mask-cross-member": (1, dict(mutate=_move_to_sheet("312")), "owns 312"),
    "versioned-external-ref": (1, dict(meta_mutate=_mutate_comp("2", lambda c: c.update(
        versionedExternalReferences=[{"componentIdentifier": "101", "objectIdentifier": "301"}]))),
        "versionedExternalReferences"),
    "versioned-component-uuid": (1, dict(meta_mutate=_versioned({"objectUuidMapEntries": [
        {"identifier": "301", "uuid": {"lower": "1", "upper": "2"}}]})), "versionedComponents"),
    "versioned-component-data-ref": (1, dict(meta_mutate=_versioned({"dataReferences": [
        {"dataIdentifier": "50", "objectReferenceList": [{"objectIdentifier": "302", "count": 1}]}]})),
        "versionedComponents"),
    "versioned-component-ambiguous": (1, dict(meta_mutate=_versioned({"ambiguousObjectIdentifiers": ["304"]})),
                                      "versionedComponents"),
    "versioned-component-external-ref": (1, dict(meta_mutate=_versioned({"externalReferences": [
        {"componentIdentifier": "101", "objectIdentifier": "305"}]})), "versionedComponents"),
    "shared-member": (1, dict(mutate=_second_slide_in_member), "slide archives"),
    "cross-member-subtree": (1, dict(mutate=_cross_member_subtree), "700"),
    "uuid-ref": (1, dict(mutate=_uuid_ref), "uuid"),
    "foreign-ext-ref": (1, dict(meta_mutate=_mutate_comp("2", _foreign_ext_ref)), "externalReferences"),
    "dmm-orphan": (3, dict(dmm=(54,)), "DataMetadataMap"),
    "orphan-without-member": (3, dict(data_names={k: v for k, v in DATA_NAMES.items() if k != 54}), "Data/"),
}


def _assert_refused_only(path: Path, before: dict[str, bytes], res: HidesResult, slide: int, needle: str):
    member = {1: S1, 2: S2, 3: S3}[slide]
    assert res.slides[slide].refused, res.slides[slide]
    assert needle in (res.slides[slide].reason or ""), res.slides[slide].reason
    assert res.slides[slide].deleted == 0 and res.slides[slide].removed_ids == []
    assert _raw_members(path)[member] == before[member]
    for n, s in res.slides.items():
        if n != slide:
            assert not s.refused, (n, s.reason)
            assert s.deleted == len(HIDES[n])


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_b5_refusal_leaves_slide_byte_identical_and_patches_others(tmp_path, case):
    slide, build_kw, needle = REFUSALS[case]
    path = _build(tmp_path / f"{case}.key", **build_kw)
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, slide, needle)


def _with_item(items, slide, kind, ki, **change):
    out = dict(items)
    out[slide] = [dict(it, **change) if (it["kind"], it["kindIndex"]) == (kind, ki) else it for it in items[slide]]
    return out


def test_payload_items_carry_source_id_and_uuid(deck):
    item = next(it for it in _payload(deck)[1] if (it["kind"], it["kindIndex"]) == ("shape", 0))
    assert item["iwaId"] == 301 and item["iwaUuid"] == "301:7"


def test_every_offline_item_carries_its_iwa_id_including_empty_placeholder_boxes(tmp_path):
    """The cache freshness check needs ``iwaId`` on every offline item: add an empty 0x0
    text box (a layout placeholder seed) to slide 3 and check every item on every slide."""
    def mutate(members):
        members[S3][0] = _slide(103, [500, 501, 502])
        members[S3].extend([
            _a(502, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 512},
                                               "super": {"style": {"identifier": 901}, **_shape_super(0, 0, 0, 0)}},
               refs=[512, 901]),
            _a(512, "TSWP.StorageArchive", {"text": [""]}),
        ])
    path = _build(tmp_path / "ph.key", mutate=mutate)
    payload = _payload(path)
    assert all(isinstance(it.get("iwaId"), int) for items in payload.values() for it in items)
    assert 502 in {it["iwaId"] for it in payload[3]}


def test_id_mismatch_refuses_unproven(deck):
    before = _raw_members(deck)
    res = _run(deck, items=_with_item(_payload(deck), 1, "image", 2, iwaId=303))
    _assert_refused_only(deck, before, res, 1, "image 2 resolves to 304, source id 303")
    assert not res.slides[1].order_proven


def test_missing_iwa_id_refuses_unproven(deck):
    items = _payload(deck)
    items[2] = [{k: v for k, v in it.items() if k != "iwaId"} for it in items[2]]
    before = _raw_members(deck)
    res = _run(deck, items=items)
    _assert_refused_only(deck, before, res, 2, "has no source iwaId")
    assert not res.slides[2].order_proven


def test_uuid_mismatch_refuses_unproven(deck):
    before = _raw_members(deck)
    res = _run(deck, items=_with_item(_payload(deck), 3, "image", 0, iwaUuid="1:2"))
    _assert_refused_only(deck, before, res, 3, "uuid 501:7 != source 1:2")
    assert not res.slides[3].order_proven


def test_reordered_saved_deck_refuses_unproven(tmp_path):
    """The save swaps hidden image 304 and surviving image 303 (same file): kindIndex 2 now
    holds the survivor, so its id no longer matches the payload's and nothing is deleted."""
    source = _build(tmp_path / "src.key")
    saved = _build(tmp_path / "saved.key", mutate=lambda m: m[S1].__setitem__(
        0, _slide(101, [300, 301, 302, 304, 303, 305, 306])))
    before = _raw_members(saved)
    res = _run(saved, items=_payload(source), counts=deck_kind_counts(source))
    _assert_refused_only(saved, before, res, 1, "image 2 resolves to 303, source id 304")
    assert not res.slides[1].order_proven


def _canvas_resized(members):
    """Pass 1's 7680 -> 1920 canvas change on slide 1: x/4, y/4 + 405, w/4, h/4."""
    def walk(v):
        if isinstance(v, dict):
            g = v.get("geometry")
            if isinstance(g, dict) and "position" in g and "size" in g:
                g["position"] = {"x": g["position"]["x"] / 4, "y": g["position"]["y"] / 4 + 405}
                g["size"] = {"width": g["size"]["width"] / 4, "height": g["size"]["height"] / 4}
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for a in members[S1]:
        walk(a["objects"])


def test_canvas_resized_saved_deck_is_patched_because_geometry_no_longer_matters(tmp_path):
    source = _build(tmp_path / "src.key")
    saved = _build(tmp_path / "saved.key", mutate=_canvas_resized)
    res = _run(saved, items=_payload(source), counts=deck_kind_counts(source), verify=True)
    assert all(not s.refused for s in res.slides.values()), {n: s.reason for n, s in res.slides.items()}
    assert set(res.slides[1].removed_ids) == SUBTREE_1


def test_b5_reconcile_mismatch_refuses(deck):
    counts = deck_kind_counts(deck)
    counts[3] = {**counts[3], "image": 2}
    before = _raw_members(deck)
    res = _run(deck, counts=counts)
    _assert_refused_only(deck, before, res, 3, "reconcile")


def test_b5_unresolved_target_refuses(deck):
    hides = {**HIDES, 3: [{"role": "hide", "kind": "image", "kindIndex": 5}]}
    before = _raw_members(deck)
    res = _run(deck, hides)
    _assert_refused_only(deck, before, res, 3, "does not resolve")


def test_b5_two_specs_on_one_target_refuse(deck):
    hides = {**HIDES, 3: [{"role": "hide", "kind": "image", "kindIndex": 0}] * 2}
    before = _raw_members(deck)
    res = _run(deck, hides)
    _assert_refused_only(deck, before, res, 3, "two hide specs")


def test_b5_forced_refusal(deck):
    before = _raw_members(deck)
    res = _run(deck, force_refuse=frozenset({2}))
    _assert_refused_only(deck, before, res, 2, "forced")


def test_b12_undecodable_member_raises_before_write(tmp_path):
    path = _build(tmp_path / "junk.key")
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("Index/Junk.iwa", b"\x00\x01garbage")
    before = _raw_members(path)
    with pytest.raises(OfflineWriteRefused, match="Junk.iwa"):
        _run(path, items=_payload(path), counts=deck_kind_counts(path))
    assert _raw_members(path) == before


def test_b14_movie_hide_on_component_with_feature_infos_refuses(tmp_path):
    def movie(members):
        members[S3][0] = _slide(103, [500, 501, 502])
        members[S3].append(_a(502, "TSD.MovieArchive", {"movieData": {"identifier": 51}, "super": _geom(0, 0, 9, 9)},
                              refs=[], data=[51]))

    def features(comp):
        comp["featureInfos"] = [{"identifier": "TSDMovieInfoPlaysAcrossSlides"}]

    path = _build(tmp_path / "movie.key", mutate=movie, meta_mutate=_mutate_comp("103", features))
    hides = {**HIDES, 3: [{"role": "hide", "kind": "movie", "kindIndex": 0}]}
    before = _raw_members(path)
    res = _run(path, hides)
    _assert_refused_only(path, before, res, 3, "featureInfos")


def test_every_slide_refused_writes_nothing(deck):
    before = _raw_members(deck)
    res = _run(deck, force_refuse=frozenset({1, 2, 3}))
    assert all(s.refused for s in res.slides.values())
    assert res.members == [] and res.dropped_data == []
    assert _raw_members(deck) == before


def test_slide_zero_refuses_before_write(deck):
    with pytest.raises(OfflineWriteRefused):
        patch_deck_hides(deck, {0: HIDES[1]}, source_counts_by_slide={}, items_by_slide={})


# ---------------------------------------------------------------- B6/B9: post-write failures


def test_b6_post_write_corruption_raises_on_read_back(deck, monkeypatch):
    original = _raw_members(deck)[S1]
    real = iwa_write._rewrite_members

    def corrupting(path, edits, *, drop=()):
        real(path, {**edits, S1: original}, drop=drop)

    monkeypatch.setattr(iwa_hides, "_rewrite_members", corrupting)
    with pytest.raises(HidesWriteFailed, match="read-back"):
        _run(deck)


def test_b9_offline_write_corrupted_propagates(deck, monkeypatch):
    def boom(*_a, **_k):
        raise OfflineWriteCorrupted("truncated")

    monkeypatch.setattr(iwa_hides, "_rewrite_members", boom)
    with pytest.raises(OfflineWriteCorrupted):
        _run(deck)


def test_disk_guard_refusal_propagates_and_leaves_deck(deck, monkeypatch):
    before = _raw_members(deck)
    monkeypatch.setattr(iwa_write.shutil, "disk_usage", lambda _p: type("U", (), {"free": 0})())
    with pytest.raises(OfflineWriteRefused, match="free space"):
        _run(deck)
    assert _raw_members(deck) == before


# ---------------------------------------------------------------- B7: decode count


def test_b7_one_whole_deck_decode(deck, monkeypatch):
    items, counts = _payload(deck), deck_kind_counts(deck)
    calls: dict[str, int] = {}
    real = IWAFile.from_buffer.__func__

    def counting(cls, buf, name=None, *a, **k):
        calls[name] = calls.get(name, 0) + 1
        return real(cls, buf, name, *a, **k)

    monkeypatch.setattr(IWAFile, "from_buffer", classmethod(counting))
    monkeypatch.setattr(iwa_write, "read_slide_zorder", lambda *_a: pytest.fail("per-slide read"))
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck_full", lambda *_a, **_k: pytest.fail("_load_deck"))
    res = _run(deck, items=items, counts=counts)
    assert all(not s.refused for s in res.slides.values())
    touched = set(res.members)
    for name, n in calls.items():
        assert n <= (4 if name in touched else 1), (name, n)
    assert {SHEET, DOC, TMPL} <= set(calls) and all(calls[m] == 1 for m in (SHEET, DOC, TMPL))


# ---------------------------------------------------------------- B8: _rewrite_members(drop=)


def test_b8_drop_removes_member_by_raw_name(deck):
    raw = DATA_NAMES[50].encode("utf-8").decode("cp437")
    before = _raw_members(deck)
    _rewrite_members(deck, {}, drop=[raw])
    after = _raw_members(deck)
    assert set(after) == set(before) - {raw}
    assert all(after[n] == before[n] for n in after)


def test_b8_drop_refuses_missing_name(deck):
    before = _raw_members(deck)
    with pytest.raises(OfflineWriteRefused, match="drop names"):
        _rewrite_members(deck, {}, drop=[DATA_NAMES[50]])
    assert _raw_members(deck) == before


def test_b8_drop_refuses_edited_name(deck):
    before = _raw_members(deck)
    with pytest.raises(OfflineWriteRefused, match="both edited and dropped"):
        _rewrite_members(deck, {S1: before[S1]}, drop=[S1])
    assert _raw_members(deck) == before


# ---------------------------------------------------------------- B10: geometry patch follows


def test_b10_geometry_patch_after_hides_does_not_refuse(deck):
    counts = deck_kind_counts(deck)
    _run(deck, counts=counts)
    specs = {
        1: [*HIDES[1], {"kind": "image", "kindIndex": 1, "x": 5, "y": 6}],
        3: [*HIDES[3], {"kind": "text", "kindIndex": 0, "x": 1, "y": 2}],
    }
    results = patch_deck_geometry(deck, specs, source_counts_by_slide=counts)
    assert not results[1].refused, results[1].reason
    assert not results[3].refused, results[3].reason
    assert results[1].applied >= 1


# ---------------------------------------------------------------- #4: global component tables


@pytest.mark.parametrize("comp_id, fn, needle", [
    ("101", _i3_violation, "I3"),
    ("101", _i4_violation, "I4"),
    ("600", lambda c: c.pop("dataReferences"), "I3"),
])
def test_any_component_table_mismatch_refuses_the_stage_before_write(tmp_path, comp_id, fn, needle):
    """The untouched template's stale dataReferences (third case) would otherwise let its
    shared data 53 look orphaned once slide 2's image 402 is deleted."""
    path = _build(tmp_path / "stale.key", meta_mutate=_mutate_comp(comp_id, fn))
    before = _raw_members(path)
    with pytest.raises(OfflineWriteRefused, match=needle):
        _run(path)
    assert _raw_members(path) == before


def test_data_liveness_comes_from_headers_not_metadata(tmp_path):
    """Data 54 is also used by an image in a member Metadata has no component for. Header
    liveness keeps it (no orphan drop); Metadata alone would then leave it unreferenced
    (I6), so the stage refuses before writing instead of failing the read-back."""
    def extra(members):
        members["Index/Extra-800.iwa"] = [_image(800, 54)]

    def drop_extra(pm):
        pm["components"] = [c for c in pm["components"] if c["identifier"] != "800"]

    path = _build(tmp_path / "extra.key", mutate=extra, meta_mutate=drop_extra)
    before = _raw_members(path)
    with pytest.raises(OfflineWriteRefused, match="I6"):
        _run(path)
    assert _raw_members(path) == before


# ---------------------------------------------------------------- #8: exact slide archive, Magic Move


def _with_magic_move(members):
    obj = copy.deepcopy(members[S1][0]["objects"][0])
    obj["transition"] = _transition_dict("apple:magic-move", 1.25)
    members[S1][0] = _a(101, "KN.SlideArchive", obj, refs=[902, 300, 301, 302, 303, 304, 305, 306])


def test_b8_magic_move_transition_and_every_other_slide_field_preserved(tmp_path):
    path = _build(tmp_path / "mm.key", mutate=_with_magic_move)
    before = _decoded(path, S1)["101"]
    res = _run(path)
    assert not res.slides[1].refused, res.slides[1].reason
    after = _decoded(path, S1)["101"]
    assert after["objects"][0]["transition"] == before["objects"][0]["transition"]
    assert after["objects"][0]["transition"]["attributes"]["animationAttributes"]["effect"] == "apple:magic-move"
    want = copy.deepcopy(before)
    want["objects"][0]["drawablesZOrder"] = [{"identifier": "300"}, {"identifier": "303"}]
    want["objects"][0]["ownedDrawables"] = [{"identifier": "300"}, {"identifier": "303"}]
    want["header"]["messageInfos"][0]["objectReferences"] = ["902", "300", "303"]
    assert iwa_write._archives_equal(after, want)


def test_b8_re_encode_that_alters_the_transition_refuses_the_slide(tmp_path, monkeypatch):
    path = _build(tmp_path / "mm.key", mutate=_with_magic_move)
    real = iwa_hides._slide_apply_fn

    def tampering(plan):
        inner = real(plan)

        def apply_fn(patched):
            n = inner(patched)
            for ch in patched["chunks"]:
                for arch in ch["archives"]:
                    if str(arch["header"]["identifier"]) == "101":
                        arch["objects"][0]["transition"]["attributes"]["animationAttributes"]["duration"] = 9.0
            return n
        return apply_fn

    monkeypatch.setattr(iwa_hides, "_slide_apply_fn", tampering)
    before = _raw_members(path)
    res = _run(path)
    assert res.slides[1].refused and "re-encoded slide archive" in res.slides[1].reason
    assert res.slides[1].order_proven
    assert _raw_members(path)[S1] == before[S1]


# ---------------------------------------------------------------- #7: typed failure phases, order_proven


def test_temp_phase_failure_is_refused_and_deck_untouched(deck, monkeypatch):
    before = _raw_members(deck)

    def boom(self, *a, **k):
        raise OSError("disk full mid zip build")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", boom)
    with pytest.raises(OfflineWriteRefused, match="temp rewrite failed"):
        _run(deck)
    monkeypatch.undo()
    assert _raw_members(deck) == before


def test_failure_after_copy_back_is_hides_write_failed(deck, monkeypatch):
    real_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name.endswith(".obedwrite.tmp") and not k.get("missing_ok"):
            raise PermissionError("tmp locked")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(HidesWriteFailed, match="after its copy-back"):
        _run(deck)


def test_planning_bug_is_refused_before_write(deck, monkeypatch):
    before = _raw_members(deck)
    monkeypatch.setattr(iwa_hides, "_orphans", lambda *_a: 1 / 0)
    with pytest.raises(OfflineWriteRefused, match="ZeroDivisionError"):
        _run(deck)
    assert _raw_members(deck) == before


def test_order_proven_values(tmp_path):
    items_path = _build(tmp_path / "a.key", mutate=_build_ref)
    items = _payload(items_path)
    items = _with_item(items, 2, "image", 1, iwaId=400)
    res = _run(items_path, items=items, force_refuse=frozenset({3}))
    assert res.slides[1].refused and "330" in res.slides[1].reason and res.slides[1].order_proven
    assert res.slides[2].refused and "source id 400" in res.slides[2].reason and not res.slides[2].order_proven
    assert res.slides[3].refused and res.slides[3].reason == "forced refusal" and res.slides[3].order_proven


def test_forced_refusal_of_an_unplannable_slide_keeps_order_unproven(deck):
    counts = deck_kind_counts(deck)
    counts[3] = {**counts[3], "image": 5}
    res = _run(deck, counts=counts, force_refuse=frozenset({3}))
    assert res.slides[3].refused and "reconcile" in res.slides[3].reason
    assert not res.slides[3].order_proven


def test_patched_slides_report_order_proven(deck):
    res = _run(deck)
    assert all(s.order_proven and not s.refused for s in res.slides.values())


def test_hiding_every_drawable_on_a_slide(deck):
    hides = {**HIDES, 2: [*HIDES[2], {"role": "hide", "kind": "image", "kindIndex": 0}]}
    res = _run(deck, hides)
    assert not res.slides[2].refused, res.slides[2].reason
    z, owned, header = _z(deck, S2, "102")
    assert z == [] and owned == [] and header == ["902"]
    assert set(_decoded(deck, S2)) == {"102"}


# ---------------------------------------------------------------- Astra r2 #3: read-back


def test_read_back_catches_metadata_naming_a_removed_id(deck, monkeypatch):
    original_meta = _raw_members(deck)[META]
    real = iwa_write._rewrite_members

    def stale_metadata(path, edits, *, drop=()):
        real(path, {**edits, META: original_meta}, drop=drop)

    monkeypatch.setattr(iwa_hides, "_rewrite_members", stale_metadata)
    with pytest.raises(HidesWriteFailed, match="names removed 401|names removed 411"):
        _run(deck, {2: [HIDES[2][0]]})


# ---------------------------------------------------------------- Astra r3 #2: later objects


def test_second_object_ownership_cross_member_without_header_refuses(tmp_path):
    """Archive 306 carries a second object owning child 320, which lives in another member
    and is absent from 306's header: removing 306 alone would orphan 320/321."""
    def mutate(members):
        members[S1] = [a for a in members[S1] if str(a["header"]["identifier"]) not in {"306", "320", "321"}]
        members[SHEET].extend(_text(320, 321, "G child"))
        group = _a(306, "TSD.GroupArchive", {"children": [], "super": {}}, refs=[])
        second = copy.deepcopy(group["objects"][0])
        second["children"] = [{"identifier": 320}]
        group["objects"].append(second)
        group["header"]["messageInfos"].append(copy.deepcopy(group["header"]["messageInfos"][0]))
        members[S1].append(group)

    path = _build(tmp_path / "second.key", mutate=mutate)
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, 1, "owns 320")


# ---------------------------------------------------------------- Sol r4 #2: reference classification, #4: Metadata exactness


def _patch_s1(ident, *, extra_obj=None, super_extra=None, refs=None, add=(), add_sheet=()):
    """Rebuild slide-1 archive ``ident`` with extra fields/header refs, plus extra archives
    in the slide member (``add``) or the stylesheet member (``add_sheet``)."""
    def mutate(members):
        out = []
        for a in members[S1]:
            if str(a["header"]["identifier"]) != str(ident):
                out.append(a)
                continue
            obj = copy.deepcopy(a["objects"][0])
            obj.pop("_pbtype", None)
            obj.update(extra_obj or {})
            if super_extra:
                obj["super"] = {**obj.get("super", {}), **super_extra}
            hdr = a["header"]["messageInfos"][0].get("objectReferences") or []
            out.append(_a(ident, a["objects"][0]["_pbtype"], obj, refs=refs if refs is not None else hdr))
        members[S1] = out + copy.deepcopy(list(add))
        members[SHEET].extend(copy.deepcopy(list(add_sheet)))
    return mutate


def _standin(ident):
    return _a(ident, "TSD.StandinCaptionArchive", {})


REF_REFUSALS = {
    "fake-shape-cross-member-no-header": (
        dict(extra_obj={"fakeShapeForEmptyGroup": {"identifier": 700}},
             add_sheet=[_a(700, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 1, 1)})]),
        "fakeShapeForEmptyGroup owns 700"),
    "title-standin-cross-member": (
        dict(ident=305, super_extra={"title": {"identifier": 702}}, refs=[900, 702], add_sheet=[_standin(702)]),
        "title owns 702"),
    "caption-standin-no-header": (
        dict(ident=305, super_extra={"caption": {"identifier": 703}}, add=[_standin(703)]),
        "caption owns 703"),
    "unclassified-cross-member-no-header": (
        dict(ident=305, extra_obj={"databaseData": {"identifier": 704}}, add_sheet=[_standin(704)]),
        "unclassified databaseData"),
    "comment": (
        dict(ident=305, super_extra={"comment": {"identifier": 705}}, refs=[900, 705], add=[_standin(705)]),
        "comment references 705"),
}


@pytest.mark.parametrize("case", sorted(REF_REFUSALS))
def test_reference_classification_refusals(tmp_path, case):
    kw, needle = REF_REFUSALS[case]
    kw = dict(kw)
    ident = kw.pop("ident", 306)
    path = _build(tmp_path / f"{case}.key", mutate=_patch_s1(ident, **kw))
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, 1, needle)


def test_owned_fake_shape_and_standins_in_member_are_deleted_with_the_hide(tmp_path):
    fake = _a(701, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 1, 1)})
    mutate = _chain(
        _patch_s1(306, extra_obj={"fakeShapeForEmptyGroup": {"identifier": 701}}, refs=[320, 701], add=[fake]),
        _patch_s1(305, super_extra={"title": {"identifier": 706}, "caption": {"identifier": 707}},
                  refs=[900, 706, 707], add=[_standin(706), _standin(707)]),
    )
    path = _build(tmp_path / "owned.key", mutate=mutate)
    res = _run(path, verify=True)
    assert not res.slides[1].refused, res.slides[1].reason
    assert {"701", "706", "707"} <= set(res.slides[1].removed_ids)


@pytest.mark.parametrize("damage", ["drop", "change"])
def test_metadata_re_encode_that_alters_data_metadata_map_refuses(deck, monkeypatch, damage):
    real = iwa_hides._decode_apply_reencode_diff

    def damaging(zf, member, apply_fn, expect=None):
        out = list(real(zf, member, apply_fn, expect))
        if member == META:
            pm = iwa_write._archives_by_id(out[5])[str(PM_ID)]["objects"][0]
            if damage == "drop":
                pm.pop("dataMetadataMap")
            else:
                pm["dataMetadataMap"] = {"identifier": "9"}
        return tuple(out)

    monkeypatch.setattr(iwa_hides, "_decode_apply_reencode_diff", damaging)
    before = _raw_members(deck)
    with pytest.raises(OfflineWriteRefused, match="PackageMetadata != intended"):
        _run(deck)
    assert _raw_members(deck) == before


# ---------------------------------------------------------------- Sol r5 #2: nested attachment / comment / pencil refs


def _storage_with(table, entry_obj_id, extra_archs=(), sheet_archs=(), storage_refs=()):
    """Hide 301's storage 311 gains a ``table`` entry pointing at ``entry_obj_id``."""
    def mutate(members):
        out = []
        for a in members[S1]:
            if str(a["header"]["identifier"]) == "311":
                obj = {"text": ["Hide me"], table: {"entries": [{"characterIndex": 0, "object": {"identifier": entry_obj_id}}]}}
                a = _a(311, "TSWP.StorageArchive", obj, refs=[entry_obj_id, *storage_refs])
            out.append(a)
        members[S1] = out + copy.deepcopy(list(extra_archs))
        members[SHEET].extend(copy.deepcopy(list(sheet_archs)))
    return mutate


def _pencil_substorage(members):
    members[S1] = [a if str(a["header"]["identifier"]) != "301"
                   else _a(301, "TSWP.ShapeInfoArchive", a["objects"][0], refs=[311, 901, 730]) for a in members[S1]]
    members[S1].append(_a(730, "TSD.PencilAnnotationStorageArchive", {"subStorages": [{"identifier": 731}]}, refs=[731]))
    members[SHEET].append(_a(731, "TSD.PencilAnnotationStorageArchive", {}))


NESTED_REFUSALS = {
    "attachment-drawable-cross-member": (
        _storage_with("tableAttachment", 720,
                      extra_archs=[_a(720, "TSWP.DrawableAttachmentArchive", {"drawable": {"identifier": 721}}, refs=[721])],
                      sheet_archs=[_image(721, 51)]),
        "drawable owns 721"),
    "footnote-contained-storage-cross-member": (
        _storage_with("tableFootnote", 722,
                      extra_archs=[_a(722, "TSWP.FootnoteReferenceAttachmentArchive",
                                      {"containedStorage": {"identifier": 723}}, refs=[723])],
                      sheet_archs=[_a(723, "TSWP.StorageArchive", {"text": ["note"]})]),
        "containedStorage owns 723"),
    "highlight-table": (
        _storage_with("tableHighlight", 724, extra_archs=[_a(724, "TSWP.HighlightArchive", {})]),
        "forbidden tableHighlight"),
    "highlight-archive-comment-storage-field": (
        _storage_with("tableAttachment", 724,
                      extra_archs=[_a(724, "TSWP.HighlightArchive", {"commentStorage": {"identifier": 725}}, refs=[725]),
                                   _a(725, "TSD.CommentStorageArchive", {})]),
        "is a TSWP.HighlightArchive"),
    "pencil-annotation-storage": (
        _storage_with("tableAttachment", 726,
                      extra_archs=[_a(726, "TSWP.PencilAnnotationArchive",
                                      {"pencilAnnotationStorage": {"identifier": 727}}, refs=[727]),
                                   _a(727, "TSD.PencilAnnotationStorageArchive", {})]),
        "is a TSWP.PencilAnnotationArchive"),
    "pencil-storage-header-only": (_pencil_substorage, "header references ['730']"),
    "unclassified-header-listed": (
        _storage_with("tableSmartfield", 728, extra_archs=[_a(728, "TSWP.StorageArchive", {})]),
        "unclassified tableSmartfield"),
}


@pytest.mark.parametrize("case", sorted(NESTED_REFUSALS))
def test_nested_reference_classification_refusals(tmp_path, case):
    mutate, needle = NESTED_REFUSALS[case]
    path = _build(tmp_path / f"{case}.key", mutate=mutate)
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, 1, needle)


def test_owned_footnote_and_inline_drawable_in_member_are_deleted_with_the_hide(tmp_path):
    def mutate(members):
        _storage_with("tableAttachment", 720, extra_archs=[
            _a(720, "TSWP.DrawableAttachmentArchive", {"drawable": {"identifier": 721}}, refs=[721]),
            _image(721, 51)])(members)
    path = _build(tmp_path / "inline.key", mutate=mutate)
    res = _run(path, verify=True)
    assert not res.slides[1].refused, res.slides[1].reason
    assert {"720", "721"} <= set(res.slides[1].removed_ids)


@pytest.mark.parametrize("path, cls", [
    ("super.super.title", "strong"), ("super.caption", "strong"), ("children", "strong"), ("mask", "strong"),
    ("ownedStorage", "strong"), ("fakeShapeForEmptyGroup", "strong"), ("drawable", "strong"),
    ("containedStorage", "strong"), ("subStorages", "strong"), ("calloutSubStorages", "strong"),
    ("tableAttachment.entries.object", "strong"), ("tableFootnote.entries.object", "strong"),
    ("super.parent", "weak"), ("super.style", "weak"), ("styleSheet", "weak"),
    ("tableParaStyle.entries.object", "weak"), ("tableDropCapStyle.entries.object", "weak"),
    ("super.comment", "forbidden"), ("commentStorage", "forbidden"), ("pencilAnnotationStorage", "forbidden"),
    ("tableHighlight.entries.object", "forbidden"), ("tablePencilAnnotation.entries.field", "forbidden"),
    ("tableInsertion.entries.object", "forbidden"), ("textFlow", "forbidden"),
    ("tableSmartfield.entries.object", "unclassified"), ("databaseData", "unclassified"),
])
def test_reference_path_classes(path, cls):
    assert iwa_hides._ref_class(path) == cls


# ---------------------------------------------------------------- Sol r6 #1: classification drives closure


def test_same_member_weak_style_stays_outside_the_subtree(tmp_path):
    """A slide-member style used by hidden image 305 and surviving image 303: the weak,
    header-listed ref must not pull the style into deletion."""
    local_style = _a(740, "TSD.MediaStyleArchive", {})

    def mutate(members):
        members[S1] = [_image(int(a["header"]["identifier"]), 51 if a["header"]["identifier"] in (303, "303") else 52,
                              style=740)
                       if str(a["header"]["identifier"]) in ("303", "305") else a for a in members[S1]]
        members[S1].append(local_style)

    path = _build(tmp_path / "style.key", mutate=mutate)
    res = _run(path, verify=True)
    assert not res.slides[1].refused, res.slides[1].reason
    assert "740" not in res.slides[1].removed_ids
    assert "740" in _decoded(path, S1)


@pytest.mark.parametrize("where", ["messageInfos", "fieldInfos"])
def test_header_only_reference_refuses(tmp_path, where):
    extra = _a(741, "TSWP.StorageArchive", {"text": ["orphan?"]})

    def mutate(members):
        out = []
        for a in members[S1]:
            if str(a["header"]["identifier"]) == "305":
                a = copy.deepcopy(a)
                mi = a["header"]["messageInfos"][0]
                if where == "messageInfos":
                    mi["objectReferences"] = [*mi.get("objectReferences", []), "741"]
                else:
                    mi["fieldInfos"] = [{"path": {"path": [1]}, "objectReferences": ["741"]}]
            out.append(a)
        members[S1] = out + [extra]

    path = _build(tmp_path / f"{where}.key", mutate=mutate)
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, 1, "header references ['741'] with no decoded body reference")


def test_unresolved_forbidden_reference_refuses(tmp_path):
    path = _build(tmp_path / "c.key", mutate=_patch_s1(305, super_extra={"comment": {"identifier": 99999}}))
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, 1, "forbidden super.comment references 99999")


# ---------------------------------------------------------------- Sol r7 #2: subtree refusals keep the order proof


def _header_only_ref(members):
    members[S1] = [a if str(a["header"]["identifier"]) != "305"
                   else _a(305, "TSD.ImageArchive", a["objects"][0], refs=[900, 741], data=[52]) for a in members[S1]]
    members[S1].append(_a(741, "TSWP.StorageArchive", {"text": ["x"]}))


PROVEN_REFUSALS = {
    "header-only": (_header_only_ref, "no decoded body reference"),
    "comment": (_patch_s1(305, super_extra={"comment": {"identifier": 705}}, refs=[900, 705], add=[_standin(705)]),
                "forbidden super.comment"),
    "highlight": (NESTED_REFUSALS["highlight-table"][0], "forbidden tableHighlight"),
    "unclassified": (NESTED_REFUSALS["unclassified-header-listed"][0], "unclassified tableSmartfield"),
}


@pytest.mark.parametrize("case", sorted(PROVEN_REFUSALS))
def test_subtree_refusals_keep_order_proven_for_the_per_slide_fallback(tmp_path, case):
    mutate, needle = PROVEN_REFUSALS[case]
    path = _build(tmp_path / f"{case}.key", mutate=mutate)
    before = _raw_members(path)
    res = _run(path)
    _assert_refused_only(path, before, res, 1, needle)
    assert res.slides[1].order_proven


# ---------------------------------------------------------------- Sol r8 #5: ambiguous package, #6: shared slide id


def _duplicate_with_hidden_ref(members):
    """A second archive 303 in the Document member whose body (a build) points at hide 301:
    the first-occurrence model would never see that reference."""
    members[DOC].append(_a(303, "KN.BuildArchive", {"drawable": {"identifier": 301}, "delivery": "", "attributes": {}},
                           refs=[301]))


def test_duplicate_archive_id_refuses_the_stage_with_zero_byte_change(tmp_path):
    path = _build(tmp_path / "dup.key", mutate=_duplicate_with_hidden_ref)
    before = _raw_members(path)
    with pytest.raises(OfflineWriteRefused, match=r"duplicate archive id.*303 in \[.Index/Document.iwa., .Index/Slide-101.iwa.\]"):
        _run(path)
    assert _raw_members(path) == before


@pytest.mark.parametrize("where", [META, DOC])
def test_second_package_metadata_refuses_the_stage_with_zero_byte_change(tmp_path, where):
    path = _build(tmp_path / "pm2.key")
    with zipfile.ZipFile(path) as zf:
        decoded = IWAFile.from_buffer(zf.read(where), where).to_dict()
    extra = _a(6, "TSP.PackageMetadata", {"lastObjectIdentifier": "1000"})
    decoded["chunks"][0]["archives"].append(extra)
    iwa_write._rewrite_members(path, {where: IWAFile.from_dict(decoded).to_buffer()})
    before = _raw_members(path)
    with pytest.raises(OfflineWriteRefused, match="PackageMetadata found in"):
        _run(path)
    assert _raw_members(path) == before


def _shared_slide_id(members):
    """Slide nodes 10 and 12 both point at slide archive 101 (slide numbers 1 and 3)."""
    members[DOC][3] = _a(12, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False}, refs=[101])


def test_shared_slide_id_is_an_unproven_refusal(tmp_path):
    path = _build(tmp_path / "shared.key", mutate=_shared_slide_id)
    before = _raw_members(path)
    hides = {1: HIDES[1], 3: HIDES[1]}
    res = _run(path, hides)
    for n in (1, 3):
        assert res.slides[n].refused and "appears under 2 slide numbers" in res.slides[n].reason
        assert not res.slides[n].order_proven
    assert _raw_members(path)[S1] == before[S1]


def test_shared_slide_id_aborts_before_any_applescript_fallback(tmp_path, monkeypatch):
    from obed_edom import offline_write

    path = _build(tmp_path / "shared.key", mutate=_shared_slide_id)
    items = _payload(path)
    wall = {"slides": [{"number": n, "items": items[n]} for n in sorted(items)]}
    transforms = [{**h, "slide": n} for n in (1, 3) for h in HIDES[1]]
    calls: list = []
    monkeypatch.setattr(offline_write, "_run_hide_fallback", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(offline_write, "_run_fallback_scripts", lambda *a, **k: calls.append(a) or (True, [], []))
    with pytest.raises(offline_write.OfflineHidesAborted, match="before the saved order was proven"):
        offline_write.run_offline_hides(path, "on", {1, 3}, transforms, wall, lambda _m: None)
    assert calls == []


def test_one_target_with_an_untargeted_alias_aborts_with_zero_byte_change(tmp_path, monkeypatch):
    """Only slide 1 is targeted; slide 3 is an untargeted alias of the same archive 101."""
    from obed_edom import offline_write

    path = _build(tmp_path / "alias.key", mutate=_shared_slide_id)
    before = _raw_members(path)
    res = _run(path, {1: HIDES[1]})
    assert res.slides[1].refused and "appears under 2 slide numbers" in res.slides[1].reason
    assert not res.slides[1].order_proven and res.members == []
    assert _raw_members(path) == before

    items = _payload(path)
    wall = {"slides": [{"number": n, "items": items[n]} for n in sorted(items)]}
    calls: list = []
    monkeypatch.setattr(offline_write, "_run_hide_fallback", lambda *a, **k: calls.append(a))
    with pytest.raises(offline_write.OfflineHidesAborted, match="before the saved order was proven"):
        offline_write.run_offline_hides(path, "on", {1}, [{**h, "slide": 1} for h in HIDES[1]], wall, lambda _m: None)
    assert calls == [] and _raw_members(path) == before
