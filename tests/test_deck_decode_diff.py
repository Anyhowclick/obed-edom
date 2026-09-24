"""Checker controls for ``scripts/deck_decode_diff.py`` (O2 of the pass-1 hides-offline plan).

Synthetic REAL ``.key`` decks built with the ``IWAFile`` builder from ``test_iwa_write``.
The base deck is described as ``{member: [archive dicts]}`` plus ``Data/`` files, so each
test edits a deep copy and re-serialises it:

- Slide 1 (``Index/Slide-101.iwa``): shape 300 and image 301 (data 7001, style 900 in the
  stylesheet), builds 500 (dissolve, on 300) and 501 (wipe, on 301). Header refs carry
  every referenced id, the image header carries its data ref.
- Slide 2 (``Index/Slide-102.iwa``): shapes 400 and 401.
- ``Index/Metadata.iwa``: one component per member (id == root archive id), uuid entries,
  the image's dataReferences, the stylesheet externalReference, and ``datas`` for 7001
  (``photo.jpg``) and 7002 (``orphan.png``, referenced by nobody).

Null controls: deck vs itself, vs a consistently re-IDed copy, vs a reseeded copy -> 0.
Positive controls: a field change on slide 2, swapped build refs, a dangling body ref, a
stale header ref, Metadata table edits, a dropped data -> reported (and ``--allow``-able).
"""
from __future__ import annotations

import base64
import copy
import io
import json
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from scripts import deck_decode_diff as ddd  # noqa: E402
from test_iwa_write import _arch, _build_effect, _geom, _member, _shape_super  # noqa: E402
from test_stroke_probe import _with_refs  # noqa: E402

_DIGEST_PHOTO = base64.b64encode(b"photo-digest").decode()
_DIGEST_ORPHAN = base64.b64encode(b"orphan-digest").decode()


def _with_data_refs(arch, refs):
    arch = copy.deepcopy(arch)
    arch["header"]["messageInfos"][0]["dataReferences"] = [str(r) for r in refs]
    return arch


def _build(effect, drawable):
    return _with_refs(_arch(drawable + 200, "KN.BuildArchive", {
        "drawable": {"identifier": drawable}, "delivery": "All at Once", "duration": 0.0,
        "attributes": _build_effect(effect), "chunkIdSeed": 1,
    }), [drawable])


def _shape(ident, slide, x, y, w, h):
    shape_super = _shape_super(x, y, w, h)
    shape_super["super"]["parent"] = {"identifier": slide}
    return _with_refs(_arch(ident, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": shape_super}), [slide])


def _base_spec():
    shape300 = _shape(300, 101, 10, 20, 100, 50)
    image301 = _with_data_refs(_with_refs(_arch(301, "TSD.ImageArchive", {
        "data": {"identifier": 7001}, "style": {"identifier": 900},
        "super": {**_geom(300, 100, 120, 60), "parent": {"identifier": 101}},
        "originalSize": {"width": 120.0, "height": 60.0},
    }), [900, 101]), [7001])
    build500 = _build("apple:dissolve", 300)
    build501 = _build("apple:wipe-iris", 301)
    slide101 = _with_refs(_arch(101, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 300}, {"identifier": 301}],
        "ownedDrawables": [{"identifier": 300}, {"identifier": 301}],
        "builds": [{"identifier": 500}, {"identifier": 501}],
    }), [300, 301, 500, 501])
    shape400 = _shape(400, 102, 30, 40, 80, 60)
    shape401 = _shape(401, 102, 50, 60, 20, 20)
    slide102 = _with_refs(_arch(102, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 400}, {"identifier": 401}],
        "ownedDrawables": [{"identifier": 400}, {"identifier": 401}],
    }), [400, 401])
    show = _with_refs(_arch(2, "KN.ShowArchive", {
        "slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]},
    }), [10, 11])
    node10 = _with_refs(_arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 101}, "isSkipped": False}), [101])
    node11 = _with_refs(_arch(11, "KN.SlideNodeArchive", {"slide": {"identifier": 102}, "isSkipped": False}), [102])
    style900 = _arch(900, "TSD.MediaStyleArchive", {"super": {"styleIdentifier": "image-0-imageStyle"}})

    def uuids(*ids):
        return [{"identifier": i, "uuid": {"lower": str(i), "upper": "7"}} for i in ids]

    components = [
        {"identifier": 2, "preferredLocator": "Document", "objectUuidMapEntries": uuids(2, 10, 11),
         "externalReferences": [{"componentIdentifier": 101}, {"componentIdentifier": 102}]},
        {"identifier": 900, "preferredLocator": "DocumentStylesheet", "objectUuidMapEntries": uuids(900)},
        {"identifier": 101, "locator": "Slide-101", "preferredLocator": "Slide",
         "objectUuidMapEntries": uuids(101, 300, 301, 500, 501),
         "externalReferences": [{"componentIdentifier": 900, "objectIdentifier": 900}],
         "dataReferences": [{"dataIdentifier": 7001,
                             "objectReferenceList": [{"objectIdentifier": 301, "count": 1}]}]},
        {"identifier": 102, "locator": "Slide-102", "preferredLocator": "Slide",
         "objectUuidMapEntries": uuids(102, 400, 401)},
    ]
    metadata = _arch(5, "TSP.PackageMetadata", {
        "lastObjectIdentifier": "1000",
        "saveToken": "1",
        "revision": {"sequence32": 1, "identifier": "rev-a"},
        "fileFormatVersion": [14, 4, 1],
        "dataMetadataMap": {"identifier": 6},
        "components": components,
        "datas": [
            {"identifier": 7001, "digest": _DIGEST_PHOTO, "preferredFileName": "photo.jpg",
             "fileName": "photo-7001.jpg"},
            {"identifier": 7002, "digest": _DIGEST_ORPHAN, "preferredFileName": "orphan.png",
             "fileName": "orphan-7002.png"},
        ],
    })
    return {
        "members": {
            "Index/Document.iwa": [show, node10, node11],
            "Index/DocumentStylesheet.iwa": [style900],
            "Index/Slide-101.iwa": [slide101, shape300, image301, build500, build501],
            "Index/Slide-102.iwa": [slide102, shape400, shape401],
            "Index/Metadata.iwa": [metadata, _arch(6, "TSP.DataMetadataMap", {})],
        },
        "files": {
            "Data/photo-7001.jpg": b"\xff\xd8photo",
            "Data/orphan-7002.png": b"\x89PNGorphan",
            "preview.jpg": b"\xff\xd8preview",
        },
    }


