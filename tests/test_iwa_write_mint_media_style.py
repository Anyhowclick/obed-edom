"""Offline tests for ``iwa_write.mint_media_style`` (no Keynote).

Reuses the ``_build_deck`` synthetic stylesheet fixture from ``test_stroke_probe``
(styles 900/901 in ``Index/DocumentStylesheet.iwa``), extended with
``stylesheet_root``/``metadata`` for the mint's registration footprint.
"""
from __future__ import annotations

import copy
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_runs import _load_deck, _load_deck_full  # noqa: E402
from obed_edom.iwa_write import _resolve_stroke, card_styles, mint_media_style  # noqa: E402
from scripts.write_gate_ab import changed_members  # noqa: E402
from test_iwa_write import _arch, _geom  # noqa: E402
from test_stroke_probe import (  # noqa: E402
    _METADATA_ARCHIVE_ID, _STYLESHEET_ROOT_ID, _WHITE_SOLID_STROKE, _build_deck, _with_refs,
)

_WHITE_SPEC = {"width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"}
_NEW_MEDIA_STYLE_ID = "1001"


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "mint.key", stylesheet_root=True, metadata=True)


def test_refuses_empty_drawables(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", [], _WHITE_SPEC)
    assert result["refused"]
    assert "empty" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_unknown_source_style(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "999999", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert deck.read_bytes() == before


def test_refuses_wrong_archive_type(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "300", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "TSD.MediaStyleArchive" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_drawable_not_pointing_at_source(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["302"], _WHITE_SPEC)
    assert result["refused"]
    assert "does not point at style 900" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_on_undecodable_extra_member(tmp_path):
    deck = _build_deck(tmp_path / "bogus.key", stylesheet_root=True, metadata=True)
    with zipfile.ZipFile(deck, "a") as zf:
        zf.writestr("Index/Bogus.iwa", b"not a valid iwa chunk")
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "Index/Bogus.iwa" in result["reason"]
    assert deck.read_bytes() == before

    objects, _id_to_file, _file_ids = _load_deck(deck)
    assert "900" in objects


def test_refuses_when_metadata_member_missing(tmp_path):
    deck = _build_deck(tmp_path / "no_meta.key", stylesheet_root=True, metadata=False)
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "Index/Metadata.iwa" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_new_id_already_taken(tmp_path):
    collide = _arch(1001, "TSD.MediaStyleArchive", {"super": {"styleIdentifier": "collide-style"}})
    deck = _build_deck(
        tmp_path / "collide.key", stylesheet_root=True, metadata=True, extra_stylesheet_archives=(collide,),
    )
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "1001" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_new_id_already_taken_by_object_less_archive(tmp_path):
    collide = {
        "header": {
            "_pbtype": "TSP.ArchiveInfo",
            "identifier": 1001,
            "messageInfos": [{"_pbtype": "TSP.MessageInfo", "type": 1, "identifier": 1001}],
        },
        "objects": [],
    }
    deck = _build_deck(
        tmp_path / "collide_object_less.key", stylesheet_root=True, metadata=True,
        extra_stylesheet_archives=(collide,),
    )
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "1001" in result["reason"]
    assert deck.read_bytes() == before


def test_build_deck_stylesheet_root_round_trips(deck):
    objects, id_to_file, _fi = _load_deck(deck)
    assert str(_STYLESHEET_ROOT_ID) in objects
    assert objects["900"]["super"]["stylesheet"]["identifier"] == str(_STYLESHEET_ROOT_ID)
    assert len(objects[str(_METADATA_ARCHIVE_ID)]["components"]) == 3


def test_mints_variation_archive_shaped_like_keynote(deck):
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]
    objects, _id_to_file, _fi = _load_deck(deck)
    minted = objects[result["new_id"]]
    assert minted == {
        "_pbtype": "TSD.MediaStyleArchive",
        "super": {
            "parent": {"identifier": "900"},
            "isVariation": True,
            "stylesheet": {"identifier": str(_STYLESHEET_ROOT_ID)},
        },
        "overrideCount": 1,
        "mediaProperties": {"stroke": {
            "color": {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"},
            "width": 5.0,
            "cap": "ButtCap",
            "join": "MiterJoin",
            "miterLimit": 4.0,
            "pattern": {"type": "TSDSolidPattern", "phase": 0.0, "count": 0, "pattern": [0.0] * 6},
        }},
    }


def test_minted_archive_header_references_parent(deck):
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]

    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/DocumentStylesheet.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/DocumentStylesheet.iwa").to_dict()
    minted_header = None
    source_header = None
    for ch in decoded["chunks"]:
        for arch in ch["archives"]:
            aid = str(arch["header"]["identifier"])
            if aid == result["new_id"]:
                minted_header = arch["header"]
            elif aid == "900":
                source_header = arch["header"]
    assert minted_header is not None and source_header is not None
    minted_mi = minted_header["messageInfos"][0]
    source_mi = source_header["messageInfos"][0]
    assert minted_mi["type"] == source_mi["type"] == 3016
    assert minted_mi["version"] == source_mi["version"] == [1, 0, 5]
    assert minted_mi["objectReferences"] == ["900"]


def test_registers_in_styles_and_parent_map_only(deck):
    before_objects, _b1, _b2 = _load_deck(deck)
    before_root = copy.deepcopy(before_objects[str(_STYLESHEET_ROOT_ID)])

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]

    objects, _id_to_file, _fi = _load_deck(deck)
    root = objects[str(_STYLESHEET_ROOT_ID)]
    assert {"identifier": result["new_id"]} in root["styles"]
    assert len(root["styles"]) == len(before_root["styles"]) + 1
    assert root["identifierToStyleMap"] == before_root["identifierToStyleMap"]
    matching = [e for e in root["parentToChildrenStyleMap"] if e["parent"]["identifier"] == "900"]
    assert len(matching) == 1
    assert matching[0]["children"] == [{"identifier": result["new_id"]}]


def test_resolve_stroke_reaches_minted_style(deck):
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]
    objects, _id_to_file, _fi = _load_deck(deck)
    stroke, inherited = _resolve_stroke(result["new_id"], objects)
    assert inherited is False
    assert stroke["width"] == pytest.approx(5.0)


