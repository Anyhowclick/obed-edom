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


def _base_spec():
    shape300 = _arch(300, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(10, 20, 100, 50)})
    image301 = _with_data_refs(_with_refs(_arch(301, "TSD.ImageArchive", {
        "data": {"identifier": 7001}, "style": {"identifier": 900}, "super": _geom(300, 100, 120, 60),
        "originalSize": {"width": 120.0, "height": 60.0},
    }), [900]), [7001])
    build500 = _build("apple:dissolve", 300)
    build501 = _build("apple:wipe-iris", 301)
    slide101 = _with_refs(_arch(101, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": 300}, {"identifier": 301}],
        "ownedDrawables": [{"identifier": 300}, {"identifier": 301}],
        "builds": [{"identifier": 500}, {"identifier": 501}],
    }), [300, 301, 500, 501])
    shape400 = _arch(400, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(30, 40, 80, 60)})
    shape401 = _arch(401, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(50, 60, 20, 20)})
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
            "Index/Metadata.iwa": [metadata],
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
        if key in _ID_KEYS and not isinstance(item, (dict, list)) and int(item) in mapping:
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
        _obj(spec, "Index/Slide-102.iwa", 400)["super"] = _shape_super(31, 40, 80, 60)

    report = ddd.run(base, _variant(tmp_path, "moved", edit))
    assert report["differing_slides"] == [2]
    assert _keys(report) == [
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


def test_undeleted_vs_deleted_reports_only_that_slide_and_its_metadata(base, tmp_path):
    report = ddd.run(base, _variant(tmp_path, "deleted", _correctly_deleted_401))
    assert report["differing_slides"] == [2]
    assert {k.split(":")[0] for k in _keys(report)} == {"slide", "member", "metadata"}
    assert "metadata:Slide-102:objectUuidMapEntries" in _keys(report)
    assert "slide:2:TSWP.ShapeInfoArchive" in _keys(report)


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