def _write(spec, path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, archives in spec["members"].items():
            z.writestr(name, _member(archives))
        for name, data in spec["files"].items():
            z.writestr(name, data)
    path.write_bytes(buf.getvalue())
    return path


def _archive(spec, member, ident):
    return next(a for a in spec["members"][member] if int(a["header"]["identifier"]) == ident)


def _obj(spec, member, ident):
    return _archive(spec, member, ident)["objects"][0]


def _metadata(spec):
    return _obj(spec, "Index/Metadata.iwa", 5)


def _component(spec, locator):
    return next(c for c in _metadata(spec)["components"] if (c.get("locator") or c["preferredLocator"]) == locator)


def _drop_archive(spec, member, ident):
    spec["members"][member] = [a for a in spec["members"][member] if int(a["header"]["identifier"]) != ident]


def _set_header_refs(spec, member, ident, refs):
    _archive(spec, member, ident)["header"]["messageInfos"][0]["objectReferences"] = [str(r) for r in refs]


_ID_KEYS = ("identifier", "objectIdentifier", "componentIdentifier")


def _renumber(value, mapping):
    """Every object id (never a data id) through ``mapping``, in bodies, headers and Metadata."""
    if isinstance(value, list):
        return [_renumber(v, mapping) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key in _ID_KEYS and str(item).isdigit() and int(item) in mapping:
            out[key] = mapping[int(item)]
        elif key == "objectReferences":
            out[key] = [str(mapping.get(int(r), int(r))) for r in item]
        else:
            out[key] = _renumber(item, mapping)
    return out


@pytest.fixture()
def base(tmp_path):
    return _write(_base_spec(), tmp_path / "base.key")


def _variant(tmp_path, name, edit):
    spec = _base_spec()
    edit(spec)
    return _write(spec, tmp_path / f"{name}.key")


def _keys(report):
    return sorted(d["key"] for d in report["diffs"])


def _correctly_deleted_401(spec):
    _drop_archive(spec, "Index/Slide-102.iwa", 401)
    slide = _obj(spec, "Index/Slide-102.iwa", 102)
    slide["drawablesZOrder"] = [{"identifier": 400}]
    slide["ownedDrawables"] = [{"identifier": 400}]
    _set_header_refs(spec, "Index/Slide-102.iwa", 102, [400])
    comp = _component(spec, "Slide-102")
    comp["objectUuidMapEntries"] = [e for e in comp["objectUuidMapEntries"] if e["identifier"] != 401]


# --------------------------------------------------------------------------
# Null controls.
# --------------------------------------------------------------------------
def test_null_deck_vs_itself(base):
    report = ddd.run(base, base)
    assert report["diffs"] == []
    assert report["differing_slides"] == []
    assert report["unallowed"] == 0


def test_null_deck_vs_separately_written_copy(base, tmp_path):
    report = ddd.run(base, _write(_base_spec(), tmp_path / "copy.key"))
    assert report["diffs"] == []


def test_null_consistent_identifier_renumbering(base, tmp_path):
    spec = _base_spec()
    ids = [int(a["header"]["identifier"]) for archives in spec["members"].values() for a in archives]
    mapping = {i: i + 10_000 for i in ids if i != 5}
    renumbered = {
        "members": {name: _renumber(archives, mapping) for name, archives in spec["members"].items()},
        "files": spec["files"],
    }
    other = _write(renumbered, tmp_path / "renumbered.key")
    assert ddd.load_deck(other).archives.keys() != ddd.load_deck(base).archives.keys()

    report = ddd.run(base, other)
    assert report["diffs"] == []


def test_null_random_seed_and_save_token_changes(base, tmp_path):
    def edit(spec):
        build = _obj(spec, "Index/Slide-101.iwa", 500)
        build["attributes"]["animationAttributes"]["randomNumberSeed"] = 424242
        _metadata(spec)["saveToken"] = "99"
        _metadata(spec)["lastObjectIdentifier"] = "2000"

    report = ddd.run(base, _variant(tmp_path, "reseeded", edit))
    assert report["diffs"] == []


def test_null_uuid_values_ignored(base, tmp_path):
    def edit(spec):
        for comp in _metadata(spec)["components"]:
            for entry in comp["objectUuidMapEntries"]:
                entry["uuid"] = {"lower": "123", "upper": "456"}

    report = ddd.run(base, _variant(tmp_path, "uuids", edit))
    assert report["diffs"] == []


# --------------------------------------------------------------------------
# Positive controls.
# --------------------------------------------------------------------------
def test_field_change_on_slide_2_reports_exactly_slide_2(base, tmp_path):
    def edit(spec):
        _obj(spec, "Index/Slide-102.iwa", 400)["super"]["super"]["geometry"]["position"]["x"] = 31

    report = ddd.run(base, _variant(tmp_path, "moved", edit))
    assert report["differing_slides"] == [2]
    assert _keys(report) == [
        "metadata:Slide-102:objectUuidMapEntries",
        "slide:2:KN.SlideArchive.@objectReferences",
        "slide:2:KN.SlideArchive.drawablesZOrder",
        "slide:2:KN.SlideArchive.ownedDrawables",
        "slide:2:TSWP.ShapeInfoArchive.super",
    ]
    assert report["unallowed"] == len(report["diffs"])


def _swap_build_targets(spec):
    b500 = _archive(spec, "Index/Slide-101.iwa", 500)
    b501 = _archive(spec, "Index/Slide-101.iwa", 501)
    b500["objects"][0]["drawable"] = {"identifier": 301}
    b501["objects"][0]["drawable"] = {"identifier": 300}
    b500["header"]["messageInfos"][0]["objectReferences"] = ["301"]
    b501["header"]["messageInfos"][0]["objectReferences"] = ["300"]


def test_swapped_build_refs_reported(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "swapped", _swap_build_targets))
    assert report["differing_slides"] == [1]
    assert "slide:1:KN.BuildArchive.drawable" in _keys(report)
    assert "slide:1:KN.BuildArchive.@objectReferences" in _keys(report)


def test_swapped_build_refs_invisible_with_refs_off(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "swapped", _swap_build_targets), refs=False)
    assert report["diffs"] == []