def test_repoints_only_named_drawables(deck):
    result = mint_media_style(deck, "900", ["300", "301"], _WHITE_SPEC)
    assert not result["refused"]
    objects, _id_to_file, _fi = _load_deck(deck)
    assert objects["300"]["style"]["identifier"] == result["new_id"]
    assert objects["301"]["style"]["identifier"] == result["new_id"]
    assert objects["303"]["style"]["identifier"] == "900"
    assert objects["304"]["style"]["identifier"] == "900"


def test_repoints_group_child_drawable(deck):
    before_objects, _b1, _b2 = _load_deck(deck)
    before_group = copy.deepcopy(before_objects["250"])

    result = mint_media_style(deck, "900", ["303"], _WHITE_SPEC)
    assert not result["refused"]

    objects, _id_to_file, _fi = _load_deck(deck)
    assert objects["303"]["style"]["identifier"] == result["new_id"]
    assert objects["250"] == before_group


def test_rewrites_drawable_header_object_references(tmp_path):
    two_refs = _with_refs(
        _arch(306, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(240, 0, 50, 50)}),
        [901, 900],
    )
    deck = _build_deck(
        tmp_path / "two_refs.key", stylesheet_root=True, metadata=True,
        extra_slide_archives=(two_refs,), extra_zorder=(306,),
    )

    result = mint_media_style(deck, "900", ["306"], _WHITE_SPEC)
    assert not result["refused"]

    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/Slide-100.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/Slide-100.iwa").to_dict()
    found = False
    for ch in decoded["chunks"]:
        for arch in ch["archives"]:
            if str(arch["header"]["identifier"]) == "306":
                found = True
                refs = arch["header"]["messageInfos"][0]["objectReferences"]
                assert refs == ["901", result["new_id"]]
    assert found, "drawable 306 not found in reparsed member"


def test_refuses_when_header_has_zero_references(tmp_path):
    no_refs = _arch(305, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(240, 0, 50, 50)})
    deck = _build_deck(
        tmp_path / "no_refs.key", stylesheet_root=True, metadata=True,
        extra_slide_archives=(no_refs,), extra_zorder=(305,),
    )
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["305"], _WHITE_SPEC)
    assert result["refused"]
    assert "305" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_header_reference_count_is_not_one(tmp_path):
    doubled = _with_refs(
        _arch(305, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(240, 0, 50, 50)}),
        [900, 900],
    )
    deck = _build_deck(
        tmp_path / "doubled.key", stylesheet_root=True, metadata=True,
        extra_slide_archives=(doubled,), extra_zorder=(305,),
    )
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["305"], _WHITE_SPEC)
    assert result["refused"]
    assert "305" in result["reason"]
    assert deck.read_bytes() == before


