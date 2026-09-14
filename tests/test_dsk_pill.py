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
def test_reuse_refuses_an_unrelated_content_image_sharing_the_data_id(tmp_path: Path) -> None:
    """With slide 3's own pill (15156374) stripped, an untagged content image that merely
    reuses its data id (27859) but does not carry the layout pill's fingerprint (a
    different geometry/angle here) must never be selected for reuse: the mint path runs
    instead, and the unrelated image is left untouched."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    member = "Index/Slide-15156371.iwa"
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
    arch = _find_archive(decoded, "15156371")
    obj = arch["objects"][0]
    donor = copy.deepcopy(_find_archive(decoded, "15156374"))
    donor["header"] = copy.deepcopy(donor["header"])
    donor["header"]["identifier"] = "27859999"
    donor["objects"][0] = copy.deepcopy(donor["objects"][0])
    # Same data id (27859) but a different, non-fingerprint-matching geometry/angle: an
    # ordinary content image, not a pill.
    donor["objects"][0]["super"]["geometry"] = {
        "position": {"x": 10.0, "y": 20.0}, "size": {"width": 400.0, "height": 300.0},
        "flags": 3, "angle": 0.0,
    }
    decoded["chunks"][0]["archives"].append(donor)
    obj["ownedDrawables"].append({"identifier": "27859999"})
    obj["drawablesZOrder"].append({"identifier": "27859999"})
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {member: new_bytes})

    out_path = tmp_path / "out.key"
    result = P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=out_path)
    assert result.minted == 1
    assert result.reused == 0

    objects, _i2f, _fi = _load_deck_full(out_path)[:3]
    unrelated = objects["27859999"]
    assert unrelated["super"]["geometry"]["angle"] == 0.0
    assert unrelated["super"]["geometry"]["size"] == {"width": 400.0, "height": 300.0}


@needs_gold
def test_reuse_accepts_a_tagged_candidate_only_when_its_data_id_matches(tmp_path: Path) -> None:
    """With slide 3's own pill stripped, a `Media`-tagged image on the slide whose OWN
    data id differs from the resolved layout's pill data id is not eligible for reuse
    (mint runs instead)."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    member = "Index/Slide-15156371.iwa"
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
    arch = _find_archive(decoded, "15156371")
    obj = arch["objects"][0]
    donor = copy.deepcopy(_find_archive(decoded, "15156374"))
    donor["header"] = copy.deepcopy(donor["header"])
    donor["header"]["identifier"] = "27859998"
    donor["objects"][0] = copy.deepcopy(donor["objects"][0])
    donor["objects"][0]["data"] = {"identifier": "999999999"}  # foreign data id
    decoded["chunks"][0]["archives"].append(donor)
    obj["ownedDrawables"].append({"identifier": "27859998"})
    obj["drawablesZOrder"].append({"identifier": "27859998"})
    obj.setdefault("sageTagToInfoMap", []).append({"tag": "Media", "info": {"identifier": "27859998"}})
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {member: new_bytes})

    out_path = tmp_path / "out.key"
    result = P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=out_path)
    assert result.minted == 1
    assert result.reused == 0