def test_swapped_build_refs_reported_without_id_pairing(base, tmp_path):
    spec = _base_spec()
    _swap_build_targets(spec)
    mapping = {500: 600, 501: 601}
    spec["members"] = {name: _renumber(archives, mapping) for name, archives in spec["members"].items()}
    report = ddd.run(base, _write(spec, tmp_path / "swapped_reid.key"))
    assert report["differing_slides"] == [1]
    [entry] = [d for d in report["diffs"] if d["key"] == "slide:1:KN.BuildArchive"]
    assert len(entry["a"]) == 2 and len(entry["b"]) == 2


def test_dangling_body_ref_reported(tmp_path):
    good = _variant(tmp_path, "good", _correctly_deleted_401)

    def edit(spec):
        _correctly_deleted_401(spec)
        _obj(spec, "Index/Slide-102.iwa", 102)["drawablesZOrder"].append({"identifier": 401})

    report = ddd.run(good, _variant(tmp_path, "dangling", edit))
    assert report["differing_slides"] == [2]
    [entry] = [d for d in report["diffs"] if d["key"].startswith("slide:")]
    assert entry["key"] == "slide:2:KN.SlideArchive.drawablesZOrder"
    assert entry["b"][-1] == ddd.DANGLING
    assert ddd.DANGLING not in entry["a"]