def test_bumps_last_object_identifier(deck):
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]

    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/Metadata.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/Metadata.iwa").to_dict()
    pm = decoded["chunks"][0]["archives"][0]["objects"][0]
    assert pm["lastObjectIdentifier"] == result["new_id"]


def test_adds_uuid_map_entry_for_minted_style(deck):
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]

    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/Metadata.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/Metadata.iwa").to_dict()
    pm = decoded["chunks"][0]["archives"][0]["objects"][0]
    stylesheet_component = next(c for c in pm["components"] if c["identifier"] == str(_STYLESHEET_ROOT_ID))
    new_entries = [e for e in stylesheet_component["objectUuidMapEntries"] if e["identifier"] == result["new_id"]]
    assert len(new_entries) == 1
    uuid = new_entries[0]["uuid"]
    assert int(uuid["lower"]) != 0 or int(uuid["upper"]) != 0
    other_uuids = {
        (e["uuid"]["lower"], e["uuid"]["upper"])
        for c in pm["components"] for e in c.get("objectUuidMapEntries") or []
        if e["identifier"] != result["new_id"]
    }
    assert (uuid["lower"], uuid["upper"]) not in other_uuids


def test_adds_external_reference_to_each_drawable_component(deck):
    result = mint_media_style(deck, "900", ["300", "301"], _WHITE_SPEC)
    assert not result["refused"]

    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/Metadata.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/Metadata.iwa").to_dict()
    pm = decoded["chunks"][0]["archives"][0]["objects"][0]
    slide_component = next(c for c in pm["components"] if c["identifier"] == "100")
    matches = [
        r for r in slide_component.get("externalReferences") or []
        if r["componentIdentifier"] == str(_STYLESHEET_ROOT_ID) and r["objectIdentifier"] == result["new_id"]
    ]
    assert len(matches) == 1


def test_only_expected_members_change(deck, tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(deck.read_bytes())

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]
    assert changed_members(original, deck) == {
        "Index/DocumentStylesheet.iwa", "Index/Slide-100.iwa", "Index/Metadata.iwa",
    }


def test_refuses_and_leaves_deck_untouched_when_reparse_adds_extra_archive(deck, monkeypatch):
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    mutated = {"fired": False}
    target_member = "Index/DocumentStylesheet.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                mutated["fired"] = True
                decoded = orig_to_dict()
                bogus = copy.deepcopy(decoded["chunks"][0]["archives"][0])
                bogus["header"]["identifier"] = "999999"
                decoded["chunks"][0]["archives"].append(bogus)
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert mutated["fired"]
    assert result["refused"]
    assert deck.read_bytes() == before


def test_mint_survives_reload(deck):
    result = mint_media_style(deck, "900", ["300", "301"], _WHITE_SPEC)
    assert not result["refused"]

    objects, id_to_file, _fi = _load_deck(deck)
    styles = {s["id"]: s for s in card_styles(objects, id_to_file)}
    new_id = result["new_id"]
    assert styles[new_id]["refs"] == 2
    assert styles[new_id]["width"] == pytest.approx(5.0)
    assert styles[new_id]["inherited"] is False
    assert styles["900"]["width"] == pytest.approx(0.25)


def test_refuses_synthesized_spec_missing_color_instead_of_raising(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], {"width": 5.0})
    assert result["refused"]
    assert "color" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_synthesized_spec_with_non_positive_width_instead_of_raising(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], {"width": 0.0, "color": (1.0, 1.0, 1.0, 1.0)})
    assert result["refused"]
    assert "width" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_nan_width(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], {"width": float("nan"), "color": (1.0, 1.0, 1.0, 1.0)})
    assert result["refused"]
    assert "width" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_infinite_width(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], {"width": float("inf"), "color": (1.0, 1.0, 1.0, 1.0)})
    assert result["refused"]
    assert "width" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_bool_width(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], {"width": True, "color": (1.0, 1.0, 1.0, 1.0)})
    assert result["refused"]
    assert "width" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_bool_color_component(deck):
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], {"width": 5.0, "color": (1.0, 1.0, 1.0, True)})
    assert result["refused"]
    assert "color" in result["reason"]
    assert deck.read_bytes() == before


