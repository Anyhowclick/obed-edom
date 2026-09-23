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
from obed_edom.iwa_hides import HidesResult, patch_deck_hides  # noqa: E402
from obed_edom.iwa_kindindex import deck_kind_counts, derive_kind_index  # noqa: E402
from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: E402
from obed_edom.iwa_write import (  # noqa: E402
    OfflineWriteCorrupted,
    OfflineWriteRefused,
    _RawNameZipInfo,
    _rewrite_members,
    patch_deck_geometry,
)
from obed_edom.offline_inspect import _build_data_index, _data_identifier  # noqa: E402
from test_iwa_write import _arch, _geom, _member, _shape_super  # noqa: E402

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


def _text(ident, storage, text, *, textbox=True, style=901, extra_refs=(), **extra):
    obj = {"isTextBox": textbox, "ownedStorage": {"identifier": storage},
           "super": {"style": {"identifier": style}, **_geom(10, 10, 100, 40)}, **extra}
    return [
        _a(ident, "TSWP.ShapeInfoArchive", obj, refs=[storage, style, *extra_refs]),
        _a(storage, "TSWP.StorageArchive", {"text": [text]}),
    ]


def _image(ident, data, *, mask=None, style=900):
    obj = {"data": {"identifier": data}, "style": {"identifier": style}, "super": _geom(0, 0, 50, 50)}
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
            *_text(320, 321, "G child", extra_refs=[306]),
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
    """JXA-shaped items per slide (kind, kindIndex, text, fileName) off the undeleted deck."""
    objects, _idf, _fi = _load_deck(path)
    with zipfile.ZipFile(path) as zf:
        data_index = _build_data_index(zf.namelist())
    out: dict[int, list[dict]] = {}
    for n, (sid, _skipped) in enumerate(slide_order(objects), 1):
        items = []
        for rec in derive_kind_index(objects[sid], objects):
            item = {"kind": rec["kind"], "kindIndex": rec["kindIndex"], "text": rec["text"], "fileName": ""}
            if rec["kind"] in ("image", "movie"):
                item["fileName"] = data_index.get(_data_identifier(objects[rec["id"]]) or "", "")
            if rec.get("duplicateOf"):
                item["duplicateOf"] = rec["duplicateOf"]
            items.append(item)
        out[n] = items
    return out


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
    members[S1].append(_image(307, 51, mask=312))


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


def _foreign_ext_ref(comp):
    comp.setdefault("externalReferences", []).append({"componentIdentifier": "101", "objectIdentifier": "301"})


REFUSALS = {
    "build-ref": (1, dict(mutate=_build_ref), "330"),
    "shared-mask": (1, dict(mutate=_shared_mask), "307"),
    "connection-line": (1, dict(mutate=_connection_line), "308"),
    "dual-target": (2, dict(mutate=_dual_target), "dual"),
    "non-list-slide-field": (1, dict(mutate=_non_list_slide_field), "titlePlaceholder"),
    "i1": (1, dict(mutate=_i1_violation), "I1"),
    "i2": (1, dict(mutate=_i2_violation), "I2"),
    "i3": (1, dict(meta_mutate=_mutate_comp("101", _i3_violation)), "I3"),
    "i4": (1, dict(meta_mutate=_mutate_comp("101", _i4_violation)), "I4"),
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


def test_b5_identity_mismatch_refuses(deck):
    items = _payload(deck)
    items[1] = [dict(it, text="Other") if it["kind"] == "text" else it for it in items[1]]
    before = _raw_members(deck)
    res = _run(deck, items=items)
    _assert_refused_only(deck, before, res, 1, "text 0 text differs")


def test_b5_image_identity_mismatch_refuses(deck):
    items = _payload(deck)
    items[2] = [dict(it, fileName="wrong.png") if it["kind"] == "image" else it for it in items[2]]
    before = _raw_members(deck)
    res = _run(deck, items=items)
    _assert_refused_only(deck, before, res, 2, "image 0 file")


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


def test_group_identity_uses_child_text_signature(deck):
    good = _run(deck, group_text_by_slide={1: {0: "G child"}})
    assert not good.slides[1].refused


def test_group_identity_mismatch_refuses(deck):
    before = _raw_members(deck)
    res = _run(deck, group_text_by_slide={1: {0: "Something else"}})
    _assert_refused_only(deck, before, res, 1, "group 0")


def test_b12_tail_placeholder_text_items_do_not_refuse(deck):
    items = _payload(deck)
    items[3] = items[3] + [{"kind": "text", "kindIndex": 1, "text": "", "w": 0, "h": 0, "fileName": ""}]
    counts = deck_kind_counts(deck)
    counts[3] = {**counts[3], "text": counts[3]["text"] + 1}
    res = _run(deck, items=items, counts=counts)
    assert not res.slides[3].refused, res.slides[3].reason


def test_b12_non_placeholder_extra_text_item_refuses(deck):
    items = _payload(deck)
    items[3] = items[3] + [{"kind": "text", "kindIndex": 1, "text": "real", "w": 90, "h": 20, "fileName": ""}]
    counts = deck_kind_counts(deck)
    counts[3] = {**counts[3], "text": counts[3]["text"] + 1}
    before = _raw_members(deck)
    res = _run(deck, items=items, counts=counts)
    _assert_refused_only(deck, before, res, 3, "payload has 2 text items")


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


def test_slide_zero_raises(deck):
    with pytest.raises(ValueError):
        patch_deck_hides(deck, {0: HIDES[1]}, source_counts_by_slide={}, items_by_slide={})


# ---------------------------------------------------------------- B6/B9: post-write failures


def test_b6_post_write_corruption_raises_on_read_back(deck, monkeypatch):
    original = _raw_members(deck)[S1]
    real = iwa_write._rewrite_members

    def corrupting(path, edits, *, drop=()):
        real(path, {**edits, S1: original}, drop=drop)

    monkeypatch.setattr(iwa_hides, "_rewrite_members", corrupting)
    with pytest.raises(RuntimeError, match="read-back"):
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