def test_stale_header_ref_reported(tmp_path):
    good = _variant(tmp_path, "good", _correctly_deleted_401)

    def edit(spec):
        _correctly_deleted_401(spec)
        _set_header_refs(spec, "Index/Slide-102.iwa", 102, [400, 401])

    stale = _variant(tmp_path, "stale", edit)
    report = ddd.run(good, stale)
    [entry] = report["diffs"]
    assert entry["key"] == "slide:2:KN.SlideArchive.@objectReferences"
    assert ddd.DANGLING in entry["b"]
    assert report["differing_slides"] == [2]

    assert ddd.run(good, stale, refs=False)["diffs"] == []


def test_removed_drawable_reports_only_its_slide_lists_header_and_archive(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "deleted", _correctly_deleted_401))
    assert report["differing_slides"] == [2]
    assert _keys(report) == [
        "metadata:Slide-102:objectUuidMapEntries",
        "slide:2:KN.SlideArchive.@objectReferences",
        "slide:2:KN.SlideArchive.drawablesZOrder",
        "slide:2:KN.SlideArchive.ownedDrawables",
        "slide:2:TSWP.ShapeInfoArchive",
    ]
    [removed] = [d for d in report["diffs"] if d["key"] == "slide:2:TSWP.ShapeInfoArchive"]
    assert len(removed["a"]) == 1 and removed["b"] == []


def test_slide_archive_change_does_not_cascade_to_parent_refs(base, tmp_path):
    def edit(spec):
        _obj(spec, "Index/Slide-102.iwa", 102)["name"] = "renamed"

    report = ddd.run(base, _variant(tmp_path, "renamed", edit))
    assert _keys(report) == ["slide:2:KN.SlideArchive.name"]


def test_parent_ref_to_another_slide_reported(base, tmp_path):
    def edit(spec):
        _obj(spec, "Index/Slide-102.iwa", 400)["super"]["super"]["parent"] = {"identifier": 101}
        _set_header_refs(spec, "Index/Slide-102.iwa", 400, [101])

    report = ddd.run(base, _variant(tmp_path, "reparented", edit))
    assert "slide:2:TSWP.ShapeInfoArchive.super" in _keys(report)
    assert "slide:2:TSWP.ShapeInfoArchive.@objectReferences" in _keys(report)


def _with_field_info(spec, member, ident, *, refs=(), data=()):
    info = {"path": {"path": [1]}, "type": "REFERENCE"}
    if refs:
        info["objectReferences"] = [str(r) for r in refs]
    if data:
        info["dataReferences"] = [str(r) for r in data]
    _archive(spec, member, ident)["header"]["messageInfos"][0]["fieldInfos"] = [info]


def test_null_identical_field_infos(base, tmp_path):
    def edit(spec):
        _with_field_info(spec, "Index/Slide-102.iwa", 400, refs=[102])

    one = _variant(tmp_path, "fi1", edit)
    two = _variant(tmp_path, "fi2", edit)
    assert ddd.run(one, two)["diffs"] == []


def test_dangling_field_info_object_ref_reported(tmp_path):
    def good(spec):
        _correctly_deleted_401(spec)
        _with_field_info(spec, "Index/Slide-102.iwa", 400, refs=[102])

    def dangling(spec):
        _correctly_deleted_401(spec)
        _with_field_info(spec, "Index/Slide-102.iwa", 400, refs=[102, 401])

    report = ddd.run(_variant(tmp_path, "good", good), _variant(tmp_path, "dangling", dangling))
    [entry] = report["diffs"]
    assert entry["key"] == "slide:2:TSWP.ShapeInfoArchive.@fieldInfos"
    assert ddd.DANGLING in entry["b"][0]["objectReferences"]