def test_stylesheet_root_header_is_byte_equal_after_mint(deck):
    import zipfile

    from keynote_parser.codec import IWAFile

    def _root_header(buf):
        decoded = IWAFile.from_buffer(buf, "Index/DocumentStylesheet.iwa").to_dict()
        return next(
            arch["header"] for ch in decoded["chunks"] for arch in ch["archives"]
            if str(arch["header"]["identifier"]) == str(_STYLESHEET_ROOT_ID)
        )

    with zipfile.ZipFile(deck) as zf:
        before_header = _root_header(zf.read("Index/DocumentStylesheet.iwa"))
    assert before_header["messageInfos"][0]["objectReferences"] == ["900", "901"]

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]

    with zipfile.ZipFile(deck) as zf:
        after_header = _root_header(zf.read("Index/DocumentStylesheet.iwa"))
    assert after_header == before_header


def _rewrite_metadata_components(deck, components):
    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        others = {n: zf.read(n) for n in zf.namelist() if n != "Index/Metadata.iwa"}
        meta_buf = zf.read("Index/Metadata.iwa")
    decoded = IWAFile.from_buffer(meta_buf, "Index/Metadata.iwa").to_dict()
    decoded["chunks"][0]["archives"][0]["objects"][0]["components"] = components
    new_meta_buf = IWAFile.from_dict(decoded).to_buffer()
    with zipfile.ZipFile(deck, "w") as zf:
        for name, data in others.items():
            zf.writestr(name, data)
        zf.writestr("Index/Metadata.iwa", new_meta_buf)


def test_tolerates_a_duplicate_locator_on_a_component_not_needed_by_the_mint(deck):
    objects, _id_to_file, _fi = _load_deck(deck)
    pm = objects[str(_METADATA_ARCHIVE_ID)]
    components = copy.deepcopy(pm["components"])
    unrelated = next(c for c in components if c["preferredLocator"] == "Document")
    duplicate = copy.deepcopy(unrelated)
    duplicate["identifier"] = "9999"
    components.append(duplicate)
    _rewrite_metadata_components(deck, components)

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"], result.get("reason")


