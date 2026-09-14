"""Deck-marked and unit coverage for `dsk_pill.write_pills` (§1.4 mask law, plan §3 L4)."""
from __future__ import annotations

import copy
import secrets
import shutil
import zipfile
from pathlib import Path

import pytest
from keynote_parser.codec import IWAFile

from obed_edom import dsk_pill as P
from obed_edom.iwa_geometry import compose_geometry
from obed_edom.iwa_runs import _load_deck_full, slide_order
from obed_edom.iwa_write import (
    _components_by_locator,
    _find_archive,
    _find_package_metadata_archive,
    _member_locator,
    _rewrite_members,
)

GOLD = Path.home() / "Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key"
R12B = Path.home() / "Desktop/dsk-d4-work/out-r12b/Sermon_PK_DSK.key"

# Gold's own 8 measured pill widths (§1.4): 7 gold slides + the layout's own default.
GOLD_WIDTHS = {
    3: (301.8292, "standard"),
    5: (258.04858, "one_line"),
    9: (279.41565, "standard"),
    20: (308.11703, "standard"),
    23: (355.3282, "standard"),
    35: (202.55704, "standard"),
    38: (362.11707, "standard"),
}
LAYOUT_DEFAULT_WIDTH = 958.4864

needs_gold = pytest.mark.skipif(not GOLD.exists(), reason="local gold deck only")
needs_r12b = pytest.mark.skipif(not R12B.exists(), reason="local r12b output deck only")


def _copy_deck(src: Path, tmp_path: Path, name: str) -> Path:
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return dst


def _all_specs(width_map: dict[int, tuple[float, str]]) -> dict[int, P.PillSpec]:
    return {n: P.PillSpec(w, layout) for n, (w, layout) in width_map.items()}


def _byte_diff(before: Path, after: Path, touched: set[str]) -> list[str]:
    zin, zout = zipfile.ZipFile(before), zipfile.ZipFile(after)
    return [n for n in zin.namelist() if n not in touched and zin.read(n) != zout.read(n)]


# --------------------------------------------------------------------------- mask law


def test_mask_law_constants_are_the_measured_values() -> None:
    assert P._MASK_Y == 50.9344
    assert P._MASK_H == 75.52111
    assert P._MASK_RIGHT == 1832.5315
    assert P._MAX_WIDTH == 958.4864
    assert P._FRAME_X == 50.4
    assert P._LAYOUT_FRAME_Y == {"standard": 789.1, "one_line": 879.1}


@pytest.mark.parametrize("width", [
    301.8292, 258.04858, 279.41565, 308.11703, 355.3282, 202.55704, 362.11707, 958.4864,
])
def test_apply_mask_fields_satisfies_the_law(width: float) -> None:
    mask_obj = {
        "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 1.0, "height": 1.0},
                                "flags": 3, "angle": 90.0}},
        "pathsource": {"scalarPathSource": {"type": "kTSDRoundedRectangle", "scalar": 1.0,
                                             "naturalSize": {"width": 1.0, "height": 1.0},
                                             "isCurveContinuous": True}},
    }
    P._apply_mask_fields(mask_obj, width)
    geom = mask_obj["super"]["geometry"]
    assert geom["position"] == {"x": pytest.approx(P._MASK_RIGHT - width), "y": P._MASK_Y}
    assert geom["size"] == {"width": width, "height": P._MASK_H}
    assert geom["angle"] == 180.0
    assert geom["flags"] == 3  # untouched sibling field survives the update
    sps = mask_obj["pathsource"]["scalarPathSource"]
    assert sps["naturalSize"] == {"width": width, "height": P._MASK_H}
    assert sps["scalar"] == P._MASK_SCALAR
    assert sps["isCurveContinuous"] is True
    assert P._mask_law_ok(geom, width)


def test_mask_law_rejects_a_displaced_mask() -> None:
    bad = {"position": {"x": 0.0, "y": P._MASK_Y}, "size": {"width": 100.0, "height": P._MASK_H}}
    assert not P._mask_law_ok(bad, 100.0)


# --------------------------------------------------------------------- refusal paths