def test_changed_field_info_data_ref_reported(base, tmp_path):
    def photo(spec):
        _with_field_info(spec, "Index/Slide-101.iwa", 301, data=[7001])

    def orphan(spec):
        _with_field_info(spec, "Index/Slide-101.iwa", 301, data=[7002])

    report = ddd.run(_variant(tmp_path, "photo", photo), _variant(tmp_path, "orphan", orphan))
    [entry] = report["diffs"]
    assert entry["key"] == "slide:1:TSD.ImageArchive.@fieldInfos"
    assert entry["a"][0]["dataReferences"] == [f"data:{_DIGEST_PHOTO}"]
    assert entry["b"][0]["dataReferences"] == [f"data:{_DIGEST_ORPHAN}"]


def test_same_count_wrong_uuid_entry_reported(tmp_path):
    def good(spec):
        _correctly_deleted_401(spec)

    def wrong(spec):
        _correctly_deleted_401(spec)
        comp = _component(spec, "Slide-102")
        comp["objectUuidMapEntries"] = [
            e for e in comp["objectUuidMapEntries"] if e["identifier"] != 400
        ] + [{"identifier": 401, "uuid": {"lower": "401", "upper": "7"}}]

    report = ddd.run(_variant(tmp_path, "good", good), _variant(tmp_path, "wrong", wrong))
    [entry] = report["diffs"]
    assert entry["key"] == "metadata:Slide-102:objectUuidMapEntries"
    assert entry["a"][0].startswith("TSWP.ShapeInfoArchive#")
    assert entry["b"] == [ddd.DANGLING]


def test_metadata_data_reference_removal_reported(base, tmp_path):
    def edit(spec):
        _component(spec, "Slide-101")["dataReferences"] = []

    report = ddd.run(base, _variant(tmp_path, "dataref", edit))
    [entry] = report["diffs"]
    assert entry["key"] == "metadata:Slide-101:dataReferences"
    assert entry["b"] == []
    [(data, obj, count)] = entry["a"]
    assert data == f"data:{_DIGEST_PHOTO}"
    assert obj.startswith("TSD.ImageArchive#")
    assert count == 1


def test_metadata_data_reference_retargeted_reported(base, tmp_path):
    def edit(spec):
        _component(spec, "Slide-101")["dataReferences"][0]["objectReferenceList"][0]["objectIdentifier"] = 300

    report = ddd.run(base, _variant(tmp_path, "retarget", edit))
    assert _keys(report) == ["metadata:Slide-101:dataReferences"]


def test_metadata_external_reference_change_reported(base, tmp_path):
    def edit(spec):
        _component(spec, "Slide-101")["externalReferences"][0]["isWeak"] = True

    report = ddd.run(base, _variant(tmp_path, "weak", edit))
    [entry] = report["diffs"]
    assert entry["key"] == "metadata:Slide-101:externalReferences"
    assert entry["a"][0][0] == "DocumentStylesheet" and entry["a"][0][2] is False
    assert entry["b"][0][2] is True


def test_metadata_external_reference_to_missing_object_is_dangling(base, tmp_path):
    def edit(spec):
        _component(spec, "Slide-101")["externalReferences"][0]["objectIdentifier"] = 999

    report = ddd.run(base, _variant(tmp_path, "extdangling", edit))
    [entry] = report["diffs"]
    assert entry["b"][0][1] == ddd.DANGLING


def test_metadata_uuid_entry_and_feature_info_changes_reported(base, tmp_path):
    def edit(spec):
        comp = _component(spec, "Slide-102")
        comp["objectUuidMapEntries"] = comp["objectUuidMapEntries"][:-1]
        comp["featureInfos"] = [{"identifier": "TSDMovieInfoPlaysAcrossSlides"}]

    report = ddd.run(base, _variant(tmp_path, "uuidcount", edit))
    assert _keys(report) == ["metadata:Slide-102:featureInfos", "metadata:Slide-102:objectUuidMapEntries"]


def test_changed_data_digest_reaches_the_referencing_slide(base, tmp_path):
    def edit(spec):
        _metadata(spec)["datas"][0]["digest"] = base64.b64encode(b"other").decode()

    report = ddd.run(base, _variant(tmp_path, "digest", edit))
    keys = _keys(report)
    assert "slide:1:TSD.ImageArchive.data" in keys
    assert "slide:1:TSD.ImageArchive.@dataReferences" in keys
    assert "datas:photo.jpg" in keys
    assert "metadata:Slide-101:dataReferences" in keys