def test_refuses_when_a_needed_locator_is_ambiguous(deck):
    objects, _id_to_file, _fi = _load_deck(deck)
    pm = objects[str(_METADATA_ARCHIVE_ID)]
    components = copy.deepcopy(pm["components"])
    needed = next(c for c in components if c["preferredLocator"] == "DocumentStylesheet")
    duplicate = copy.deepcopy(needed)
    duplicate["identifier"] = "9998"
    components.append(duplicate)
    _rewrite_metadata_components(deck, components)

    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "DocumentStylesheet" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_reparse_drops_stylesheet_root_registration(deck, monkeypatch):
    """Refuses, deck untouched, when the reparsed stylesheet root drops the mint's registration."""
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    mutated = {"fired": False}
    target_member = "Index/DocumentStylesheet.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                mutated["fired"] = True
                decoded = orig_to_dict()
                root = iwa_write_mod._find_archive(decoded, str(_STYLESHEET_ROOT_ID))["objects"][0]
                root["styles"] = root["styles"][:-1]
                last_entry = root["parentToChildrenStyleMap"][-1]
                last_entry["children"] = last_entry["children"][:-1]
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert mutated["fired"]
    assert result["refused"]
    assert f"archive {_STYLESHEET_ROOT_ID} does not match intended patch after reparse" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_reparse_drops_drawable_update(deck, monkeypatch):
    """Refuses, deck untouched, when the reparsed drawable's style.identifier is corrupted."""
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    mutated = {"fired": False}
    target_member = "Index/Slide-100.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                mutated["fired"] = True
                decoded = orig_to_dict()
                arch = iwa_write_mod._find_archive(decoded, "300")
                arch["objects"][0]["style"]["identifier"] = "999999"
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert mutated["fired"]
    assert result["refused"]
    assert "archive 300 does not match intended patch after reparse" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_reparse_drops_metadata_change(deck, monkeypatch):
    """Refuses, deck untouched, when the reparsed metadata archive drops the uuid map entry."""
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    mutated = {"fired": False}
    target_member = "Index/Metadata.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                mutated["fired"] = True
                decoded = orig_to_dict()
                pm = iwa_write_mod._find_package_metadata_archive(decoded)["objects"][0]
                stylesheet_component = next(
                    c for c in pm["components"] if c["identifier"] == str(_STYLESHEET_ROOT_ID)
                )
                stylesheet_component["objectUuidMapEntries"] = stylesheet_component["objectUuidMapEntries"][:-1]
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert mutated["fired"]
    assert result["refused"]
    assert f"archive {_METADATA_ARCHIVE_ID} does not match intended patch after reparse" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_reparse_drops_minted_header_version(deck, monkeypatch):
    """Refuses, deck untouched, when the reparsed minted archive header drops its version."""
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    mutated = {"fired": False}
    target_member = "Index/DocumentStylesheet.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                mutated["fired"] = True
                decoded = orig_to_dict()
                minted = decoded["chunks"][0]["archives"][-1]
                del minted["header"]["messageInfos"][0]["version"]
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert mutated["fired"]
    assert result["refused"]
    assert f"archive {_NEW_MEDIA_STYLE_ID} does not match intended patch after reparse" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_reparse_alters_uuid_map_entry(deck, monkeypatch):
    """Refuses, deck untouched, when the reparsed metadata archive's minted uuid entry is altered."""
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    mutated = {"fired": False}
    target_member = "Index/Metadata.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                mutated["fired"] = True
                decoded = orig_to_dict()
                pm = iwa_write_mod._find_package_metadata_archive(decoded)["objects"][0]
                stylesheet_component = next(
                    c for c in pm["components"] if c["identifier"] == str(_STYLESHEET_ROOT_ID)
                )
                entry = stylesheet_component["objectUuidMapEntries"][-1]
                lower = entry["uuid"]["lower"]
                entry["uuid"]["lower"] = type(lower)(int(lower) ^ 1)
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert mutated["fired"]
    assert result["refused"]
    assert f"archive {_METADATA_ARCHIVE_ID} does not match intended patch after reparse" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_hostile_source_style_id_str_instead_of_raising(deck):
    class _Hostile:
        def __str__(self):
            raise RuntimeError("boom")

    before = deck.read_bytes()
    result = mint_media_style(deck, _Hostile(), ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert "not str()-coercible" in result["reason"]
    assert deck.read_bytes() == before


def _stroke_message(width):
    return {
        "color": {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"},
        "width": width,
        "cap": "ButtCap",
        "join": "MiterJoin",
        "miterLimit": 4.0,
        "pattern": {
            "type": "TSDSolidPattern", "phase": 0.0, "count": 0,
            "pattern": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
    }


def test_mints_with_float32_inexact_width_from_stroke_message(deck):
    width = 5.0 / 1.5
    result = mint_media_style(deck, "900", ["300"], {"stroke_message": _stroke_message(width)})
    assert not result["refused"], result.get("reason")

    objects, id_to_file, _fi = _load_deck(deck)
    stroke, _inherited = _resolve_stroke(result["new_id"], objects)
    assert stroke["width"] == pytest.approx(width, rel=1e-6)


def test_refuses_stroke_message_with_unknown_key(deck):
    before = deck.read_bytes()
    message = _stroke_message(5.0)
    message["bogusField"] = 1.0
    result = mint_media_style(deck, "900", ["300"], {"stroke_message": message})
    assert result["refused"]
    assert "bogusField" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_stroke_message_with_unknown_nested_key(deck):
    before = deck.read_bytes()
    message = _stroke_message(5.0)
    message["color"]["rgbspce"] = message["color"].pop("rgbspace")
    result = mint_media_style(deck, "900", ["300"], {"stroke_message": message})
    assert result["refused"]
    assert "color.rgbspce" in result["reason"]
    assert deck.read_bytes() == before


def test_load_deck_matches_load_deck_full_prefix(deck):
    assert _load_deck(deck) == _load_deck_full(deck)[:3]


def test_refuses_stroke_message_with_nan_color_component(deck):
    before = deck.read_bytes()
    message = _stroke_message(5.0)
    message["color"]["r"] = float("nan")
    result = mint_media_style(deck, "900", ["300"], {"stroke_message": message})
    assert result["refused"]
    assert "non-finite" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_stroke_message_with_bool_color_component(deck):
    before = deck.read_bytes()
    message = _stroke_message(5.0)
    message["color"]["r"] = True
    result = mint_media_style(deck, "900", ["300"], {"stroke_message": message})
    assert result["refused"]
    assert "non-finite" in result["reason"]
    assert deck.read_bytes() == before


def test_regenerates_uuid_when_randbits_returns_zero(deck, monkeypatch):
    import obed_edom.iwa_write as iwa_write_mod

    calls = iter([0, 0, 123, 456])
    monkeypatch.setattr(iwa_write_mod.secrets, "randbits", lambda n: next(calls))

    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert not result["refused"]

    import zipfile

    from keynote_parser.codec import IWAFile
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/Metadata.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/Metadata.iwa").to_dict()
    pm = decoded["chunks"][0]["archives"][0]["objects"][0]
    stylesheet_component = next(c for c in pm["components"] if c["identifier"] == str(_STYLESHEET_ROOT_ID))
    entry = next(e for e in stylesheet_component["objectUuidMapEntries"] if e["identifier"] == result["new_id"])
    assert (entry["uuid"]["lower"], entry["uuid"]["upper"]) == ("123", "456")


def test_refuses_when_candidate_id_already_registered_in_root_styles(deck):
    import zipfile

    from keynote_parser.codec import IWAFile

    import obed_edom.iwa_write as iwa_write_mod

    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/DocumentStylesheet.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/DocumentStylesheet.iwa").to_dict()
    root = iwa_write_mod._find_archive(decoded, str(_STYLESHEET_ROOT_ID))["objects"][0]
    root["styles"].append({"identifier": _NEW_MEDIA_STYLE_ID})
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    iwa_write_mod._rewrite_members(deck, {"Index/DocumentStylesheet.iwa": new_bytes})

    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert _NEW_MEDIA_STYLE_ID in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_candidate_id_is_a_dangling_header_reference(tmp_path):
    extra_image = _with_refs(
        _arch(305, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(240, 0, 50, 50)}),
        [900, _NEW_MEDIA_STYLE_ID],
    )
    deck = _build_deck(
        tmp_path / "dangling_header.key", stylesheet_root=True, metadata=True,
        extra_slide_archives=(extra_image,),
    )
    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert _NEW_MEDIA_STYLE_ID in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_candidate_id_is_a_dangling_external_reference(tmp_path):
    import zipfile

    from keynote_parser.codec import IWAFile

    import obed_edom.iwa_write as iwa_write_mod

    deck = _build_deck(tmp_path / "dangling_external.key", stylesheet_root=True, metadata=True)
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read("Index/Metadata.iwa")
    decoded = IWAFile.from_buffer(buf, "Index/Metadata.iwa").to_dict()
    pm = iwa_write_mod._find_package_metadata_archive(decoded)["objects"][0]
    component = next(c for c in pm["components"] if c["identifier"] == str(_STYLESHEET_ROOT_ID))
    component["externalReferences"] = [
        {"componentIdentifier": str(_STYLESHEET_ROOT_ID), "objectIdentifier": _NEW_MEDIA_STYLE_ID}
    ]
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    iwa_write_mod._rewrite_members(deck, {"Index/Metadata.iwa": new_bytes})

    before = deck.read_bytes()
    result = mint_media_style(deck, "900", ["300"], _WHITE_SPEC)
    assert result["refused"]
    assert _NEW_MEDIA_STYLE_ID in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_source_style_is_itself_a_variation(tmp_path):
    variation = _arch(902, "TSD.MediaStyleArchive", {
        "super": {
            "styleIdentifier": "image-2-imageStyle",
            "parent": {"identifier": 900},
            "isVariation": True,
            "stylesheet": {"identifier": _STYLESHEET_ROOT_ID},
        },
        "mediaProperties": {"stroke": _WHITE_SOLID_STROKE},
    })
    extra_image = _with_refs(
        _arch(305, "TSD.ImageArchive", {"style": {"identifier": 902}, "super": _geom(240, 0, 50, 50)}), [902]
    )
    deck = _build_deck(
        tmp_path / "variation_source.key", stylesheet_root=True, metadata=True,
        extra_stylesheet_archives=(variation,), extra_slide_archives=(extra_image,), extra_zorder=(305,),
    )
    before = deck.read_bytes()
    result = mint_media_style(deck, "902", ["305"], _WHITE_SPEC)
    assert result["refused"]
    assert "variation" in result["reason"]
    assert deck.read_bytes() == before