@needs_gold
def test_refuses_width_at_or_below_zero(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="width"):
        P.write_pills(deck, slides={3: P.PillSpec(0.0, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_refuses_width_above_layout_default(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="width"):
        P.write_pills(deck, slides={3: P.PillSpec(P._MAX_WIDTH + 0.01, "standard")},
                     out_path=tmp_path / "out.key")


@needs_gold
def test_refuses_a_slide_whose_layout_has_no_media_slot(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="no Media slot"):
        P.write_pills(deck, slides={1: P.PillSpec(300.0, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_refuses_a_declared_layout_that_does_not_match_the_resolved_one(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="frame y"):
        P.write_pills(deck, slides={3: P.PillSpec(300.0, "one_line")}, out_path=tmp_path / "out.key")


def test_refuses_empty_slides(tmp_path: Path) -> None:
    with pytest.raises(P.OfflineWriteRefused, match="empty"):
        P.write_pills(tmp_path / "nonexistent.key", slides={}, out_path=tmp_path / "out.key")


@needs_gold
def test_refuses_more_than_one_candidate_pill(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    member = "Index/Slide-15156371.iwa"
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
    arch = _find_archive(decoded, "15156371")
    obj = arch["objects"][0]
    dup_image = copy.deepcopy(_find_archive(decoded, "15156374"))
    dup_image["header"] = copy.deepcopy(dup_image["header"])
    dup_image["header"]["identifier"] = "15156999"
    dup_image["objects"][0] = copy.deepcopy(dup_image["objects"][0])
    decoded["chunks"][0]["archives"].append(dup_image)
    obj["ownedDrawables"].append({"identifier": "15156999"})
    obj["drawablesZOrder"].append({"identifier": "15156999"})
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {member: new_bytes})

    with pytest.raises(P.OfflineWriteRefused, match="candidate pill"):
        P.write_pills(deck, slides={3: P.PillSpec(300.0, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_never_writes_in_place(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    before = deck.read_bytes()
    out_path = tmp_path / "out.key"
    P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=out_path)
    assert deck.read_bytes() == before
    assert out_path.exists()


# ------------------------------------------------------------------------- gold round trip


@needs_gold
def test_gold_round_trip_is_idempotent_on_its_own_widths(tmp_path: Path) -> None:
    """Writing each gold verse slide's OWN measured width back reproduces gold exactly:
    every non-touched member byte-identical, every touched pill's composed frame/mask
    unchanged within 0.01pt."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    out_path = tmp_path / "out.key"
    specs = _all_specs(GOLD_WIDTHS)
    result = P.write_pills(deck, slides=specs, out_path=out_path)
    assert result.applied == len(GOLD_WIDTHS)
    assert result.reused == len(GOLD_WIDTHS)
    assert result.minted == 0

    assert _byte_diff(GOLD, out_path, set(result.members)) == []

    objects, _id_to_file, _file_ids = _load_deck_full(out_path)[:3]
    order = slide_order(objects)
    for n, (width, layout) in GOLD_WIDTHS.items():
        slide = objects[order[n - 1][0]]
        recs = compose_geometry(slide, objects)
        pills = [r for r in recs if r["kind"] == "image" and r["w"] == pytest.approx(width, abs=0.05)]
        assert len(pills) == 1, (n, recs)
        rec = pills[0]
        assert rec["x"] == pytest.approx(P._FRAME_X, abs=0.02)
        assert rec["y"] == pytest.approx(P._LAYOUT_FRAME_Y[layout], abs=0.02)
        mask_id = str(objects[rec["id"]]["mask"]["identifier"])
        mask_geom = objects[mask_id]["super"]["geometry"]
        assert P._mask_law_ok(mask_geom, width)


@needs_gold
@pytest.mark.parametrize("ordinal,width,layout", [(n, w, layout) for n, (w, layout) in GOLD_WIDTHS.items()])
def test_gold_round_trip_single_slide(tmp_path: Path, ordinal: int, width: float, layout: str) -> None:
    deck = _copy_deck(GOLD, tmp_path, f"gold-{ordinal}.key")
    out_path = tmp_path / "out.key"
    result = P.write_pills(deck, slides={ordinal: P.PillSpec(width, layout)}, out_path=out_path)
    assert result.reused == 1
    assert result.minted == 0


@needs_gold
def test_gold_layout_default_width_round_trips(tmp_path: Path) -> None:
    """The layout's own default width (958.4864, the max) also satisfies the law when
    written onto a gold slide."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    out_path = tmp_path / "out.key"
    P.write_pills(deck, slides={3: P.PillSpec(LAYOUT_DEFAULT_WIDTH, "standard")}, out_path=out_path)
    objects, _i2f, _fi = _load_deck_full(out_path)[:3]
    order = slide_order(objects)
    recs = compose_geometry(objects[order[2][0]], objects)
    pills = [r for r in recs if r["kind"] == "image"]
    assert len(pills) == 1
    assert pills[0]["w"] == pytest.approx(LAYOUT_DEFAULT_WIDTH, abs=0.02)
    assert pills[0]["x"] == pytest.approx(P._FRAME_X, abs=0.02)


# --------------------------------------------------------------------- copy (mint) path, in gold


def _strip_own_pill(deck: Path, slide_member: str, slide_id: str, pill_id: str) -> None:
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(slide_member)
    decoded = IWAFile.from_buffer(buf, slide_member).to_dict()
    arch = _find_archive(decoded, slide_id)
    obj = arch["objects"][0]
    obj["ownedDrawables"] = [r for r in obj["ownedDrawables"] if str(r["identifier"]) != pill_id]
    obj["drawablesZOrder"] = [r for r in obj["drawablesZOrder"] if str(r["identifier"]) != pill_id]
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {slide_member: new_bytes})


@needs_gold
def test_mint_path_reproduces_gold_after_stripping_the_own_pill(tmp_path: Path) -> None:
    """Slide 3's own pill (15156374) stripped, then re-derived by copying the layout's
    Media drawable: the minted pill reproduces gold's original frame/mask exactly."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")

    out_path = tmp_path / "out.key"
    result = P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=out_path)
    assert result.minted == 1
    assert result.reused == 0

    objects, _i2f, _fi = _load_deck_full(out_path)[:3]
    order = slide_order(objects)
    recs = compose_geometry(objects[order[2][0]], objects)
    pills = [r for r in recs if r["kind"] == "image"]
    assert len(pills) == 1
    rec = pills[0]
    assert rec["id"] != "15156374"  # a fresh id was minted, not reused
    assert rec["x"] == pytest.approx(P._FRAME_X, abs=0.02)
    assert rec["y"] == pytest.approx(P._LAYOUT_FRAME_Y["standard"], abs=0.02)
    assert rec["w"] == pytest.approx(301.8292, abs=0.02)
    mask_id = str(objects[rec["id"]]["mask"]["identifier"])
    assert P._mask_law_ok(objects[mask_id]["super"]["geometry"], 301.8292)


# ------------------------------------------------------------------- copy path, r12b fixture


_R12B_LAYOUT_MEMBER = "Index/TemplateSlide-17638910.iwa"
_R12B_LAYOUT_ID = "17638910"
_R12B_STYLE_ID = "2652415"
_DONOR_MEMBER = "Index/TemplateSlide-3654281.iwa"
_DONOR_IMAGE, _DONOR_MASK, _DONOR_TITLE, _DONOR_CAPTION = "3654467", "3654469", "3654504", "3654494"
_DONOR_STYLE = "8527"
_DATA_IDS = ["27859", "27867", "27866", "27860"]
_FIXTURE_OFFSET = 900_000_000


def _mint_uuid(existing: set[tuple[str, str]]) -> dict:
    lower, upper = secrets.randbits(64), secrets.randbits(64)
    while (lower, upper) == (0, 0) or (str(lower), str(upper)) in existing:
        lower, upper = secrets.randbits(64), secrets.randbits(64)
    existing.add((str(lower), str(upper)))
    return {"lower": str(lower), "upper": str(upper)}


def _build_r12b_media_slot_fixture(tmp_path: Path) -> Path:
    """r12b's own `Blank Black` layout (id 17638910, currently pill-less -- §1.6) gets a
    synthetic `Media`-tagged pill, minted by copying gold's own donor archives (image,
    mask, title, caption) at a safe id offset, wired to an EXISTING r12b media style
    (2652415) so no cross-deck stylesheet needs importing, and gold's Data/ files for the
    pill's data ids copied in verbatim. This makes r12b -- which has no pill anywhere,
    §1.6 -- resolvable exactly like a live L2/L3 layout import would leave it, so the
    `write_pills` COPY path can be exercised end to end on the real r12b deck."""
    fixture = _copy_deck(R12B, tmp_path, "r12b.key")
    new_img = str(_FIXTURE_OFFSET + 1)
    new_mask = str(_FIXTURE_OFFSET + 2)
    new_title = str(_FIXTURE_OFFSET + 3)
    new_caption = str(_FIXTURE_OFFSET + 4)

    with zipfile.ZipFile(GOLD) as zf:
        donor_buf = zf.read(_DONOR_MEMBER)
        data_files = {
            n: zf.read(n) for n in zf.namelist()
            if n.startswith("Data/") and any(f"-{d}." in n for d in _DATA_IDS)
        }
    assert len(data_files) == len(_DATA_IDS)

    donor_decoded = IWAFile.from_buffer(donor_buf, _DONOR_MEMBER).to_dict()
    img_arch = _find_archive(donor_decoded, _DONOR_IMAGE)
    mask_arch = _find_archive(donor_decoded, _DONOR_MASK)
    title_arch = _find_archive(donor_decoded, _DONOR_TITLE)
    caption_arch = _find_archive(donor_decoded, _DONOR_CAPTION)

    new_img_obj = copy.deepcopy(img_arch["objects"][0])
    new_img_obj["super"]["parent"] = {"identifier": _R12B_LAYOUT_ID}
    new_img_obj["super"]["title"] = {"identifier": new_title}
    new_img_obj["super"]["caption"] = {"identifier": new_caption}
    new_img_obj["mask"] = {"identifier": new_mask}
    new_img_obj["style"] = {"identifier": _R12B_STYLE_ID}
    new_img_header = copy.deepcopy(img_arch["header"])
    new_img_header["identifier"] = new_img
    remap = {_DONOR_CAPTION: new_caption, _DONOR_TITLE: new_title,
             _DONOR_STYLE: _R12B_STYLE_ID, _DONOR_MASK: new_mask}
    for mi in new_img_header.get("messageInfos") or []:
        if mi.get("objectReferences"):
            mi["objectReferences"] = [remap.get(r, r) for r in mi["objectReferences"]]

    new_mask_obj = copy.deepcopy(mask_arch["objects"][0])
    new_mask_obj["super"]["parent"] = {"identifier": new_img}
    new_mask_header = copy.deepcopy(mask_arch["header"])
    new_mask_header["identifier"] = new_mask

    new_title_obj = copy.deepcopy(title_arch["objects"][0])
    new_title_header = copy.deepcopy(title_arch["header"])
    new_title_header["identifier"] = new_title

    new_caption_obj = copy.deepcopy(caption_arch["objects"][0])
    new_caption_header = copy.deepcopy(caption_arch["header"])
    new_caption_header["identifier"] = new_caption

    with zipfile.ZipFile(fixture) as zf:
        layout_buf = zf.read(_R12B_LAYOUT_MEMBER)
        meta_buf = zf.read("Index/Metadata.iwa")

    layout_decoded = IWAFile.from_buffer(layout_buf, _R12B_LAYOUT_MEMBER).to_dict()
    layout_decoded["chunks"][0]["archives"].extend([
        {"header": new_img_header, "objects": [new_img_obj]},
        {"header": new_mask_header, "objects": [new_mask_obj]},
        {"header": new_title_header, "objects": [new_title_obj]},
        {"header": new_caption_header, "objects": [new_caption_obj]},
    ])
    layout_arch = _find_archive(layout_decoded, _R12B_LAYOUT_ID)
    layout_obj = layout_arch["objects"][0]
    layout_obj.setdefault("ownedDrawables", []).append({"identifier": new_img})
    layout_obj.setdefault("drawablesZOrder", []).append({"identifier": new_img})
    layout_obj.setdefault("sageTagToInfoMap", []).append({"tag": "Media", "info": {"identifier": new_img}})

    meta_decoded = IWAFile.from_buffer(meta_buf, "Index/Metadata.iwa").to_dict()
    meta_arch = _find_package_metadata_archive(meta_decoded)
    package_meta = meta_arch["objects"][0]
    package_meta["lastObjectIdentifier"] = str(_FIXTURE_OFFSET + 4)
    comps_by_loc = _components_by_locator(package_meta.get("components") or [])
    layout_comp = comps_by_loc[_member_locator(_R12B_LAYOUT_MEMBER)][0]

    existing_uuids: set[tuple[str, str]] = set()
    for comp in package_meta.get("components") or []:
        for entry in comp.get("objectUuidMapEntries") or []:
            uuid = entry.get("uuid") or {}
            existing_uuids.add((str(uuid.get("lower")), str(uuid.get("upper"))))
    uuid_entries = layout_comp.setdefault("objectUuidMapEntries", [])
    for nid in (new_img, new_mask, new_title, new_caption):
        uuid_entries.append({"identifier": nid, "uuid": _mint_uuid(existing_uuids)})

    by_data = {str(e.get("dataIdentifier")): e for e in layout_comp.get("dataReferences") or []}
    for did in _DATA_IDS:
        entry = by_data.get(did)
        if entry is None:
            entry = {"dataIdentifier": did, "objectReferenceList": []}
            layout_comp.setdefault("dataReferences", []).append(entry)
        entry.setdefault("objectReferenceList", []).append({"objectIdentifier": new_img, "count": 1})

    style_comp = comps_by_loc[_member_locator("Index/DocumentStylesheet.iwa")][0]
    ext_refs = layout_comp.setdefault("externalReferences", [])
    if not any(str(r.get("objectIdentifier")) == _R12B_STYLE_ID for r in ext_refs):
        ext_refs.append({"componentIdentifier": str(style_comp["identifier"]), "objectIdentifier": _R12B_STYLE_ID})

    new_layout_bytes = IWAFile.from_dict(copy.deepcopy(layout_decoded)).to_buffer()
    IWAFile.from_buffer(new_layout_bytes, _R12B_LAYOUT_MEMBER)  # reparse sanity
    new_meta_bytes = IWAFile.from_dict(copy.deepcopy(meta_decoded)).to_buffer()
    IWAFile.from_buffer(new_meta_bytes, "Index/Metadata.iwa")

    _rewrite_members(fixture, {_R12B_LAYOUT_MEMBER: new_layout_bytes, "Index/Metadata.iwa": new_meta_bytes})
    with zipfile.ZipFile(fixture, "a") as zf:
        present = set(zf.namelist())
        for name, data in data_files.items():
            if name not in present:
                zf.writestr(name, data)
    return fixture


@needs_gold
@needs_r12b
def test_r12b_copy_path_mints_exactly_one_pill_and_touches_nothing_else(tmp_path: Path) -> None:
    """r12b has no pills anywhere (§1.6). Onto a fixture where ordinal 1's resolved
    layout has been given a Media slot (see `_build_r12b_media_slot_fixture`), writing a
    301.829-wide pill mints exactly one pill drawable satisfying the mask law, and every
    other object in the deck -- including every other member byte-for-byte -- is
    untouched."""
    fixture = _build_r12b_media_slot_fixture(tmp_path)
    out_path = tmp_path / "out.key"
    result = P.write_pills(fixture, slides={1: P.PillSpec(301.829, "standard")}, out_path=out_path)
    assert result.minted == 1
    assert result.reused == 0

    assert _byte_diff(fixture, out_path, set(result.members)) == []

    objects, _i2f, _fi = _load_deck_full(out_path)[:3]
    order = slide_order(objects)
    recs = compose_geometry(objects[order[0][0]], objects)
    pills = [r for r in recs if r["kind"] == "image"]
    assert len(pills) == 1
    rec = pills[0]
    assert rec["x"] == pytest.approx(P._FRAME_X, abs=0.02)
    assert rec["y"] == pytest.approx(P._LAYOUT_FRAME_Y["standard"], abs=0.02)
    assert rec["w"] == pytest.approx(301.829, abs=0.02)
    mask_id = str(objects[rec["id"]]["mask"]["identifier"])
    assert P._mask_law_ok(objects[mask_id]["super"]["geometry"], 301.829)

    # every other slide's own owned drawables are untouched
    for idx, (sid, _skipped) in enumerate(order):
        if idx == 0:
            continue
        slide = objects[sid]
        assert not any(
            (objects.get(str(r["identifier"])) or {}).get("_pbtype") == "TSD.ImageArchive"
            and str((objects[str(r["identifier"])].get("data") or {}).get("identifier")) == "27859"
            for r in (slide.get("ownedDrawables") or [])
        )