def _drop_orphan_data(spec):
    _metadata(spec)["datas"] = [d for d in _metadata(spec)["datas"] if d["identifier"] != 7002]
    del spec["files"]["Data/orphan-7002.png"]


def test_dropped_data_member_and_datas_entry_reported(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "nodata", _drop_orphan_data))
    assert _keys(report) == ["datas:orphan.png", "zip:Data/orphan.png"]
    assert report["unallowed"] == 2


def test_dropped_data_silenced_by_allow(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "nodata", _drop_orphan_data), allow=[r"^(zip:Data/|datas:)"])
    assert len(report["diffs"]) == 2
    assert report["unallowed"] == 0
    assert all(d["allowed"] for d in report["diffs"])


def test_non_iwa_member_content_change_reported(base, tmp_path):
    def edit(spec):
        spec["files"]["preview.jpg"] = b"\xff\xd8other"

    report = ddd.run(base, _variant(tmp_path, "preview", edit))
    assert _keys(report) == ["zip:preview.jpg"]


def test_non_slide_member_change_reported_by_member(base, tmp_path):
    def edit(spec):
        _obj(spec, "Index/DocumentStylesheet.iwa", 900)["super"]["styleIdentifier"] = "image-9-imageStyle"

    report = ddd.run(base, _variant(tmp_path, "style", edit))
    keys = _keys(report)
    assert "member:Index/DocumentStylesheet.iwa:TSD.MediaStyleArchive.super" in keys
    assert "slide:1:TSD.ImageArchive.style" in keys
    assert "metadata:Slide-101:externalReferences" in keys


def test_extra_slide_reported(base, tmp_path):
    def edit(spec):
        show = _obj(spec, "Index/Document.iwa", 2)
        show["slideTree"]["slides"].append({"identifier": 11})

    report = ddd.run(base, _variant(tmp_path, "extra", edit))
    assert "slide:3" in _keys(report)
    assert 3 in report["differing_slides"]


# --------------------------------------------------------------------------
# Helpers and CLI.
# --------------------------------------------------------------------------
def test_normalise_zip_name_strips_data_id_and_fixes_cp437():
    assert ddd.normalise_zip_name("Data/photo-7001.jpg") == "Data/photo.jpg"
    assert ddd.normalise_zip_name("Data/a-b-12.png") == "Data/a-b.png"
    mojibake = "Data/café-5.jpg".encode().decode("cp437")
    assert ddd.normalise_zip_name(mojibake) == "Data/café.jpg"
    assert ddd.normalise_zip_name("preview.jpg") == "preview.jpg"
    assert ddd.normalise_zip_name("Data/no-id.jpg") == "Data/no-id.jpg"


def test_cli_exit_codes_and_json(base, tmp_path, capsys):
    nodata = _variant(tmp_path, "nodata", _drop_orphan_data)
    out = tmp_path / "report.json"

    assert ddd.main([str(base), str(base)]) == 0
    assert ddd.main([str(base), str(nodata), "--json", str(out)]) == 1
    report = json.loads(out.read_text())
    assert report["unallowed"] == 2
    assert sorted(d["key"] for d in report["diffs"]) == ["datas:orphan.png", "zip:Data/orphan.png"]

    assert ddd.main([str(base), str(nodata), "--allow", "^zip:Data/", "--allow", "^datas:"]) == 0
    assert ddd.main([str(base), str(nodata), "--allow", "^zip:"]) == 1
    printed = capsys.readouterr().out
    assert "DIFF    datas:orphan.png" in printed
    assert "allowed zip:Data/orphan.png" in printed


def test_cli_undecodable_member_exits_2(base, tmp_path, capsys):
    bad = tmp_path / "bad.key"
    bad.write_bytes(base.read_bytes())
    with zipfile.ZipFile(bad, "a") as zf:
        zf.writestr("Index/Bogus.iwa", b"not a valid iwa chunk")
    assert ddd.main([str(base), str(bad)]) == 2
    assert "Index/Bogus.iwa" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Versioned Metadata tables: components[].versionedExternalReferences,