@needs_gold
def test_verify_catches_a_dropped_mask_scalar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`_verify` re-reads and validates the FULL mask law, not just position/size: a
    corrupted `_apply_mask_fields` that stops writing the rounded-rect `scalar` is caught
    (not just the composed geometry, which is unaffected by a dropped scalar)."""
    real_apply = P._apply_mask_fields

    def broken_apply(mask_obj: dict, width: float) -> None:
        real_apply(mask_obj, width)
        mask_obj["pathsource"]["scalarPathSource"]["scalar"] = 1.0  # drop the 15.0 law

    monkeypatch.setattr(P, "_apply_mask_fields", broken_apply)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="mask"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_dropped_mask_angle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same as above for the mask's 180 deg angle, dropped after the real write."""
    real_apply = P._apply_mask_fields

    def broken_apply(mask_obj: dict, width: float) -> None:
        real_apply(mask_obj, width)
        mask_obj["super"]["geometry"]["angle"] = 0.0

    monkeypatch.setattr(P, "_apply_mask_fields", broken_apply)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="mask"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_missing_mask_path_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex review 2, finding 3: the concrete mask path type `kTSDRoundedRectangle` is
    required on reread, not merely equality with the (possibly also-missing) layout type."""
    real_apply = P._apply_mask_fields

    def broken_apply(mask_obj: dict, width: float) -> None:
        real_apply(mask_obj, width)
        mask_obj["pathsource"]["scalarPathSource"]["type"] = ""

    monkeypatch.setattr(P, "_apply_mask_fields", broken_apply)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    with pytest.raises(P.OfflineWriteRefused, match="pathsource type"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


# ------------------------------------------------------------- Codex review 2, finding 1


@needs_gold
def test_reuse_refuses_a_candidate_whose_mask_is_the_layouts_own_shared_mask(tmp_path: Path) -> None:
    """A reused pill whose `mask` reference is retargeted to the resolved layout's OWN
    mask (a mask shared with the layout's Media drawable, in a different member) must be
    refused before any mutation -- the layout's mask must never be touched."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    member = "Index/Slide-15156371.iwa"
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
    arch = _find_archive(decoded, "15156374")
    arch["objects"][0]["mask"] = {"identifier": "3654469"}  # the layout's own mask, cross-member
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {member: new_bytes})

    with zipfile.ZipFile(GOLD) as zf:
        layout_member_buf = zf.read("Index/TemplateSlide-3654281.iwa")
    layout_mask_before = _find_archive(
        IWAFile.from_buffer(layout_member_buf, "Index/TemplateSlide-3654281.iwa").to_dict(), "3654469"
    )["objects"][0]

    with pytest.raises(P.OfflineWriteRefused, match="not exclusively owned"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")

    # the layout's own mask member is untouched -- write_pills never reached the edit stage
    with zipfile.ZipFile(deck) as zf:
        layout_member_after = zf.read("Index/TemplateSlide-3654281.iwa")
    layout_mask_after = _find_archive(
        IWAFile.from_buffer(layout_member_after, "Index/TemplateSlide-3654281.iwa").to_dict(), "3654469"
    )["objects"][0]
    assert layout_mask_after == layout_mask_before


@needs_gold
def test_reuse_refuses_a_mask_shared_with_another_image(tmp_path: Path) -> None:
    """A candidate's mask (15156378) also referenced by a second, unrelated image
    anywhere in the deck must refuse the reuse mutation -- shared masks are never
    eligible, regardless of that second image's own tag or data id."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    member = "Index/Slide-15156371.iwa"
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
    arch = _find_archive(decoded, "15156371")
    obj = arch["objects"][0]
    dup_image = copy.deepcopy(_find_archive(decoded, "15156374"))
    dup_image["header"] = copy.deepcopy(dup_image["header"])
    dup_image["header"]["identifier"] = "15156998"
    dup_image["objects"][0] = copy.deepcopy(dup_image["objects"][0])
    dup_image["objects"][0]["data"] = {"identifier": "999999998"}  # unrelated data id
    dup_image["objects"][0]["mask"] = {"identifier": "15156378"}  # shares the pill's own mask
    decoded["chunks"][0]["archives"].append(dup_image)
    obj["ownedDrawables"].append({"identifier": "15156998"})
    obj["drawablesZOrder"].append({"identifier": "15156998"})
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {member: new_bytes})

    with pytest.raises(P.OfflineWriteRefused, match="not exclusively owned"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


# ------------------------------------------------------------- Codex review 2, finding 3
# (fingerprint / mask-type unit coverage; full-pipeline coverage is above and in mint tests)


def test_fingerprints_match_rejects_a_changed_raw_height_with_the_same_composed_frame() -> None:
    """`compose_geometry`'s frame does not carry height, and `_verify`'s own x/w/y checks
    do not either -- only the full fingerprint catches a raw geometry change (here, mask
    height, not width) that still composes to the same expected frame."""
    before = P._image_fingerprint({
        "super": {"geometry": {"position": {"x": 50.4, "y": 789.1},
                                "size": {"width": 300.0, "height": 100.0}, "angle": 180.0}},
        "originalSize": {"width": 500.0, "height": 500.0},
        "naturalSize": {"width": 500.0, "height": 500.0},
        "style": {"identifier": "8527"},
    })
    after = P._image_fingerprint({
        "super": {"geometry": {"position": {"x": 50.4, "y": 789.1},
                                "size": {"width": 300.0, "height": 250.0}, "angle": 180.0}},
        "originalSize": {"width": 500.0, "height": 500.0},
        "naturalSize": {"width": 500.0, "height": 500.0},
        "style": {"identifier": "8527"},
    })
    assert not P._fingerprints_match(before, after)


def test_pill_fingerprint_matches_refuses_when_mask_type_missing_on_both_sides() -> None:
    """Both sides carrying an empty/absent mask path type must not be treated as a match
    -- the concrete `kTSDRoundedRectangle` literal is required, not mere equality."""
    image_obj = {
        "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 1.0, "height": 1.0},
                                "angle": 180.0}},
        "originalSize": {"width": 1.0, "height": 1.0},
        "naturalSize": {"width": 1.0, "height": 1.0},
        "style": {"identifier": "1"},
    }
    layout_pill = copy.deepcopy(image_obj)
    mask_obj = {"pathsource": {"scalarPathSource": {"scalar": 15.0}}}
    layout_mask = {"pathsource": {"scalarPathSource": {"scalar": 15.0}}}
    assert not P._pill_fingerprint_matches(image_obj, mask_obj, layout_pill, layout_mask)


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


# ------------------------------------------------------------- minter / metadata registration


def test_minter_skips_a_candidate_id_registered_only_in_object_uuid_map_entries() -> None:
    package_meta = {
        "lastObjectIdentifier": "100",
        "components": [{"objectUuidMapEntries": [{"identifier": "101", "uuid": {"lower": "1", "upper": "2"}}]}],
    }
    minter = P._Minter(package_meta, objects={}, id_to_file={}, header_object_references=set())
    assert minter.mint_id() == "102"


def test_minter_skips_a_candidate_id_registered_only_in_external_references() -> None:
    package_meta = {
        "lastObjectIdentifier": "100",
        "components": [{"externalReferences": [{"componentIdentifier": "5", "objectIdentifier": "101"}]}],
    }
    minter = P._Minter(package_meta, objects={}, id_to_file={}, header_object_references=set())
    assert minter.mint_id() == "102"


def test_minter_skips_a_candidate_id_registered_only_in_data_references() -> None:
    package_meta = {
        "lastObjectIdentifier": "100",
        "components": [{"dataReferences": [
            {"dataIdentifier": "101", "objectReferenceList": [{"objectIdentifier": "102", "count": 1}]},
        ]}],
    }
    minter = P._Minter(package_meta, objects={}, id_to_file={}, header_object_references=set())
    assert minter.mint_id() == "103"


def test_register_data_refs_appends_to_a_pre_existing_slide_data_reference() -> None:
    component = {"dataReferences": [
        {"dataIdentifier": "27859", "objectReferenceList": [{"objectIdentifier": "999", "count": 1}]},
    ]}
    P._register_data_refs(component, "1000", ["27859", "27867"])
    by_data = {e["dataIdentifier"]: e for e in component["dataReferences"]}
    assert [r["objectIdentifier"] for r in by_data["27859"]["objectReferenceList"]] == ["999", "1000"]
    assert [r["objectIdentifier"] for r in by_data["27867"]["objectReferenceList"]] == ["1000"]


def test_register_style_ext_ref_accepts_a_same_component_match_idempotently() -> None:
    component = {"externalReferences": [{"componentIdentifier": "7", "objectIdentifier": "8527"}]}
    P._register_style_ext_ref(component, "8527", "7")
    assert component["externalReferences"] == [{"componentIdentifier": "7", "objectIdentifier": "8527"}]


def test_register_style_ext_ref_refuses_a_conflicting_component_id() -> None:
    component = {"externalReferences": [{"componentIdentifier": "7", "objectIdentifier": "8527"}]}
    with pytest.raises(P.OfflineWriteRefused, match="already registered"):
        P._register_style_ext_ref(component, "8527", "9")


def test_register_style_ext_ref_appends_a_new_cross_member_reference() -> None:
    component = {}
    P._register_style_ext_ref(component, "8527", "7")
    assert component["externalReferences"] == [{"componentIdentifier": "7", "objectIdentifier": "8527"}]


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
def test_synthetic_r12b_media_slot_copy_path_mints_exactly_one_pill_and_touches_nothing_else(
    tmp_path: Path,
) -> None:
    """SYNTHETIC mint case, not a real L2/L3-imported layout: r12b has no pills anywhere
    (§1.6), so `_build_r12b_media_slot_fixture` manually grafts a `Media`-tagged pill and
    hand-builds the metadata shape (objectUuidMapEntries/dataReferences/externalReferences)
    the writer relies on, onto r12b's own real `Blank Black` layout and real Data/ files.
    Replace with a fixture produced by the real importer once L2/L3 land (plan note, L4).
    Onto that fixture, writing a 301.829-wide pill mints exactly one pill drawable
    satisfying the mask law, and every other object in the deck -- including every other
    member byte-for-byte -- is untouched."""
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


# ------------------------------------------------------------- Codex review 2, finding 2
# Mint metadata verification must be exact-component, not global. Each test below uses
# gold's own mint path (slide 3's own pill stripped) with one registration step broken.


@needs_gold
def test_verify_catches_minted_ids_missing_uuid_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "_register_new_ids", lambda component, minter, new_ids: None)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="objectUuidMapEntries"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_minted_ids_registered_in_the_wrong_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior global scan would have accepted registration anywhere in the package;
    `_verify` must now require it in the target slide component specifically."""
    real_register = P._register_new_ids

    def broken_register(component: dict, minter: P._Minter, new_ids: list[str]) -> None:
        wrong = next(
            c for c in (minter._package_meta.get("components") or []) if c is not component
        )
        real_register(wrong, minter, new_ids)

    monkeypatch.setattr(P, "_register_new_ids", broken_register)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="objectUuidMapEntries"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_dropped_data_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "_register_data_refs", lambda component, image_id, data_ids: None)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="data id"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_dropped_style_external_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Slide 3's layout pill style (8527) lives in `Index/DocumentStylesheet.iwa`, a
    different member from the slide -- the cross-component path `_register_style_ext_ref`
    normally exercises. Gold's slide component already carries this ext ref from other
    usage, so it is stripped first (else a no-op registration would be masked by the
    pre-existing entry); dropping the registration must then fail verification."""
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with zipfile.ZipFile(deck) as zf:
        meta_buf = zf.read("Index/Metadata.iwa")
    meta_decoded = IWAFile.from_buffer(meta_buf, "Index/Metadata.iwa").to_dict()
    package_meta = _find_package_metadata_archive(meta_decoded)["objects"][0]
    slide_comp = _components_by_locator(package_meta.get("components") or [])[
        _member_locator("Index/Slide-15156371.iwa")
    ][0]
    slide_comp["externalReferences"] = [
        r for r in (slide_comp.get("externalReferences") or []) if str(r.get("objectIdentifier")) != "8527"
    ]
    new_meta_bytes = IWAFile.from_dict(copy.deepcopy(meta_decoded)).to_buffer()
    _rewrite_members(deck, {"Index/Metadata.iwa": new_meta_bytes})

    monkeypatch.setattr(
        P, "_register_style_ext_ref", lambda component, style_id, style_component_id: None
    )
    with pytest.raises(P.OfflineWriteRefused, match="style"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_persisted_counter_that_does_not_match_the_final_mint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_mint_id = P._Minter.mint_id

    def broken_mint_id(self: P._Minter) -> str:
        cand = real_mint_id(self)
        self._package_meta["lastObjectIdentifier"] = str(int(cand) - 1)
        return cand

    monkeypatch.setattr(P._Minter, "mint_id", broken_mint_id)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="lastObjectIdentifier"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


# ------------------------------------------------------------- Codex review 3, finding 1
# The resolved layout's own Media mask must fully resolve BEFORE any candidate is
# considered -- gold slide 3, layout member Index/TemplateSlide-3654281.iwa, layout pill
# 3654467, layout mask 3654469.

_GOLD_LAYOUT_MEMBER = "Index/TemplateSlide-3654281.iwa"
_GOLD_LAYOUT_PILL = "3654467"
_GOLD_LAYOUT_MASK = "3654469"


def _corrupt_gold_layout_mask(deck: Path, mutate) -> None:
    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(_GOLD_LAYOUT_MEMBER)
    decoded = IWAFile.from_buffer(buf, _GOLD_LAYOUT_MEMBER).to_dict()
    mutate(decoded)
    new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
    _rewrite_members(deck, {_GOLD_LAYOUT_MEMBER: new_bytes})


@needs_gold
def test_layout_mask_unresolved_refuses_before_any_candidate(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")

    def mutate(decoded: dict) -> None:
        arch = _find_archive(decoded, _GOLD_LAYOUT_PILL)
        arch["objects"][0]["mask"] = {"identifier": "999999999"}

    _corrupt_gold_layout_mask(deck, mutate)
    with pytest.raises(P.OfflineWriteRefused, match="unresolved"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_layout_mask_wrong_parent_refuses_before_any_candidate(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")

    def mutate(decoded: dict) -> None:
        arch = _find_archive(decoded, _GOLD_LAYOUT_MASK)
        arch["objects"][0]["super"]["parent"] = {"identifier": "999999999"}

    _corrupt_gold_layout_mask(deck, mutate)
    with pytest.raises(P.OfflineWriteRefused, match="parent"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_layout_mask_wrong_path_type_refuses_before_any_candidate(tmp_path: Path) -> None:
    deck = _copy_deck(GOLD, tmp_path, "gold.key")

    def mutate(decoded: dict) -> None:
        arch = _find_archive(decoded, _GOLD_LAYOUT_MASK)
        arch["objects"][0]["pathsource"]["scalarPathSource"]["type"] = ""

    _corrupt_gold_layout_mask(deck, mutate)
    with pytest.raises(P.OfflineWriteRefused, match="pathsource type"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


# ------------------------------------------------------------- Codex review 3, finding 2
# Mint object-graph verification: all four archives, exact image<->mask/title/caption
# wiring, and re-run exclusive mask ownership on the re-read output. Each test lets the
# real write happen, then corrupts the already-rewritten out_path (monkeypatching
# `_rewrite_members` to run the real rewrite first) so `_verify`'s re-read is what fails.


def _minted_graph_ids(path: Path, member: str, slide_id: str) -> tuple[str, str, str, str]:
    with zipfile.ZipFile(path) as zf:
        buf = zf.read(member)
    decoded = IWAFile.from_buffer(buf, member).to_dict()
    slide_obj = _find_archive(decoded, slide_id)["objects"][0]
    image_id = str(slide_obj["ownedDrawables"][-1]["identifier"])
    image_obj = _find_archive(decoded, image_id)["objects"][0]
    mask_id = str(image_obj["mask"]["identifier"])
    title_id = str(image_obj["super"]["title"]["identifier"])
    caption_id = str(image_obj["super"]["caption"]["identifier"])
    return image_id, mask_id, title_id, caption_id


@needs_gold
def test_verify_catches_a_missing_minted_caption_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_rewrite = P._rewrite_members
    member = "Index/Slide-15156371.iwa"

    def corrupt_rewrite(path: Path, edits: dict) -> None:
        real_rewrite(path, edits)
        _image_id, _mask_id, _title_id, caption_id = _minted_graph_ids(path, member, "15156371")
        with zipfile.ZipFile(path) as zf:
            buf = zf.read(member)
        decoded = IWAFile.from_buffer(buf, member).to_dict()
        decoded["chunks"][0]["archives"] = [
            a for a in decoded["chunks"][0]["archives"]
            if str(a["header"]["identifier"]) != caption_id
        ]
        new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
        real_rewrite(path, {member: new_bytes})

    monkeypatch.setattr(P, "_rewrite_members", corrupt_rewrite)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, member, "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="caption archive"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_minted_mask_whose_parent_is_not_the_minted_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_rewrite = P._rewrite_members
    member = "Index/Slide-15156371.iwa"

    def corrupt_rewrite(path: Path, edits: dict) -> None:
        real_rewrite(path, edits)
        _image_id, mask_id, _title_id, _caption_id = _minted_graph_ids(path, member, "15156371")
        with zipfile.ZipFile(path) as zf:
            buf = zf.read(member)
        decoded = IWAFile.from_buffer(buf, member).to_dict()
        mask_arch = _find_archive(decoded, mask_id)
        mask_arch["objects"][0]["super"]["parent"] = {"identifier": "999999999"}
        new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
        real_rewrite(path, {member: new_bytes})

    monkeypatch.setattr(P, "_rewrite_members", corrupt_rewrite)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, member, "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="parent"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_substituted_minted_mask_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The minted image's own `mask` reference is retargeted to a byte-for-byte DUPLICATE
    of the correctly-written minted mask (same fields, satisfies the mask law for this
    width identically) under a different id -- `_verify` must still refuse because it is
    not the exact id it minted, not merely because the geometry looks right."""
    real_rewrite = P._rewrite_members
    member = "Index/Slide-15156371.iwa"

    def corrupt_rewrite(path: Path, edits: dict) -> None:
        real_rewrite(path, edits)
        image_id, mask_id, _title_id, _caption_id = _minted_graph_ids(path, member, "15156371")
        with zipfile.ZipFile(path) as zf:
            buf = zf.read(member)
        decoded = IWAFile.from_buffer(buf, member).to_dict()
        mask_arch = _find_archive(decoded, mask_id)
        dup_mask = copy.deepcopy(mask_arch)
        dup_mask["header"] = copy.deepcopy(dup_mask["header"])
        dup_mask["header"]["identifier"] = "888888888"
        decoded["chunks"][0]["archives"].append(dup_mask)
        image_arch = _find_archive(decoded, image_id)
        image_arch["objects"][0]["mask"] = {"identifier": "888888888"}
        new_bytes = IWAFile.from_dict(copy.deepcopy(decoded)).to_buffer()
        real_rewrite(path, {member: new_bytes})

    monkeypatch.setattr(P, "_rewrite_members", corrupt_rewrite)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, member, "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="references"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