# components[].ambiguousObjectIdentifiers, and every table of versionedComponents.
# --------------------------------------------------------------------------
def _versioned_component(target):
    return {
        "identifier": 8000, "locator": "Slide-102-v1", "preferredLocator": "Slide",
        "externalReferences": [{"componentIdentifier": 900, "objectIdentifier": 900}],
        "dataReferences": [{"dataIdentifier": 7001,
                            "objectReferenceList": [{"objectIdentifier": target, "count": 1}]}],
        "objectUuidMapEntries": [{"identifier": target, "uuid": {"lower": "1", "upper": "8"}}],
        "versionedExternalReferences": [{"componentIdentifier": 102, "objectIdentifier": target}],
        "ambiguousObjectIdentifiers": [target],
    }


def _versioned_spec(spec, target=401):
    comp = _component(spec, "Slide-101")
    comp["versionedExternalReferences"] = [{"componentIdentifier": 102, "objectIdentifier": target}]
    comp["ambiguousObjectIdentifiers"] = [target]
    _metadata(spec)["versionedComponents"] = [_versioned_component(target)]


def _set_component_versioned_ext(spec, ident):
    _component(spec, "Slide-101")["versionedExternalReferences"][0]["objectIdentifier"] = ident


def _set_component_ambiguous(spec, ident):
    _component(spec, "Slide-101")["ambiguousObjectIdentifiers"] = [ident]


def _versioned(spec):
    return _metadata(spec)["versionedComponents"][0]


def _set_versioned_ext(spec, ident):
    _versioned(spec)["externalReferences"][0]["objectIdentifier"] = ident


def _set_versioned_data(spec, ident):
    _versioned(spec)["dataReferences"][0]["objectReferenceList"][0]["objectIdentifier"] = ident


def _set_versioned_uuid(spec, ident):
    _versioned(spec)["objectUuidMapEntries"][0]["identifier"] = ident


def _set_versioned_versioned_ext(spec, ident):
    _versioned(spec)["versionedExternalReferences"][0]["objectIdentifier"] = ident


def _set_versioned_ambiguous(spec, ident):
    _versioned(spec)["ambiguousObjectIdentifiers"] = [ident]


def test_null_versioned_tables(tmp_path):
    one = _variant(tmp_path, "v1", _versioned_spec)
    two = _variant(tmp_path, "v2", _versioned_spec)
    assert ddd.run(one, two)["diffs"] == []
    deck = ddd.load_deck(one)
    tables = ddd._component_tables(deck, ddd._components(deck, "versionedComponents")["Slide-102-v1"])
    assert all(ddd.DANGLING not in repr(rows) for rows in tables.values())
    assert tables["dataReferences"][0][1].startswith("TSWP.ShapeInfoArchive#")


@pytest.mark.parametrize(("setter", "key"), [
    (_set_component_versioned_ext, "metadata:Slide-101:versionedExternalReferences"),
    (_set_component_ambiguous, "metadata:Slide-101:ambiguousObjectIdentifiers"),
    (_set_versioned_ext, "metadata:versioned:Slide-102-v1:externalReferences"),
    (_set_versioned_data, "metadata:versioned:Slide-102-v1:dataReferences"),
    (_set_versioned_uuid, "metadata:versioned:Slide-102-v1:objectUuidMapEntries"),
    (_set_versioned_versioned_ext, "metadata:versioned:Slide-102-v1:versionedExternalReferences"),
    (_set_versioned_ambiguous, "metadata:versioned:Slide-102-v1:ambiguousObjectIdentifiers"),
])
def test_dangling_versioned_ref_reported(tmp_path, setter, key):
    good = _variant(tmp_path, "good", _versioned_spec)

    def dangling(spec):
        _versioned_spec(spec)
        setter(spec, 999)

    report = ddd.run(good, _variant(tmp_path, "dangling", dangling))
    [entry] = report["diffs"]
    assert entry["key"] == key
    assert ddd.DANGLING in repr(entry["b"])
    assert ddd.DANGLING not in repr(entry["a"])


def test_versioned_component_presence_reported(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "v", lambda spec: _metadata(spec).update(
        versionedComponents=[_versioned_component(401)])))
    assert _keys(report) == ["metadata:versioned:Slide-102-v1"]


# --------------------------------------------------------------------------
# Non-projected PackageMetadata fields, with METADATA_CHURN removed.
# --------------------------------------------------------------------------
def test_metadata_churn_constant():
    assert ddd.METADATA_CHURN == {"saveToken", "revision", "lastObjectIdentifier"}


def test_null_metadata_churn_only(base, tmp_path):
    def edit(spec):
        meta = _metadata(spec)
        meta["saveToken"] = "77"
        meta["revision"] = {"sequence32": 9, "identifier": "rev-b"}
        meta["lastObjectIdentifier"] = "5000"
        for comp in meta["components"]:
            comp["saveToken"] = "3"

    assert ddd.run(base, _variant(tmp_path, "churn", edit))["diffs"] == []


def test_data_metadata_map_retarget_reported(base, tmp_path):
    def edit(spec):
        _metadata(spec)["dataMetadataMap"] = {"identifier": 999}

    report = ddd.run(base, _variant(tmp_path, "dmm", edit))
    [entry] = report["diffs"]
    assert entry["key"] == "metadata:package.dataMetadataMap"
    assert entry["a"].startswith("TSP.DataMetadataMap#")
    assert entry["b"] == ddd.DANGLING


def test_data_metadata_map_dropped_reported(base, tmp_path):
    def edit(spec):
        del _metadata(spec)["dataMetadataMap"]

    report = ddd.run(base, _variant(tmp_path, "nodmm", edit))
    assert _keys(report) == ["metadata:package.dataMetadataMap"]


def test_package_scalar_field_change_reported(base, tmp_path):
    def edit(spec):
        _metadata(spec)["fileFormatVersion"] = [14, 5, 0]

    report = ddd.run(base, _variant(tmp_path, "ffv", edit))
    assert _keys(report) == ["metadata:package.fileFormatVersion"]


def test_component_non_projected_field_change_reported(base, tmp_path):
    def edit(spec):
        _component(spec, "Slide-102")["canBeDropped"] = True

    report = ddd.run(base, _variant(tmp_path, "drop", edit))
    assert _keys(report) == ["metadata:Slide-102:fields"]


def test_datas_non_projected_field_change_reported(base, tmp_path):
    def edit(spec):
        _metadata(spec)["datas"][1]["canDownload"] = True

    report = ddd.run(base, _variant(tmp_path, "dl", edit))
    assert _keys(report) == ["datas:orphan.png"]


def test_datas_file_name_id_suffix_ignored(base, tmp_path):
    def edit(spec):
        _metadata(spec)["datas"][1]["fileName"] = "orphan-8888.png"

    assert ddd.run(base, _variant(tmp_path, "fn", edit))["diffs"] == []


# --------------------------------------------------------------------------
# Duplicate archive ids / a second PackageMetadata are rejected at load.
# --------------------------------------------------------------------------
def _duplicate_shape_400(spec, x):
    dup = copy.deepcopy(_archive(spec, "Index/Slide-102.iwa", 400))
    dup["objects"][0]["super"]["super"]["geometry"]["position"]["x"] = x
    spec["members"]["Index/Slide-102.iwa"].append(dup)


def test_duplicate_archive_id_cannot_compare_green(tmp_path, capsys):
    one = _variant(tmp_path, "dup1", lambda spec: _duplicate_shape_400(spec, 1))
    two = _variant(tmp_path, "dup2", lambda spec: _duplicate_shape_400(spec, 2))
    with pytest.raises(ddd.DuplicateArchive) as exc:
        ddd.run(one, two)
    assert "archive id 400 at Index/Slide-102.iwa#1 and Index/Slide-102.iwa#3" in str(exc.value)
    assert ddd.main([str(one), str(two)]) == 2
    assert ddd.main([str(one), str(one)]) == 2
    assert "duplicate archive" in capsys.readouterr().err


def test_duplicate_archive_id_across_members_rejected(tmp_path):
    def edit(spec):
        spec["members"]["Index/DocumentStylesheet.iwa"].append(copy.deepcopy(_archive(spec, "Index/Slide-102.iwa", 401)))

    with pytest.raises(ddd.DuplicateArchive, match="archive id 401 at .*#\\d+ and .*#\\d+"):
        ddd.load_deck(_variant(tmp_path, "cross", edit))


def test_second_package_metadata_rejected(tmp_path, capsys):
    def edit(spec):
        second = copy.deepcopy(_archive(spec, "Index/Metadata.iwa", 5))
        second["header"]["identifier"] = 55
        for info in second["header"]["messageInfos"]:
            info["identifier"] = 55
        spec["members"]["Index/Metadata.iwa"].append(second)

    deck = _variant(tmp_path, "twometa", edit)
    with pytest.raises(ddd.DuplicateArchive, match="TSP.PackageMetadata at Index/Metadata.iwa#0 and Index/Metadata.iwa#2"):
        ddd.load_deck(deck)
    assert ddd.main([str(deck), str(deck)]) == 2
    assert "duplicate archive" in capsys.readouterr().err