# ------------------------------------------------------------- Codex review 3, finding 3
# Metadata verification must count over the raw lists: exactly one entry per minted id /
# expected data id / non-conflicting style reference, not mere containment.


@needs_gold
def test_verify_catches_a_duplicate_uuid_entry_for_a_minted_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_register = P._register_new_ids

    def dup_register(component: dict, minter: P._Minter, new_ids: list[str]) -> None:
        real_register(component, minter, new_ids)
        component["objectUuidMapEntries"].append({"identifier": new_ids[0], "uuid": minter.mint_uuid()})

    monkeypatch.setattr(P, "_register_new_ids", dup_register)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="objectUuidMapEntries"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_duplicate_data_reference_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_register = P._register_data_refs

    def dup_register(component: dict, image_id: str, data_ids: list[str]) -> None:
        real_register(component, image_id, data_ids)
        for did in data_ids:
            component["dataReferences"].append(
                {"dataIdentifier": did, "objectReferenceList": [{"objectIdentifier": image_id, "count": 1}]}
            )

    monkeypatch.setattr(P, "_register_data_refs", dup_register)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="dataReferences entries"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")


@needs_gold
def test_verify_catches_a_correct_plus_conflicting_style_reference_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_register = P._register_style_ext_ref

    def conflicting_register(component: dict, style_id: str, style_component_id: str) -> None:
        real_register(component, style_id, style_component_id)
        component["externalReferences"].append(
            {"componentIdentifier": "999999999", "objectIdentifier": style_id}
        )

    monkeypatch.setattr(P, "_register_style_ext_ref", conflicting_register)
    deck = _copy_deck(GOLD, tmp_path, "gold.key")
    _strip_own_pill(deck, "Index/Slide-15156371.iwa", "15156371", "15156374")
    with pytest.raises(P.OfflineWriteRefused, match="non-conflicting"):
        P.write_pills(deck, slides={3: P.PillSpec(301.8292, "standard")}, out_path=tmp_path / "out.key")
